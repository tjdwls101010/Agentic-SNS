"""Private continuation handles: random names, bound to their query and viewer, valid for a day after issue."""
import json
import math
import os
import re
import secrets
import string
import time
from .account.state import cache_dir
from .errors import TwitterError

FORMAT = 2
LIFETIME = 86400
HANDLE = re.compile(r'[a-z0-9]{6}')
ALPHABET = string.ascii_lowercase + string.digits


def valid(handle):
    return bool(HANDLE.fullmatch(handle or ''))


class CursorStore:
    def __init__(self):
        self.directory = cache_dir() / 'cursors'

    def save(self, context, state):
        """Store the state under a new handle, redrawing on a collision, and sweep expired handles first."""
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.sweep()
        while True:
            handle = ''.join(secrets.choice(ALPHABET) for _ in range(6))
            try:
                fd = os.open(self.directory / f'{handle}.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError:
                continue
        with os.fdopen(fd, 'wb') as stream:
            stream.write((json.dumps(dict(state, format=FORMAT, created_at=time.time(), context=context), ensure_ascii=False) + '\n').encode())
            stream.flush()
            os.fsync(stream.fileno())
        return handle

    def load(self, handle, context):
        """The state behind a handle; a handle of another query or viewer, an older format or an expired one is refused."""
        if not valid(handle):
            raise TwitterError(2, 'Continuation handles are six lowercase letters or digits.', 'Copy --after from the latest more: line.')
        try:
            data = json.loads((self.directory / f'{handle}.json').read_text())
            if not isinstance(data, dict):
                raise ValueError
        except (OSError, ValueError):
            raise TwitterError(2, 'Continuation is missing or belongs to a different query/account.', 'Copy --after from the latest more: line, or rerun without --after.') from None
        if data.get('format') != FORMAT:
            raise TwitterError(2, 'This continuation was written by an older version of the skill.', 'Rerun the command without --after.')
        created = data.get('created_at')
        if not isinstance(created, (int, float)) or isinstance(created, bool) or not math.isfinite(created):
            raise TwitterError(2, 'Continuation is missing or belongs to a different query/account.', 'Copy --after from the latest more: line, or rerun without --after.')
        if time.time() - created > LIFETIME:
            raise TwitterError(2, 'This continuation expired 24 hours after it was issued.', 'Rerun the command without --after.')
        if data.get('context') != context or not isinstance(data.get('pending'), list):
            raise TwitterError(2, 'Continuation is missing or belongs to a different query/account.', 'Copy --after from the latest more: line, or rerun without --after.')
        return data

    def sweep(self):
        """Delete handles past their lifetime, counted from the issue time they record (the file time when they record none); return how many remain."""
        remaining = 0
        for path in self.directory.glob('*.json') if self.directory.is_dir() else ():
            try:
                try:
                    created = json.loads(path.read_text()).get('created_at')
                except (ValueError, AttributeError):
                    created = None
                if not isinstance(created, (int, float)) or isinstance(created, bool) or not math.isfinite(created):
                    created = path.stat().st_mtime
                if time.time() - created > LIFETIME:
                    path.unlink()
                else:
                    remaining += 1
            except OSError:
                continue
        return remaining
