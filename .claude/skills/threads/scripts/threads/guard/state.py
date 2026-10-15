"""Where account protection state lives, the lock that serializes it, and atomic writes."""
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from ..errors import ThreadsError


def cache_dir():
    return Path(os.environ.get('THREADS_HOME', Path.home() / '.cache/threads-skill'))


@contextmanager
def account_lock():
    # 성진: A single Aside account shares this lock before its ID is known; split by browser account when multi-account support exists.
    root = cache_dir()
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = (root / 'account.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX)
    except OSError:
        raise ThreadsError(5, 'Account protection storage is unavailable.', 'Restore access to THREADS_HOME before retrying.') from None
    try:
        yield
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def write_state(name, value):
    """Atomic credential-free state; callers serialize read/modify/write with account_lock."""
    root = cache_dir()
    temporary = None
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(mode='w', dir=root, delete=False) as stream:
            temporary = stream.name
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / name)
    except OSError:
        raise ThreadsError(5, 'Account protection state could not be saved.', 'Restore access to THREADS_HOME before retrying.') from None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
