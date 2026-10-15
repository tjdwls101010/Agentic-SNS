"""--out files: NDJSON committed a whole page at a time, so an interrupted collection resumes where it stopped.

Line 1 is a header (kind header, format, the query context, started_at). Then records, each page closed by a marker
(kind page, the state to resume from, ids and n of the records above it, stop_reason, skipped, coverage). Only
complete pages are trusted: the tail after the last marker is dropped and read again. A file for another query or an
older format is refused before any byte changes.
"""
import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from facebook.errors import FacebookError

# Bumped whenever a saved page or the header changes meaning.
FORMAT = 3
COMPLETE = ('exhausted', 'window_reached')


def _line(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def describe():
    """The --out file schema."""
    return {
        'object': 'out',
        'description': 'The NDJSON file --out writes: one header, then records, each page closed by a page line.',
        'format': FORMAT,
        'lines': {
            'header': 'first line: kind "header", format, context (command, target, order, filters, account_id), '
                      'started_at',
            'record': 'a post, comment, entity or about record (see schema <object>)',
            'page': 'after each committed page: kind "page" with no id, state (where the next page starts), ids and n '
                    'of the records above it, stop_reason, skipped (ids left out, e.g. advertisements), coverage',
        },
        'resume': 'Rerun the same command with the same --out path: records after the last page line are dropped and '
                  'read again, saved ids are not written twice, and --limit counts what is saved (parent comments '
                  'for comments). A complete file reads nothing. A file for another query, an earlier format or one '
                  'whose pages do not match their records is refused before any byte changes; use a new path.',
        'privacy': 'The file holds other people\'s names, words and profile links. Keep it outside the repository '
                   'and delete it when the task is done.',
    }


class OutFile:
    """One --out file opened for one query context; the lock is held until close()."""

    def __init__(self, path, context):
        self.path, self.context = Path(path).expanduser(), context
        self.ids, self.skipped = set(), set()
        self.count = self.parent_count = 0
        self.state, self.complete = None, False
        self.stream = None
        try:
            self.stream = os.fdopen(os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600), 'r+b')
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.close()
            raise FacebookError(2, 'Cannot open or lock the --out file.', 'Choose a writable path that no other '
                                                                         'command is writing.') from None
        try:
            self._recover()
        except FacebookError:
            self.close()
            raise
        except (OSError, ValueError):
            self.close()
            raise FacebookError(2, 'Cannot read the --out file.', 'Use a new --out path.') from None

    def _recover(self):
        first = self.stream.readline()
        if not first:
            self.stream.write(_line({'kind': 'header', 'format': FORMAT, 'context': self.context,
                                     'started_at': datetime.now(timezone.utc).isoformat()}))
            self.stream.flush()
            os.fsync(self.stream.fileno())
            return
        try:
            header = json.loads(first)
        except ValueError:
            header = None
        if not isinstance(header, dict) or header.get('kind') != 'header':
            raise FacebookError(2, 'The --out file is not a collection written by this skill.', 'Use a new --out '
                                                                                               'path.')
        if header.get('format') != FORMAT:
            raise FacebookError(2, 'The --out file was written by an earlier version of this skill.',
                                'Use a new --out path; the old file is left as it was.')
        if header.get('context') != self.context:
            raise FacebookError(2, 'The --out file belongs to another command, target, order or account.',
                                'Use a new --out path, or rerun the command that started this file.')
        boundary, page = self.stream.tell(), []
        ids, skipped, count, parents, state, complete = set(), set(), 0, 0, None, False
        while line := self.stream.readline():
            if not line.endswith(b'\n'):
                break
            try:
                record = json.loads(line)
            except ValueError:
                break
            if not isinstance(record, dict):
                break
            if record.get('kind') == 'page' and 'id' not in record:
                page_ids = [r.get('id') for r in page]
                if record.get('ids') != page_ids or record.get('n') != len(page):
                    raise FacebookError(2, 'The --out file failed its integrity check: a page line does not match '
                                           'the records above it.', 'Keep this file as it is and use a new path.')
                ids.update(i for i in page_ids if i is not None)
                skipped.update(record.get('skipped') or [])
                count += len(page)
                parents += sum(1 for r in page if r.get('depth') == 0)
                state = record.get('state')
                complete = record.get('stop_reason') in COMPLETE
                boundary, page = self.stream.tell(), []
            else:
                page.append(record)
        self.ids, self.skipped, self.count, self.parent_count = ids, skipped, count, parents
        self.state, self.complete = state, complete
        self.stream.seek(boundary)
        self.stream.truncate()

    def commit(self, records, state, stop_reason, skipped=(), notes=()):
        """Append one page and its marker, fsynced; records whose id is already saved are left out."""
        page, new = [], set()
        for record in records:
            identity = record.get('id')
            if identity is not None and (identity in self.ids or identity in new):
                continue
            page.append(record)
            if identity is not None:
                new.add(identity)
        marker = {'kind': 'page', 'state': state, 'ids': [r.get('id') for r in page], 'n': len(page),
                  'stop_reason': stop_reason}
        if skipped:
            marker['skipped'] = list(skipped)
        if notes:
            marker['coverage'] = list(notes)
        try:
            for record in page:
                self.stream.write(_line(record))
            self.stream.write(_line(marker))
            self.stream.flush()
            os.fsync(self.stream.fileno())
        except OSError:
            raise FacebookError(6, 'A page could not be written to the --out file.', 'Free disk space, then rerun '
                                                                                     'the same command to resume.') from None
        self.ids |= new
        self.skipped |= set(skipped)
        self.count += len(page)
        self.parent_count += sum(1 for r in page if r.get('depth') == 0)
        self.state, self.complete = state, stop_reason in COMPLETE

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None
