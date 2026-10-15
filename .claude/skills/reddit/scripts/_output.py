"""Private cursor handles and crash-resumable, page-committed NDJSON output."""
import fcntl
import json
import os
import stat
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from ._errors import RedditError


def _line(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode()


class OutFile:
    """Trust only complete page markers; an interrupted tail is replayed."""
    def __init__(self, path, context):
        self.path, self.context = Path(path).expanduser(), dict(context)
        self.ids, self.count, self.cursor, self.pending, self.complete = set(), 0, None, [], False
        self.state = None
        self.parent_count = 0
        self.stream = None
        try:
            fd = _open(self.path, os.O_RDWR | os.O_CREAT)
            self.stream = os.fdopen(fd, 'r+b')
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._recover()
        except (OSError, ValueError, RedditError) as error:
            self.close()
            if isinstance(error, RedditError):
                raise
            raise RedditError(2, 'Cannot open or lock the output file.',
                                'Choose a writable file not used by another process.') from None

    def _recover(self):
        first = self.stream.readline()
        if not first:
            self.stream.write(_line(dict(self.context, kind='header',
                                         started_at=datetime.now(timezone.utc).isoformat(),
                                         limit_unit='page; may exceed the requested count by the remainder of one page')))
            self.stream.flush()
            os.fsync(self.stream.fileno())
            return
        try:
            if not first.endswith(b'\n'):
                raise ValueError
            header = json.loads(first)
        except ValueError:
            raise RedditError(2, 'The output header is incomplete.', 'Use a new output file.') from None
        if (not isinstance(header, dict) or header.get('kind') != 'header'
                or {k: v for k, v in header.items() if k not in ('kind', 'started_at', 'limit_unit')} != self.context):
            raise RedditError(2, 'The output file belongs to a different query context.', 'Use a new output file.')
        boundary, page = self.stream.tell(), []
        while line := self.stream.readline():
            if not line.endswith(b'\n'):
                break
            try:
                record = json.loads(line)
            except ValueError:
                raise RedditError(2, 'Output contains a corrupt complete line.', 'Preserve this file and use a new path.') from None
            if not isinstance(record, dict):
                raise RedditError(2, 'Output contains an invalid record.')
            if record.get('kind') == 'page' and 'fullname' not in record:
                page_ids = [r.get('fullname') for r in page]
                if (record.get('ids') != page_ids or record.get('n') != len(page)
                        or len(set(page_ids)) != len(page_ids) or self.ids.intersection(page_ids)
                        or not {'state', 'cursor', 'stop_reason'} <= record.keys()):
                    raise RedditError(2, 'Output page integrity check failed.', 'Preserve this file and use a new path.')
                _state(record['state'], self.context)
                self.ids.update(page_ids)
                self.count += len(page)
                self.parent_count += sum(record.get('kind') == 'comment' and not record.get('depth') for record in page)
                self.cursor = record.get('cursor')
                self.state = record.get('state')
                self.pending = (self.state or {}).get('pending', [])
                self.complete = record.get('stop_reason') in ('exhausted', 'window_reached') or self.cursor == {'exhausted': True}
                boundary, page = self.stream.tell(), []
            else:
                _record(record)
                page.append(record)
        self.stream.seek(boundary)
        self.stream.truncate()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def commit(self, records, cursor, stop_reason, *, state=None):
        _state(state, self.context)
        records = list(records)
        for record in records:
            _record(record)
        page, new_ids = [], set()
        for record in records:
            identity = record.get('fullname')
            if identity is not None and (identity in self.ids or identity in new_ids):
                continue
            page.append(record)
            if identity is not None:
                new_ids.add(identity)
        marker = dict(kind='page', cursor=cursor, state=state,
                      ids=[r.get('fullname') for r in page], n=len(page), stop_reason=stop_reason)
        try:
            encoded = b''.join(_line(record) for record in page) + _line(marker)
        except (ValueError, TypeError):
            raise RedditError(2, 'Output progress must be JSON serializable.') from None
        try:
            self.stream.write(encoded)
            self.stream.flush()
            os.fsync(self.stream.fileno())
        except OSError:
            raise RedditError(8, 'Output page could not be committed.',
                                'Free disk space and resume with the same command and file.') from None
        self.ids.update(new_ids)
        self.count += len(page)
        self.parent_count += sum(record.get('kind') == 'comment' and not record.get('depth') for record in page)
        self.cursor = deepcopy(cursor)
        self.state = deepcopy(state)
        self.pending = (self.state or {}).get('pending', [])
        self.complete = stop_reason in ('exhausted', 'window_reached') or cursor == {'exhausted': True}

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


def _record(record):
    if (not isinstance(record, dict) or not isinstance(record.get('fullname'), str)
            or not record['fullname'] or record.get('kind') not in ('post', 'comment', 'subreddit', 'user')):
        raise RedditError(2, 'Output records must be fullname-keyed model objects.')
    _flat(record)


def _state(state, context):
    if state is not None:
        if not isinstance(state, dict):
            raise RedditError(2, 'Progress state must be an object.')
        if 'account' in state and state['account'] != context.get('account'):
            raise RedditError(2, 'Progress state belongs to a different account.')
        _flat(state)


def _flat(value):
    if isinstance(value, dict):
        if value.get('replies'):
            raise RedditError(2, 'Persist flat thread records, not nested replies.')
        for child in value.values():
            _flat(child)
    elif isinstance(value, list):
        for child in value:
            _flat(child)


def _safe(path):
    path = Path(os.path.abspath(Path(path).expanduser()))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise RedditError(2, 'Symbolic links are not allowed for private output/cache paths.')
    return path


def _open(path, flags):
    path = _safe(path)
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(path.name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
    finally:
        os.close(directory)
    if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
        os.close(fd)
        raise RedditError(2, 'Private output/cache paths must be regular, unshared files.')
    os.fchmod(fd, 0o600)
    return fd


def _root():
    return Path(os.environ.get('REDDIT_HOME', '~/.cache/reddit-skill')).expanduser()


def cleanup_cache(directory=None, *, now=None, ttl=86400, max_bytes=209715200):
    """Shared TTL/size policy for thread and cursor JSON, never coordination files."""
    root = _safe(directory or _root())
    if not root.exists():
        return 0
    try:
        with os.fdopen(_open(root / 'threads.lock', os.O_RDWR | os.O_CREAT), 'r+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return _cleanup(root, time.time() if now is None else now, ttl, max_bytes)
    except OSError:
        raise RedditError(8, 'Cache cleanup is busy or unavailable.',
                          'Save continuation handles after the thread transaction closes.') from None


def _cleanup(root, now, ttl, max_bytes):
    entries = []
    for name in ('cursors', 'threads'):
        folder = _safe(root / name)
        if not folder.exists():
            continue
        for path in folder.glob('*.json'):
            _safe(path)
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                continue
            if now - info.st_mtime >= ttl:
                path.unlink()
            else:
                entries.append((info.st_mtime, path, info.st_size))
    total = sum(size for _, _, size in entries)
    for _, path, size in sorted(entries):
        if total <= max_bytes:
            break
        path.unlink()
        total -= size
    return total


class CursorStore:
    """Standalone Facebook cursor-store design with Reddit context and cache policy."""
    def __init__(self, directory=None):
        self.directory = _safe(directory or _root() / 'cursors')
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.directory.chmod(0o700)
            self.directory.parent.chmod(0o700)
        except OSError:
            raise RedditError(8, 'Cannot create the private cursor directory.') from None

    def save(self, context, cursor, pending=None):
        if pending is not None and not isinstance(pending, list):
            raise RedditError(2, 'Pending continuation records must be an array.')
        self._paths(cursor)
        try:
            cleanup_cache(self.directory.parent)
            with os.fdopen(_open(self.directory / 'counter', os.O_RDWR | os.O_CREAT), 'r+b') as counter:
                fcntl.flock(counter, fcntl.LOCK_EX)
                number = int(counter.read() or b'0') + 1
                if number < 1:
                    raise ValueError
                counter.seek(0)
                counter.write(str(number).encode())
                counter.truncate()
                counter.flush()
                os.fsync(counter.fileno())
                path = self.directory / f'{number}.json'
                with os.fdopen(_open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL), 'wb') as stream:
                    stream.write(_line(dict(context=context, cursor=cursor, pending=pending or [],
                                            created_at=datetime.now(timezone.utc).isoformat())))
                    stream.flush()
                    os.fsync(stream.fileno())
                cleanup_cache(self.directory.parent)
                if not path.exists():
                    raise RedditError(8, 'Continuation exceeds the cache capacity.')
                return number
        except (OSError, ValueError, TypeError):
            raise RedditError(8, 'Cannot save a continuation handle.', 'Check the Reddit cache directory.') from None

    def _paths(self, value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('path', 'thread_path'):
                    if not isinstance(child, str):
                        raise RedditError(2, 'Invalid cached thread path.')
                    path = Path(child)
                    root = _safe(self.directory.parent / 'threads')
                    path = _safe(path if path.is_absolute() else root / path)
                    if path.parent != root or path.suffix != '.json':
                        raise RedditError(2, 'Cached thread path escapes the thread directory.')
                else:
                    self._paths(child)
        elif isinstance(value, list):
            for child in value:
                self._paths(child)

    def load(self, number, context):
        if not str(number).isascii() or not str(number).isdigit() or int(number) < 1:
            raise RedditError(2, 'Continuation handles are positive numbers.', 'Copy the full more: command.')
        try:
            with os.fdopen(_open(self.directory / f'{int(number)}.json', os.O_RDONLY), 'rb') as stream:
                data = json.load(stream)
            if not isinstance(data, dict) or data.get('context') != context:
                raise RedditError(2, 'Continuation context does not match this query.')
            if 'cursor' not in data or not isinstance(data.get('pending'), list):
                raise ValueError
            created = datetime.fromisoformat(data['created_at']).timestamp()
            if time.time() - created >= 86400:
                raise RedditError(2, 'Continuation handle has expired.', 'Restart the original query.')
            self._paths(data['cursor'])
            return data
        except (OSError, ValueError, TypeError, KeyError):
            raise RedditError(2, 'Continuation handle is missing or incomplete.', 'Restart the original query.') from None
