"""Account protection shared by every invocation: one cross-process lock, a persisted block for what a person must
clear, per-operation limits from X's headers, pacing, a per-command budget and one deadline.

Every request runs inside `Guard.request()`: under the lock it checks the block, the operation's limit, the budget and
the pacing gap, and the caller makes the request, classifies the response and records a block or a limit before the
lock is released, so another invocation cannot start a request between a block and its record. The guard knows
operation names and header values, never X's codes.

Two kinds of stop are kept apart because they are cleared differently: a lock or challenge blocks every request until a
person clears it and `doctor --unblock` verifies it; an operation's limit (its bucket running out, a 429) stops only
that operation until X's reset, and is never an account block.
"""
import fcntl
import json
import math
import os
import random
import tempfile
import time
from contextlib import contextmanager

from twitter.errors import TwitterError
from twitter.paths import state_dir

# 성진: 호출당 400회 상한은 실계정 보호용(하루 누적 상한은 두지 않음, X4). 일회용 계정으로 바꾸면 올려도 됨
MAX_BUDGET = 400
LOG_SECONDS = 24 * 3600
PACE_SECONDS = (1.0, 2.0)
# 성진: 남은 양이 한도의 20% 아래면 리셋까지 남은 시간에 맞춰 늦춘다(현행 지식, X4). 잠금이 생기면 더 일찍 늦춘다
SLOW_BELOW = 0.2
RESET_WITHOUT_HEADER = 900   # X's limits are 15-minute windows; a 429 without a reset waits one window
# 성진: 명령 하나는 Bash 도구의 2분 안에 끝나야 한다 — 출력·저장 여유를 남긴 기본 마감
DEADLINE_SECONDS = 100
REASONS = ('challenge', 'account_locked')
LOCK_POLL = 0.05
CALL_SECONDS = 3      # the least time a browser call needs: a wait that leaves less is a stop, not a lost request

UNBLOCK_FIX = 'Stop requests. After a person checks x.com in the Aside browser, run doctor --unblock.'
_UNREADABLE = TwitterError(5, 'Account protection state is unreadable, so requests are refused.',
                           'Check x.com in the Aside browser, then run doctor --unblock; do not delete data/protection '
                           'by hand.', reason='unreadable')


def _directory():
    try:
        return state_dir('protection')
    except OSError:
        raise TwitterError(5, 'Account protection storage is unavailable.', 'Make the skill\'s data/ directory writable, '
                                                                            'then retry.', reason='unreadable') from None


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
        raise TwitterError(5, 'Account protection state could not be saved.', 'Make the skill\'s data/ directory '
                                                                              'writable, then retry.',
                           reason='unreadable') from None
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


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _block():
    """The person-cleared block in force as {reason, blocked_at, account_id}, or None."""
    record = _read('blocked.json')
    if record is None:
        return None
    if record.get('reason') not in REASONS or not (record.get('account_id') is None
                                                   or isinstance(record.get('account_id'), str)):
        raise _UNREADABLE
    return record


def _buckets(now):
    """Every operation's bucket whose reset is still ahead: {operation: {limit, remaining, reset[, next_at]}}."""
    record = _read('buckets.json') or {}
    live = {}
    for name, bucket in record.items():
        if not isinstance(bucket, dict) or not all(_number(bucket.get(k)) for k in ('limit', 'remaining', 'reset')):
            raise _UNREADABLE
        if 'next_at' in bucket and not _number(bucket['next_at']):
            raise _UNREADABLE
        if bucket['reset'] > now:
            live[name] = bucket
    return live


def _forget_reset_buckets(now):
    """Drop buckets whose reset has passed, so the file only says what still limits a request."""
    record = _read('buckets.json')
    if record and len(_buckets(now)) != len(record):
        _write('buckets.json', _buckets(now))


def _next_allowed():
    record = _read('pace.json')
    if record is None:
        return 0.0
    value = record.get('next_allowed_at')
    if not _number(value):
        raise _UNREADABLE
    return value


def _blocked_error(record):
    if record['reason'] == 'challenge':
        message = 'X showed a browser challenge for this account; requests stay blocked until a person clears it.'
    else:
        message = 'X locked or suspended this account; requests stay blocked until a person clears it.'
    return TwitterError(5, message, UNBLOCK_FIX, reason=record['reason'], account_id=record.get('account_id'))


