"""Private atomic state and a cross-process lock for the one Aside account."""
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from ._errors import TwitterError


def cache_dir():
    return Path(os.environ.get('TWITTER_HOME', Path.home() / '.cache/twitter-skill'))


@contextmanager
def account_lock():
    # 성진: One Aside account shares this lock; split it when multi-account support exists.
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / 'account.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def read_state(name, default=None):
    try:
        return json.loads((cache_dir() / name).read_text())
    except FileNotFoundError:
        return {} if default is None else default
    except (OSError, ValueError):
        raise TwitterError(5, 'Cache state is unreadable.', 'Inspect TWITTER_HOME; preserve collected output before starting fresh.') from None


def write_state(name, value):
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=root, delete=False) as stream:
            temporary = stream.name
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / name)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def set_blocked(reason):
    if reason not in ('challenge', 'account_locked'):
        raise ValueError('Only human-clearable blocks belong here')
    state = read_state('budget.json')
    if not state.get('block'):
        state['block'] = dict(reason=reason, expires_at=None)
        write_state('budget.json', state)


def unblock():
    with account_lock():
        state = read_state('budget.json')
        state.pop('block', None)
        write_state('budget.json', state)
