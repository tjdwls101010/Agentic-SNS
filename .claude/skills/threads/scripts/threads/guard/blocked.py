"""Persistent blocks shared by every CLI using the Aside account: a checkpoint until unblocked, a rate limit for 30 minutes."""
import json
import math
import time

from ..errors import ThreadsError
from .state import account_lock, cache_dir, write_state


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
        raise ThreadsError(5, 'Account protection state is unreadable.', 'Check Threads in Aside, then run doctor --unblock.') from None
    raise ThreadsError(5, 'Threads requests are blocked for this account.',
                       'Check Threads in Aside, then run doctor --unblock.' if reason == 'checkpoint'
                       else f'No retry before {expiry:.0f} (Unix time); the rate-limit block expires automatically.', error=reason)


def set_blocked(reason):
    if reason not in ('checkpoint', 'rate_limit'):
        raise ValueError('Unknown block reason')
    try:
        existing = json.loads((cache_dir() / 'blocked.json').read_text())
        if existing.get('reason') == 'checkpoint' and reason != 'checkpoint':
            return
    except FileNotFoundError:
        pass
    except (ValueError, OSError, AttributeError):
        raise ThreadsError(5, 'Account block state is unreadable.') from None
    now = time.time()
    write_state('blocked.json', {'reason': reason, 'blocked_at': now,
                                'expires_at': None if reason == 'checkpoint' else now + 1800})


def unblock():
    with account_lock():
        try:
            (cache_dir() / 'blocked.json').unlink(missing_ok=True)
        except OSError:
            raise ThreadsError(5, 'Account block could not be cleared.', 'Restore access to THREADS_HOME.') from None