def _time_limit():
    return TwitterError(6, 'The command reached its time limit before it could send the next request.',
                        'Run the command again (or its more: line); nothing is wrong with the account.',
                        reason='time_limit')


def _limit_error(operation, reset, next_allowed, slowed=False):
    state = 'nearly used up, so its requests are spaced out' if slowed else 'used up for now'
    return TwitterError(10, f'X\'s limit for {operation} is {state}; it resets at {_local(reset)}.',
                        f'This is not an account problem and other commands still work. Retry this one after '
                        f'{_local(next_allowed)}.', reason='rate_limited', operation=operation, reset=reset,
                        next_allowed_at=next_allowed)


def _local(moment):
    return time.strftime('%H:%M:%S', time.localtime(moment))


def headers_bucket(headers):
    """{limit, remaining, reset} from x-rate-limit-* values (all three integers), else None."""
    try:
        values = [int(str((headers or {})['x-rate-limit-' + key])) for key in ('limit', 'remaining', 'reset')]
    except (KeyError, TypeError, ValueError):
        return None
    return dict(zip(('limit', 'remaining', 'reset'), values))


class Slot:
    """One request (or one look at the tab) in progress, inside the lock."""

    def __init__(self, guard, reserved, budgeted, operation=None):
        self._guard = guard
        self.reserved = reserved
        self.budgeted = budgeted
        self.operation = operation

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

    def observe(self, status, headers):
        """This slot's own response: its operation's bucket from the headers, a 429 empties it."""
        if self.operation:
            self.record_bucket(self.operation, status, headers_bucket(headers) if headers is not None else None)

    def record_bucket(self, operation, status, bucket):
        """Record what a response said about `operation`'s limit: its headers' bucket, and for a 429 remaining 0 with
        the reset from the headers, or one window from now when it is missing or already past."""
        now = self._guard.clock()
        buckets = _buckets(now)
        current = dict(bucket) if bucket else dict(buckets.get(operation) or {})
        if status == 429:
            current.setdefault('limit', 0)
            current['remaining'] = 0
            if not _number(current.get('reset')) or current['reset'] <= now:
                current['reset'] = now + RESET_WITHOUT_HEADER
        if not current:
            return
        if 0 < current['remaining'] < current['limit'] * SLOW_BELOW:
            current['next_at'] = now + (current['reset'] - now) / current['remaining']
        else:
            current.pop('next_at', None)
        buckets[operation] = current
        _write('buckets.json', buckets)

    def block(self, reason, account_id=None):
        """Persist a person-cleared block before the lock is released."""
        if reason not in REASONS:
            raise ValueError(reason)
        _write('blocked.json', {'reason': reason, 'blocked_at': self._guard.clock(),
                                'account_id': account_id if isinstance(account_id, str) else None})


class CheckSlot(Slot):
    """The one request doctor --unblock may make while a block stands; clear() lifts the block inside the lock."""

    def __init__(self, guard, operation, record):
        super().__init__(guard, 1, False, operation)
        self.block_record = record

    def clear(self):
        try:
            (_directory() / 'blocked.json').unlink(missing_ok=True)
        except OSError:
            raise TwitterError(5, 'The account block could not be cleared.', 'Make the skill\'s data/ directory '
                                                                             'writable, then retry.') from None


