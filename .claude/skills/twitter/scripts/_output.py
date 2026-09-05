"""Numbered private continuations and atomic page markers for NDJSON exports."""
import fcntl
import json
import os
from pathlib import Path
from ._blocked import cache_dir
from ._errors import TwitterError

COMPLETE = {'exhausted', 'window_reached', 'not_paginable', 'terminated'}


def line(value):
    return (json.dumps(value, ensure_ascii=False) + '\n').encode()


class CursorStore:
    def __init__(self):
        self.directory = cache_dir() / 'cursors'

    def save(self, context, state):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        number = 1
        while True:
            try:
                fd = os.open(self.directory / f'{number}.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError:
                number += 1
        with os.fdopen(fd, 'wb') as stream:
            stream.write(line(dict(state, context=context)))
            stream.flush()
            os.fsync(stream.fileno())
        return number

    def load(self, number, context):
        try:
            if not str(number).isdigit() or int(number) < 1:
                raise ValueError
            data = json.loads((self.directory / f'{int(number)}.json').read_text())
            if data.get('context') != context or not isinstance(data.get('pending'), list):
                raise ValueError
            return data
        except (OSError, ValueError, AttributeError):
            raise TwitterError(2, 'Continuation is missing or belongs to a different query/account.', 'Copy the complete more: command, or start a new query.') from None


class OutFile:
    def __init__(self, path, context):
        self.path, self.context = Path(path).expanduser(), context
        self.ids, self.count, self.state, self.complete = set(), 0, {}, False
        self.stream = None
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
            self.stream = os.fdopen(fd, 'r+b')
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.recover()
        except (OSError, ValueError, TwitterError) as error:
            self.close()
            if isinstance(error, TwitterError):
                raise
            raise TwitterError(2, 'Cannot open or lock the output file.', 'Choose a writable file not used by another process.') from None

    def recover(self):
        first = self.stream.readline()
        if not first:
            self.stream.write(line(dict(kind='header', **self.context)))
            self.stream.flush()
            os.fsync(self.stream.fileno())
            return
        if json.loads(first) != dict(kind='header', **self.context):
            raise TwitterError(2, 'Output belongs to a different query or viewer.', 'Use a new output file.')
        boundary, page = self.stream.tell(), []
        while raw := self.stream.readline():
            if not raw.endswith(b'\n'):
                break
            try:
                record = json.loads(raw)
            except ValueError:
                break
            if record.get('kind') == 'page' and 'id' not in record:
                if record.get('ids') != [r.get('id') for r in page] or record.get('n') != len(page):
                    raise TwitterError(2, 'Output page integrity check failed.', 'Preserve this file and use a new path.')
                self.ids.update(record['ids'])
                self.count += len(page)
                self.state = record['state']
                self.complete = record['stop_reason'] in COMPLETE
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


def emit(result, args):
    from ._render import render
    code = result.pop('code', 0)
    result.pop('state', None)
    result.setdefault('next', None)
    result.setdefault('warnings', [])
    result.setdefault('fetched_bytes', 0)
    result.setdefault('budget', {})
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(render(result, args))
    return code
