"""Every HTTP hop reserves a shared slot before it can leave the process.

Naver never says how much is left, so the whole allowance is local: a slot is written to
disk before the request goes out, which is why a process killed mid-flight still spends it.
"""
import fcntl
import json
import math
import os
import random
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from ._errors import NaverBlogError

# 성진: 0.5s and 120/10min are local estimates from 360 anonymous and ~100 logged-in requests
# without incident, not an allowance Naver granted; lower them if a 429 or an auth page appears.
WINDOW, WINDOW_LIMIT, MIN_GAP, JITTER = 600, 120, 0.5, 0.3


def cache_dir():
    return Path(os.environ.get('NAVER_BLOG_HOME', Path.home() / '.cache/naver-blog-skill'))


@contextmanager
def account_lock():
    # 성진: One Aside account shares this lock before its Naver id is known; split by account when multi-account exists.
    root = cache_dir()
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock = (root / 'account.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX)
    except OSError:
        raise NaverBlogError(5, 'Account protection storage is unavailable.',
                             'Restore access to NAVER_BLOG_HOME before retrying.') from None
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
        raise NaverBlogError(5, 'Account protection state could not be saved.',
                             'Restore access to NAVER_BLOG_HOME before retrying.') from None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def check_blocked():
    """rate_limit is the only block: HTTP 429 is the one signal Naver has ever been seen to send."""
    path = cache_dir() / 'blocked.json'
    try:
        record = json.loads(path.read_text())
        if record['reason'] != 'rate_limit':
            raise ValueError
        expiry = record['expires_at']
        if type(expiry) not in (int, float) or not math.isfinite(expiry):
            raise ValueError
        if expiry <= time.time():
            return None
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, KeyError):
        raise NaverBlogError(5, 'Account protection state is unreadable.',
                             'Check Naver Blog in Aside, then run doctor --unblock.') from None
    raise NaverBlogError(5, 'Naver Blog requests are blocked for this account.',
                         f'No retry before {expiry:.0f} (Unix time); this block expires on its own.',
                         error='rate_limit')


def set_blocked(reason='rate_limit'):
    if reason != 'rate_limit':
        raise ValueError('Unknown block reason')
    now = time.time()
    write_state('blocked.json', {'reason': reason, 'blocked_at': now, 'expires_at': now + 1800})


def clear_blocked():
    try:
        (cache_dir() / 'blocked.json').unlink(missing_ok=True)
    except OSError:
        raise NaverBlogError(5, 'Account block could not be cleared.',
                             'Restore access to NAVER_BLOG_HOME.') from None


def history():
    try:
        values = json.loads((cache_dir() / 'budget.json').read_text())['requests']
        if not isinstance(values, list) or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError
        return [v for v in values if v > time.time() - WINDOW]
    except FileNotFoundError:
        return []
    except (ValueError, KeyError, TypeError, OSError):
        raise NaverBlogError(5, 'Local request history is unreadable.',
                             'Restore NAVER_BLOG_HOME before making requests.') from None


class Budget:
    def __init__(self, max_requests=10):
        self.maximum = min(60, max_requests)
        self.used = 0

    @contextmanager
    def request(self, *, unblock=False):
        with account_lock():
            if not unblock:
                check_blocked()
            if self.used >= self.maximum:
                raise NaverBlogError(8, 'This command reached its local request cap.',
                                     'Continue with --after later; --limit controls results, not requests.',
                                     error='budget')
            times = history()
            if len(times) >= WINDOW_LIMIT:
                raise NaverBlogError(5, 'The local 10-minute request window is full.',
                                     f'No retry before {min(times) + WINDOW:.0f} (Unix time).', error='rate_limit')
            if times and not os.environ.get('NAVER_BLOG_NO_PACING'):
                time.sleep(max(0, max(times) + MIN_GAP + random.uniform(0, JITTER) - time.time()))
            # Reserve before sending: a process killed in flight must not leave a free slot behind.
            times = history()
            times.append(time.time())
            write_state('budget.json', {'requests': times})
            self.used += 1
            yield

    def snapshot(self):
        with account_lock():
            return {'kind': 'local', 'used': self.used, 'limit': self.maximum,
                    'remaining': max(0, self.maximum - self.used), 'window_used': len(history()),
                    'window_limit': WINDOW_LIMIT, 'window_seconds': WINDOW}