class Guard:
    """The protection, request budget and deadline of one invocation."""

    def __init__(self, budget, deadline_seconds=None, clock=time.time, monotonic=time.monotonic, sleep=time.sleep):
        if type(budget) is not int or not 1 <= budget <= MAX_BUDGET:
            raise TwitterError(2, f'The request budget must be 1 to {MAX_BUDGET}.', 'Pass a smaller --max-requests.')
        self.budget = budget
        self.clock, self.monotonic, self.sleep = clock, monotonic, sleep
        seconds = DEADLINE_SECONDS if deadline_seconds is None else deadline_seconds
        self.deadline = monotonic() + seconds
        self.used = 0    # requests charged to the budget
        self.setup = 0   # requests outside it: opening the dedicated tab, recovery, the unblock check
        self.checked = False  # whether this invocation already made its one unblock check
        self._held = None     # the unblock check in progress: what runs inside it shares its critical section

    @property
    def remaining(self):
        return max(0, self.budget - self.used)

    @property
    def count(self):
        """Every request this invocation made, inside the budget or not."""
        return self.used + self.setup

    def time_left(self):
        """Seconds until the command's deadline (never negative)."""
        return max(0.0, self.deadline - self.monotonic())

    def check(self):
        """Raise when a person-cleared block stands or the protection state cannot be read."""
        record = _block()
        if record:
            raise _blocked_error(record)

    @contextmanager
    def _locked(self, fail):
        """The cross-process lock, waited for only until the deadline: `fail()` is raised when it does not come."""
        directory = _directory()
        try:
            lock = open(directory / 'lock', 'a')
        except OSError:
            raise TwitterError(5, 'Account protection lock is unavailable.', 'Make the skill\'s data/ directory '
                                                                             'writable, then retry.',
                               reason='unreadable') from None
        try:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if self.time_left() <= LOCK_POLL:
                        raise fail() from None
                    time.sleep(LOCK_POLL)  # real time: another process holds the lock
            yield
        finally:
            try:
                fcntl.flock(lock, fcntl.LOCK_UN)
            finally:
                lock.close()

    def _wait_for(self, operation):
        """(pacing, slowdown): the seconds to wait before `operation` may go, or raise its limit / the deadline when
        the wait would leave less than CALL_SECONDS for the call (see the module docstring)."""
        if self.time_left() <= 0:
            raise _time_limit()
        now = self.clock()
        bucket = _buckets(now).get(operation) if operation else None
        if bucket and bucket['remaining'] <= 0:
            raise _limit_error(operation, bucket['reset'], bucket['reset'])
        pace = max(0.0, _next_allowed() - now)
        slow = max(0.0, bucket['next_at'] - now) if bucket and 'next_at' in bucket else 0.0
        if max(pace, slow) + CALL_SECONDS >= self.time_left():
            if slow > 0 and slow >= pace:
                raise _limit_error(operation, bucket['reset'], bucket['next_at'], slowed=True)
            raise _time_limit()
        return pace, slow

    def _reserve_pace(self):
        _write('pace.json', {'next_allowed_at': self.clock() + random.uniform(*PACE_SECONDS)})

    @contextmanager
    def request(self, operation=None, reserve=1, budgeted=True, kind=None):
        """The critical section of one request: block, the operation's limit, budget and pacing, then the caller's
        request; the caller classifies the response and records a block or a bucket before the lock is released.

        budgeted=False is for setup (opening the dedicated tab, recovery): counted in `count`, not charged to the budget.
        Inside an unblock check the request is part of that check: same critical section, the block standing.
        """
        if self._held is not None:
            self.setup += reserve
            slot = Slot(self, reserve, False, operation)
            try:
                yield slot
            finally:
                _log(kind or 'unblock_check', slot.reserved, operation, self.clock())
            return
        while True:
            with self._locked(_time_limit):
                self.check()
                if budgeted and self.used + reserve > self.budget:
                    raise TwitterError(8, 'The request budget (--max-requests) is spent.',
                                       'Run more: to continue, or rerun with a larger --max-requests.', reason='budget')
                pace, slow = self._wait_for(operation)
                if slow <= pace:
                    if pace > 0:
                        self.sleep(pace)
                    _forget_reset_buckets(self.clock())
                    # Reserve the next gap before the request too, so a killed process cannot leave pacing unrecorded.
                    self._reserve_pace()
                    if budgeted:
                        self.used += reserve
                    else:
                        self.setup += reserve
                    slot = Slot(self, reserve, budgeted, operation)
                    try:
                        yield slot
                    finally:
                        self._reserve_pace()
                        _log(kind or ('query' if budgeted else 'setup'), slot.reserved, operation, self.clock())
                    return
            # This operation's slowdown is waited out without the lock, so other operations' commands go meanwhile;
            # then everything (block, budget, limit, pacing) is weighed again.
            self.sleep(slow)

    @contextmanager
    def observe(self, allow_blocked=False):
        """The critical section of looking at the tab without a request: a saved block stops it (unless
        allow_blocked: emptying the tab, which sends nothing), and a block or bucket it sees is recorded before the lock
        is released."""
        if self._held is not None:
            yield Slot(self, 0, False)
            return
        with self._locked(_time_limit):
            if not allow_blocked:
                self.check()
            yield Slot(self, 0, False)

    @contextmanager
    def verify_unblock(self, operation='Viewer'):
        """The one check request doctor --unblock makes while a block stands, inside the lock. It passes the person
        block alone: the operation's bucket, pacing and the deadline still hold, and when they refuse, the block stays
        and the refusal is exit 5 with verification_reason. The block is lifted only when the caller calls
        slot.clear() after a verified answer; a failure, an exception or a killed process leaves it as it was."""
        def refused(why, **details):
            return TwitterError(5, 'The block stays: the check that could lift it was not made (' + why + ').',
                                UNBLOCK_FIX, reason='verification', verification_reason=why, **details)

        with self._locked(lambda: refused('time_limit')):
            if self.checked:
                raise TwitterError(5, 'This invocation already made its one unblock check.', UNBLOCK_FIX)
            self.checked = True
            record = _block()
            try:
                wait = max(self._wait_for(operation))
            except TwitterError as error:
                if error.reason == 'rate_limited':
                    raise refused('rate_limited', reset=error.details['reset'],
                                  next_allowed_at=error.details['next_allowed_at']) from None
                if error.reason == 'time_limit':
                    raise refused('time_limit') from None
                raise  # unreadable protection state is its own refusal
            if wait > 0:
                self.sleep(wait)
            self._reserve_pace()
            self.setup += 1
            slot = CheckSlot(self, operation, record)
            self._held = slot
            try:
                yield slot
            finally:
                self._held = None
                self._reserve_pace()
                _log('unblock_check', slot.reserved, operation, self.clock())

    @property
    def checking(self):
        """Whether this invocation is inside its one unblock check (a single request: no retry, no reopening)."""
        return self._held is not None

    def log_unwatched(self, count):
        """Requests the tab made while no command watched it (between commands): logged, never charged."""
        _log('unwatched', count, None, self.clock())

    def recent(self):
        """Requests logged in the last hour and the last day, every invocation of this account together."""
        now, hour, day = time.time(), 0, 0
        for entry in _log_entries():
            if now - entry['at'] < 3600:
                hour += entry['n']
            day += entry['n']
        return {'last_hour': hour, 'last_day': day}

    def state(self):
        """What doctor reports: the block, if any, the buckets X has reported that have not reset, and when the next
        request may start."""
        record = _block()
        now = self.clock()
        return {'blocked': bool(record), 'block_reason': record['reason'] if record else None,
                'block_account_id': record.get('account_id') if record else None,
                'buckets': {name: {k: bucket[k] for k in ('limit', 'remaining', 'reset')}
                            for name, bucket in _buckets(now).items()},
                'next_request_at': max(_next_allowed(), now)}


