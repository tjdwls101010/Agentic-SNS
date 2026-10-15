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


def _scan(data):
    """What a file's bytes hold: its header, the committed pages, and where the trusted part ends.

    Only a tail after the last page marker may be incomplete; a line that does not parse before a later marker means
    a committed page was damaged, which is an integrity failure.
    """
    lines = data.split(b'\n')
    try:
        header = json.loads(lines[0])
    except ValueError:
        header = None
    result = {'header': header, 'ids': set(), 'skipped': set(), 'count': 0, 'parents': 0, 'state': None,
              'complete': False, 'boundary': len(lines[0]) + 1}
    offset, page, broken = len(lines[0]) + 1, [], False
    complete_lines = lines[1:-1]  # the last element follows the final newline: empty, or a partial line
    for raw in complete_lines:
        offset += len(raw) + 1
        try:
            record = json.loads(raw)
            if not isinstance(record, dict):
                raise ValueError
        except ValueError:
            broken = True
            continue
        if record.get('kind') == 'page' and 'id' not in record:
            page_ids = [r.get('id') for r in page]
            if broken or record.get('ids') != page_ids or record.get('n') != len(page):
                raise FacebookError(2, 'The --out file failed its integrity check: a page line does not match the '
                                       'records above it.', 'Keep this file as it is and use a new path.')
            result['ids'].update(i for i in page_ids if i is not None)
            result['skipped'].update(record.get('skipped') or [])
            result['count'] += len(page)
            result['parents'] += sum(1 for r in page if r.get('depth') == 0)
            result['state'] = record.get('state')
            result['complete'] = record.get('stop_reason') in COMPLETE
            result['boundary'], page = offset, []
        elif not broken:
            page.append(record)
    return result


def _check_header(header, context):
    if not isinstance(header, dict) or header.get('kind') != 'header':
        raise FacebookError(2, 'The --out file is not a collection written by this skill.', 'Use a new --out path.')
    if header.get('format') != FORMAT:
        raise FacebookError(2, 'The --out file was written by an earlier version of this skill.',
                            'Use a new --out path; the old file is left as it was.')
    if context is not None and header.get('context') != context:
        raise FacebookError(2, 'The --out file belongs to another command, target, order or account.',
                            'Use a new --out path, or rerun the command that started this file.')


def peek(path):
    """(the query context a file was written for, whether it is complete, records saved), reading only; (None, False,
    0) when the file does not exist or is empty. A file that is not a current collection raises like opening it."""
    try:
        data = Path(path).expanduser().read_bytes()
    except FileNotFoundError:
        return None, False, 0
    except OSError:
        raise FacebookError(2, 'Cannot read the --out file.', 'Choose a readable path.') from None
    if not data:
        return None, False, 0
    scan = _scan(data)
    _check_header(scan['header'], None)
    return scan['header']['context'], scan['complete'], scan['count']


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
        data = self.stream.read()
        if not data:
            self.stream.write(_line({'kind': 'header', 'format': FORMAT, 'context': self.context,
                                     'started_at': datetime.now(timezone.utc).isoformat()}))
            self.stream.flush()
            os.fsync(self.stream.fileno())
            return
        scan = _scan(data)
        _check_header(scan['header'], self.context)
        self.ids, self.skipped, self.count = scan['ids'], scan['skipped'], scan['count']
        self.parent_count, self.state, self.complete = scan['parents'], scan['state'], scan['complete']
        self.stream.seek(scan['boundary'])
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
