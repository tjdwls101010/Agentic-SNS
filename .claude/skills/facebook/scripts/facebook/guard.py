"""Account protection shared by every invocation: one cross-process lock, a persisted block, pacing, a budget.

Every request runs inside `Guard.request()`: under the lock it checks the block, the budget and the pacing gap, and
the caller makes the request, classifies the response and records a block before the lock is released, so another
invocation cannot start a request between a block and its record. The guard does not know Facebook's codes.
"""
import fcntl
import json
import math
import os
import random
import tempfile
import time
from contextlib import contextmanager

from facebook.errors import FacebookError
from facebook.paths import state_dir

# 성진: 호출당 400회 상한은 실계정 보호용(하루 누적 상한은 두지 않음, D17). 일회용 계정으로 바꾸면 올려도 됨
MAX_BUDGET = 400
RATE_LIMIT_SECONDS = 1800
PACE_SECONDS = (1.0, 2.0)
REASONS = ('checkpoint', 'rate_limit')

_UNBLOCK = 'Stop requests. After a person checks Facebook in the Aside browser, run doctor --unblock.'
_UNREADABLE = FacebookError(5, 'Account protection state is unreadable, so requests are refused.',
                            'Check Facebook in the Aside browser, then run doctor --unblock; do not delete '
                            'data/protection by hand.')


def _directory():
    try:
        return state_dir('protection')
    except OSError:
        raise FacebookError(5, 'Account protection storage is unavailable.', 'Make the skill\'s data/ directory '
                                                                             'writable, then retry.') from None


def _write(name, value):
    """Atomic: a temporary file, fsync, then replace."""
    directory = _directory()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=directory, prefix='.' + name, delete=False) as stream:
            temporary = stream.name
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, directory / name)
    except OSError:
        raise FacebookError(5, 'Account protection state could not be saved.', 'Make the skill\'s data/ directory '
                                                                               'writable, then retry.') from None
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _read(name):
    """The parsed state file (an object), None when absent; anything else raises (fail closed)."""
    try:
        value = json.loads((_directory() / name).read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise _UNREADABLE from None
    if not isinstance(value, dict):
        raise _UNREADABLE
    return value


def _active_block():
    """The block in force as {reason, blocked_at, expires_at}, or None."""
    record = _read('blocked.json')
    if record is None:
        return None
    try:
        reason, expires = record['reason'], record['expires_at']
        if reason not in REASONS:
            raise ValueError
        if reason == 'checkpoint':
            if expires is not None:
                raise ValueError
            return record
        if type(expires) not in (int, float) or not math.isfinite(expires):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise _UNREADABLE from None
    return record if expires > time.time() else None


def _next_allowed():
    record = _read('pace.json')
    if record is None:
        return 0.0
    try:
        value = record['next_allowed_at']
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise _UNREADABLE from None
    return value


def _reserve_pace():
    _write('pace.json', {'next_allowed_at': time.time() + random.uniform(*PACE_SECONDS)})


@contextmanager
def _locked():
    directory = _directory()
    try:
        lock = open(directory / 'lock', 'a')
    except OSError:
        raise FacebookError(5, 'Account protection lock is unavailable.', 'Make the skill\'s data/ directory '
                                                                          'writable, then retry.') from None
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def _blocked_error(record):
    if record['reason'] == 'checkpoint':
        return FacebookError(5, 'Facebook showed a checkpoint for this account; requests stay blocked until a person '
                                'clears it.', _UNBLOCK)
    minutes = max(1, round((record['expires_at'] - time.time()) / 60))
    return FacebookError(5, f'Facebook rate-limited this account; requests are blocked for about {minutes} more '
                            'minutes.', 'Stop requests and retry after the block expires; check Facebook in the Aside '
                                        'browser first.')


class Slot:
    """One request in progress, inside the lock."""

    def __init__(self, guard, reserved, budgeted):
        self._guard = guard
        self.reserved = reserved
        self.budgeted = budgeted

    def charge(self, count):
        """Record how many requests this slot actually made, when more than were reserved."""
        if type(count) is int and count > self.reserved:
            if self.budgeted:
                self._guard.used += count - self.reserved
            else:
                self._guard.setup += count - self.reserved
            self.reserved = count

    def cancel(self):
        """Nothing was sent (the browser tab was gone before the request): give the reservation back."""
        if self.budgeted:
            self._guard.used -= self.reserved
        else:
            self._guard.setup -= self.reserved
        self.reserved = 0

    def block(self, reason):
        """Persist a block before the lock is released: checkpoint (until unblocked) or rate_limit (30 minutes)."""
        if reason not in REASONS:
            raise ValueError(reason)
        now = time.time()
        _write('blocked.json', {'reason': reason, 'blocked_at': now,
                                'expires_at': None if reason == 'checkpoint' else now + RATE_LIMIT_SECONDS})


class Guard:
    """The protection and request budget of one invocation."""

    def __init__(self, budget):
        if type(budget) is not int or not 1 <= budget <= MAX_BUDGET:
            raise FacebookError(2, f'The request budget must be 1 to {MAX_BUDGET}.', 'Pass a smaller --max-requests.')
        self.budget = budget
        self.used = 0    # requests charged to the budget
        self.setup = 0   # requests outside it: opening the dedicated tab

    @property
    def remaining(self):
        return max(0, self.budget - self.used)

    @property
    def count(self):
        """Every request this invocation made, inside the budget or not."""
        return self.used + self.setup

    def check(self):
        """Raise when requests are blocked or the protection state cannot be read."""
        record = _active_block()
        if record:
            raise _blocked_error(record)

    @contextmanager
    def request(self, reserve=1, budgeted=True):
        """The critical section of one request: block check, budget, pacing, then the caller's request.

        budgeted=False is for opening the dedicated tab: counted in `count`, not charged to the budget.
        """
        with _locked():
            self.check()
            if budgeted and self.used + reserve > self.budget:
                raise FacebookError(8, 'The request budget (--max-requests) is spent.',
                                    'Run more: to continue, or rerun with a larger --max-requests.', reason='budget')
            gap = _next_allowed() - time.time()
            if gap > 0:
                time.sleep(gap)
            # Reserve the next gap before the request too, so a killed process cannot leave pacing unrecorded.
            _reserve_pace()
            if budgeted:
                self.used += reserve
            else:
                self.setup += reserve
            try:
                yield Slot(self, reserve, budgeted)
            finally:
                _reserve_pace()

    @contextmanager
    def observe(self):
        """The critical section of looking at the tab without a request (its state, its loaded modules): a saved
        block stops it, and a block it sees is recorded before the lock is released."""
        with _locked():
            self.check()
            yield Slot(self, 0, False)

    def state(self):
        """What doctor reports: the active block, if any, and when the next request may start."""
        record = _active_block()
        return {'blocked': bool(record), 'block_reason': record['reason'] if record else None,
                'block_expires_at': record['expires_at'] if record else None,
                'next_request_at': max(_next_allowed(), time.time())}


def unblock():
    """Clear a persisted block (a person has checked Facebook); pacing is kept."""
    with _locked():
        try:
            (_directory() / 'blocked.json').unlink(missing_ok=True)
        except OSError:
            raise FacebookError(5, 'The account block could not be cleared.', 'Make the skill\'s data/ directory '
                                                                              'writable, then retry.') from None