def _log_entries():
    """The logged requests of the last day; lines that do not parse are skipped (the log is never a gate)."""
    try:
        lines = (_directory() / 'requests.jsonl').read_text().splitlines()
    except (OSError, TwitterError):
        return []
    entries, cutoff = [], time.time() - LOG_SECONDS
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if (isinstance(entry, dict) and type(entry.get('at')) in (int, float) and type(entry.get('n')) is int
                and entry['at'] >= cutoff):
            entries.append(entry)
    return entries


def _log(kind, count, operation, moment):
    """Append one request batch; once a line is a day old the file is rewritten without it. Observation only: a log
    that cannot be written never stops a request."""
    if type(count) is not int or count <= 0:
        return
    try:
        path = _directory() / 'requests.jsonl'
        entry = {'at': time.time(), 'kind': kind, 'n': count}
        if operation:
            entry['operation'] = operation
        with open(path, 'a') as stream:
            stream.write(json.dumps(entry) + '\n')
        first = path.open().readline()
        try:
            stale = json.loads(first).get('at', 0) < time.time() - LOG_SECONDS
        except (ValueError, AttributeError):
            stale = True
        if stale:
            kept = ''.join(json.dumps(item) + '\n' for item in _log_entries())
            temporary = path.with_name('.requests.jsonl.tmp')
            temporary.write_text(kept)
            os.replace(temporary, path)
    except (OSError, TwitterError):
        pass
