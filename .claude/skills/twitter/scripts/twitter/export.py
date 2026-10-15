"""Private NDJSON exports committed a whole page at a time, with a query header and tail recovery."""
import fcntl
import json
import os
import shlex
from pathlib import Path
from .account.state import cache_dir
from .errors import TwitterError

COMPLETE = {'exhausted', 'window_reached', 'not_paginable', 'terminated'}
FORMAT = 2


def line(value):
    return (json.dumps(value, ensure_ascii=False) + '\n').encode()


def check(path):
    """Before any request: refuse an export inside the skill's cache, or an existing one other users can read (left as it is)."""
    existing = Path(path).expanduser()
    caches = {cache_dir().expanduser().absolute(), cache_dir().expanduser().resolve()}
    if any(place == cache or cache in place.parents for place in (existing.absolute(), existing.resolve()) for cache in caches):
        raise TwitterError(2, 'The --out file would sit inside the skill\'s cache and be overwritten by it.', 'Pass --out a path outside ' + str(cache_dir()) + '.')
    if existing.exists() and existing.stat().st_mode & 0o077:
        raise readable(path)


def readable(path):
    return TwitterError(2, 'The --out file can be read by other users.',
                        f'Run chmod 600 {shlex.quote(str(Path(path).expanduser().absolute()))}, or pass a new --out path.')


class OutFile:
    def __init__(self, path, context):
        self.path, self.context = Path(path).expanduser(), context
        self.ids, self.count, self.state, self.complete = set(), 0, {}, False
        self.stream = None
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            self.stream = os.fdopen(fd, 'r+b')
            if os.fstat(fd).st_mode & 0o077:
                raise readable(path)
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.recover()
        except (OSError, ValueError, TwitterError) as error:
            self.close()
            if isinstance(error, TwitterError):
                raise
            raise TwitterError(2, 'Cannot open or lock the output file.', 'Pass --out a writable path that no other run is using.') from None

    def recover(self):
        first = self.stream.readline()
        if not first:
            self.stream.write(line(dict(kind='header', format=FORMAT, **self.context)))
            self.stream.flush()
            os.fsync(self.stream.fileno())
            return
        header = json.loads(first)
        if not isinstance(header, dict) or header.get('format') != FORMAT:
            raise TwitterError(2, 'This --out file was written by an older version of the skill and cannot be resumed.',
                               'Pass a new --out path; the old file stays as it was.')
        if header != dict(kind='header', format=FORMAT, **self.context):
            raise TwitterError(2, 'Output belongs to a different query or viewer.', 'Pass a new --out path; this file holds a different query or account.')
        boundary, page = self.stream.tell(), []
        damaged = TwitterError(2, 'Output page integrity check failed.', 'Keep this file and pass a new --out path.')
        while raw := self.stream.readline():
            if not raw.endswith(b'\n'):
                break
            try:
                record = json.loads(raw)
                if not isinstance(record, dict):
                    raise ValueError
            except ValueError:
                if self.stream.read(1):
                    raise damaged from None
                break
            if record.get('kind') == 'page' and 'id' not in record:
                try:
                    if (record['ids'] != [r.get('id') for r in page] or record['n'] != len(page) or not isinstance(record['state'], dict)
                            or not all(isinstance(identity, str) for identity in record['ids'])):
                        raise ValueError
                    self.complete = record['stop_reason'] in COMPLETE
                except (KeyError, TypeError, ValueError):
                    raise damaged from None
                self.ids.update(record['ids'])
                self.count += len(page)
                self.state = record['state']
                boundary, page = self.stream.tell(), []
            else:
                page.append(record)
        self.stream.seek(boundary)
        self.stream.truncate()

    def commit(self, records, state, stop_reason):
        page = []
        for record in records:
            if record.get('id') not in self.ids:
                page.append(record)
                self.ids.add(record.get('id'))
        try:
            for record in page:
                self.stream.write(line(record))
            completeness = {key: state.get('metadata', {})[key] for key in ('reported', 'direct_shown', 'nested_shown', 'hidden_branches') if key in state.get('metadata', {})}
            self.stream.write(line(dict(kind='page', ids=[r.get('id') for r in page], n=len(page), state=state, stop_reason=stop_reason, **completeness)))
            self.stream.flush()
            os.fsync(self.stream.fileno())
        except OSError:
            raise TwitterError(8, 'Output page could not be committed.', 'Free disk space and resume with the same file.') from None
        self.count += len(page)
        self.state, self.complete = state, stop_reason in COMPLETE

    def close(self):
        if self.stream:
            self.stream.close()
            self.stream = None
