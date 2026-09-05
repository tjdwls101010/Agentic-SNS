"""Private cursor handles and crash-resumable, page-committed NDJSON output."""
import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ._errors import ThreadsError


def _line(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


class OutFile:
    """Trust only complete page markers; an interrupted tail is replayed."""
    def __init__(self, path, context):
        self.path, self.context = Path(path).expanduser(), dict(context)
        self.ids, self.count, self.cursor, self.pending, self.complete = set(), 0, None, [], False
        self.parent_count = 0
        self.stream = None
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            self.stream = os.fdopen(fd, 'r+b')
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._recover()
        except (OSError, ValueError, ThreadsError) as error:
            self.close()
            if isinstance(error, ThreadsError):
                raise
            raise ThreadsError(2, 'Cannot open or lock the output file.',
                                'Choose a writable file not used by another process.') from None

    def _recover(self):
        first = self.stream.readline()
        if not first:
            self.stream.write(_line(dict(self.context, kind='header',
                                         started_at=datetime.now(timezone.utc).isoformat(),
                                         limit_unit='records; unshown page tails are preserved in cursor state')))
            self.stream.flush()
            os.fsync(self.stream.fileno())
            return
        try:
            header = json.loads(first)
        except ValueError:
            raise ThreadsError(2, 'The output header is incomplete.', 'Use a new output file.') from None
        if (not isinstance(header, dict) or header.get('kind') != 'header'
                or {k: v for k, v in header.items() if k not in ('kind', 'started_at', 'limit_unit')} != self.context):
            raise ThreadsError(2, 'The output file belongs to a different query context.', 'Use a new output file.')
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
                    raise ThreadsError(2, 'Output page integrity check failed.', 'Preserve this file and use a new path.')
                self.ids.update(x for x in page_ids if x is not None)
                self.count += len(page)
                self.parent_count += sum('post_id' in record and not record.get('depth') for record in page)
                self.cursor = record.get('cursor')
                self.complete = record.get('stop_reason') in ('exhausted', 'window_reached') or self.cursor == {'exhausted': True}
                boundary, page = self.stream.tell(), []
            else:
                page.append(record)
        self.stream.seek(boundary)
        self.stream.truncate()

    def commit(self, records, cursor, stop_reason):
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
            self.stream.write(_line(dict(kind='page', cursor=cursor,
                                         ids=[r.get('id') for r in page], n=len(page), stop_reason=stop_reason)))
            self.stream.flush()
            os.fsync(self.stream.fileno())
        except OSError:
            raise ThreadsError(8, 'Output page could not be committed.',
                                'Free disk space and resume with the same command and file.') from None
        self.ids.update(new_ids)
        self.count += len(page)
        self.parent_count += sum('post_id' in record and not record.get('depth') for record in page)
        self.cursor = cursor
        self.complete = stop_reason in ('exhausted', 'window_reached') or cursor == {'exhausted': True}

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


class CursorStore:
    """Opaque monotonically increasing handles bind cursors to one query context."""
    def __init__(self):
        from ._blocked import cache_dir
        self.directory = cache_dir() / 'cursors'
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def save(self, context, cursor, pending=None):
        try:
            fd = os.open(self.directory / 'counter', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'r+b') as counter:
                fcntl.flock(counter, fcntl.LOCK_EX)
                number = int(counter.read() or b'0') + 1
                # Persist the reservation first: an interrupted save leaves a gap, never a reused handle.
                counter.seek(0)
                counter.write(str(number).encode())
                counter.truncate()
                counter.flush()
                os.fsync(counter.fileno())
                path = self.directory / f'{number}.json'
                with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
                    stream.write(_line(dict(context=context, cursor=cursor, pending=pending or [],
                                            created_at=datetime.now(timezone.utc).isoformat())))
                    stream.flush()
                    os.fsync(stream.fileno())
                return number
        except (OSError, ValueError):
            raise ThreadsError(8, 'Cannot save a continuation handle.', 'Check the Threads cache directory.') from None

    def load(self, number, context):
        if not str(number).isdigit() or int(number) < 1:
            raise ThreadsError(2, 'Continuation handles are positive numbers.', 'Copy the full more: command.')
        try:
            data = json.loads((self.directory / f'{int(number)}.json').read_text())
        except (OSError, ValueError):
            raise ThreadsError(2, 'Continuation handle is missing or incomplete.', 'Restart the original query.') from None
        if not isinstance(data, dict) or data.get('context') != context:
            raise ThreadsError(2, 'Continuation context does not match this query.', 'Copy the full more: command.')
        if not isinstance(data.get('cursor'), dict) or not isinstance(data.get('pending'), list):
            raise ThreadsError(2, 'Continuation handle is incomplete.', 'Restart the original query.')
        state = data['cursor']
        if (not isinstance(state.get('pending', []), list) or
                any(not isinstance(item, dict) for item in state.get('pending', [])) or
                not isinstance(state.get('seen', []), list) or
                any(not isinstance(item, str) for item in state.get('seen', [])) or
                type(state.get('done', False)) is not bool or
                state.get('after') is not None and not isinstance(state['after'], str)):
            raise ThreadsError(2, 'Continuation progress is malformed.', 'Restart the original query.')
        return data
