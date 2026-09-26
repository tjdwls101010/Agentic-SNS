"""Crash-resumable, page-committed NDJSON output for one query context."""
import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from facebook.errors import FacebookError

# Bumped whenever a saved page or header changes meaning; older files are refused before any byte is touched.
FORMAT = 2


def _line(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


class OutFile:
    """Trust only complete page markers; an interrupted tail is replayed."""
    def __init__(self, path, context):
        self.path, self.context = Path(path).expanduser(), dict(context)
        self.ids, self.count, self.cursor, self.pending, self.complete = set(), 0, None, [], False
        self.skipped = set()  # sponsored ids left out of saved pages, so a resume does not count them again
        self.parent_count = 0
        self.stream = None
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            self.stream = os.fdopen(fd, 'r+b')
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._recover()
        except (OSError, ValueError, FacebookError) as error:
            self.close()
            if isinstance(error, FacebookError):
                raise
            raise FacebookError(2, 'Cannot open or lock the output file.',
                                'Choose a writable file not used by another process.') from None

    def _recover(self):
        first = self.stream.readline()
        if not first:
            self.stream.write(_line(dict(self.context, kind='header', format=FORMAT,
                                         started_at=datetime.now(timezone.utc).isoformat(),
                                         limit_unit='page; may exceed the requested count by the remainder of one page')))
            self.stream.flush()
            os.fsync(self.stream.fileno())
            return
        try:
            header = json.loads(first)
        except ValueError:
            raise FacebookError(2, 'The output header is incomplete.', 'Use a new output file.') from None
        if isinstance(header, dict) and header.get('kind') == 'header' and header.get('format') != FORMAT:
            raise FacebookError(2, 'The output file was written by an earlier version of this skill.', 'Restart the original query with a new --out path; this file was written by an earlier version.')
        if (not isinstance(header, dict) or header.get('kind') != 'header'
                or {k: v for k, v in header.items() if k not in ('kind', 'format', 'started_at', 'limit_unit')}
                != self.context):
            raise FacebookError(2, 'The output file belongs to a different query context.', 'Use a new output file.')
        boundary, page = self.stream.tell(), []
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
                    raise FacebookError(2, 'Output page integrity check failed.', 'Preserve this file and use a new path.')
                self.ids.update(x for x in page_ids if x is not None)
                self.skipped.update(record.get('skipped') or [])
                self.count += len(page)
                self.parent_count += sum('post_id' in record and not record.get('depth') for record in page)
                self.cursor = record.get('cursor')
                self.complete = record.get('stop_reason') in ('exhausted', 'window_reached') or self.cursor == {'exhausted': True}
                boundary, page = self.stream.tell(), []
            else:
                page.append(record)
        self.stream.seek(boundary)
        self.stream.truncate()

    def commit(self, records, cursor, stop_reason, skipped=()):
        page, new_ids = [], set()
        for record in records:
            identity = record.get('id')
            if identity is not None and (identity in self.ids or identity in new_ids):
                continue
            page.append(record)
            if identity is not None:
                new_ids.add(identity)
        try:
            for record in page:
                self.stream.write(_line(record))
            marker = dict(kind='page', cursor=cursor, ids=[r.get('id') for r in page], n=len(page),
                          stop_reason=stop_reason)
            if skipped:
                marker['skipped'] = list(skipped)
            self.stream.write(_line(marker))
            self.stream.flush()
            os.fsync(self.stream.fileno())
        except OSError:
            raise FacebookError(6, 'Output page could not be committed.',
                                'Free disk space and resume with the same command and file.') from None
        self.ids.update(new_ids)
        self.skipped.update(skipped)
        self.count += len(page)
        self.parent_count += sum('post_id' in record and not record.get('depth') for record in page)
        self.cursor = cursor
        self.complete = stop_reason in ('exhausted', 'window_reached') or cursor == {'exhausted': True}

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None
