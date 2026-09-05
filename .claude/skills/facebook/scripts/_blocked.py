"""Persistent protection shared by every CLI using the Aside account."""
import fcntl
import json
import math
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from _errors import FacebookError


def cache_dir():
    return Path(os.environ.get('FACEBOOK_HOME', Path.home() / '.cache/facebook-skill'))


@contextmanager
def account_lock():
    # 성진: A single Aside account shares this lock before its ID is known; split by browser account when multi-account support exists.
    root = cache_dir()
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = (root / 'account.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX)
    except OSError:
        raise FacebookError(5, 'Account protection storage is unavailable.', 'Restore access to FACEBOOK_HOME before retrying.') from None
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
        raise FacebookError(5, 'Account protection state could not be saved.', 'Restore access to FACEBOOK_HOME before retrying.') from None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def check_blocked():
    path = cache_dir() / 'blocked.json'
    try:
        record = json.loads(path.read_text())
        reason = record['reason']
        expiry = record['expires_at']
        if reason not in ('checkpoint', 'rate_limit'):
            raise ValueError
        if reason == 'rate_limit':
            if type(expiry) not in (int, float) or not math.isfinite(expiry):
                raise ValueError
            if expiry <= time.time():
                return None
        elif expiry is not None:
            raise ValueError
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, KeyError):
        raise FacebookError(5, 'Account protection state is unreadable.', 'Check Facebook in Aside, then run doctor --unblock.') from None
    raise FacebookError(5, 'Facebook requests are blocked for this account.', 'Stop requests. Check Facebook in Aside, then run doctor --unblock.')


def set_blocked(reason):
    if reason not in ('checkpoint', 'rate_limit'):
        raise ValueError('Unknown block reason')
    now = time.time()
    write_state('blocked.json', {'reason': reason, 'blocked_at': now,
                                'expires_at': None if reason == 'checkpoint' else now + 1800})


def unblock():
    with account_lock():
        try:
            (cache_dir() / 'blocked.json').unlink(missing_ok=True)
        except OSError:
            raise FacebookError(5, 'Account block could not be cleared.', 'Restore access to FACEBOOK_HOME.') from None
