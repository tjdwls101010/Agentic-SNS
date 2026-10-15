"""Numbered continuation handles, each bound to one query context."""
import fcntl
import json
import os
from datetime import datetime, timezone

from facebook.account import cache_dir
from facebook.errors import FacebookError

FORMAT = 2


def _line(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


class CursorStore:
    """Opaque monotonically increasing handles bind cursors to one query context."""
    def __init__(self):
        self.directory = cache_dir() / 'cursors'
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError:
            raise FacebookError(6, 'Cannot save a continuation handle.', 'Check that the Facebook cache directory '
                                                                          'is writable, then rerun the command.') from None

    def save(self, context, cursor, pending=None):
        try:
            fd = os.open(self.directory / 'counter', os.O_RDWR | os.O_CREAT, 0o600)
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
                    stream.write(_line(dict(format=FORMAT, context=context, cursor=cursor, pending=pending or [],
                                            created_at=datetime.now(timezone.utc).isoformat())))
                    stream.flush()
                    os.fsync(stream.fileno())
                return number
        except (OSError, ValueError):
            raise FacebookError(6, 'Cannot save a continuation handle.', 'Check that the Facebook cache directory '
                                                                          'is writable, then rerun the command.') from None

    def load(self, number, context):
        if not str(number).isdigit() or int(number) < 1:
            raise FacebookError(2, 'Continuation handles are positive numbers.', 'Copy the full more: command.')
        try:
            data = json.loads((self.directory / f'{int(number)}.json').read_text())
        except (OSError, ValueError):
            raise FacebookError(2, 'Continuation handle is missing or incomplete.', 'Restart the original query.') from None
        if isinstance(data, dict) and data.get('format') != FORMAT:
            raise FacebookError(2, 'This continuation handle was created by an earlier version of this skill.',
                                'Restart the original query without --after.')
        if not isinstance(data, dict) or data.get('context') != context:
            raise FacebookError(2, 'Continuation context does not match this query.', 'Copy the full more: command.')
        if 'cursor' not in data or not isinstance(data.get('pending'), list):
            raise FacebookError(2, 'Continuation handle is incomplete.', 'Restart the original query.')
        return data
