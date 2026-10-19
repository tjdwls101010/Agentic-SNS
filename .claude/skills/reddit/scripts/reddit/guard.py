"""Account protection shared by every invocation of one Aside account: one cross-process lock, Reddit's request
buckets as its rate-limit headers report them, a challenge block, pacing, a per-command budget, a request log.

Reddit counts requests in buckets (wiki pages in one, other .json reads in another) and reports each bucket's state on
every answer: x-ratelimit-used, -remaining and -reset (seconds until the bucket's window resets). Nothing here assumes a
limit or a window length. A bucket is known (the last valid headers and when they reset), unknown (never seen, or its
reset has passed) or unmetered (the first request to it was answered without usable headers). An unknown bucket gets one
probe request at a time; a known bucket's request is reserved (remaining one less, used one more) and fsynced before it
is sent, so a process killed right after sending leaves it counted. A spent bucket is not sent to until it resets; the
command stops instead of waiting there. A 429 blocks its bucket for reset seconds; a browser challenge blocks
everything until a person clears it and doctor --unblock verifies. Unreadable protection state refuses every request.

Every request runs inside `Guard.request()`: under the lock it checks the blocks, the bucket, the budget and the
pacing gap, and the caller sends, reports the headers, classifies the answer and records a block before the lock is
released. The guard knows bucket names and three headers, not Reddit's codes.
"""
import fcntl
import json
import math
import os
import random
import tempfile
import time
from contextlib import contextmanager

from reddit.errors import RedditError
from reddit.paths import state_dir

# 성진: 호출당 100회 상한은 실계정 보호용(R7). 일회용 계정으로 바꾸면 올려도 됨
MAX_BUDGET = 100
DEFAULT_BUDGET = 25
PACE_SECONDS = (1.0, 2.0)
RATE_LIMIT_SECONDS = 600     # a 429 without a usable reset
PROBE_SECONDS = 125          # how long a probe may be in flight: Aside's own time limit (120 s) and a margin
# The skill's own retry interval for a bucket Reddit did not meter, not Reddit's reset (there was none): as long as the
# ten-minute window measured on 2026-10-19.
UNMETERED_SECONDS = 600
# 성진: 늦춤 간격이 30초를 넘으면 기다리지 않고 멈춘다(more:로 이어 읽기) — 셸의 기본 2분 한도 안에서 명령이 끝나도록. 셸 한도가 바뀌면 조정
MAX_WAIT_SECONDS = 30
LOG_SECONDS = 24 * 3600

_UNBLOCK = ('Stop requests. After a person checks Reddit in the Aside browser (and solves any challenge there), run '
            'doctor --unblock.')
_WRITABLE = 'Make the skill\'s data/ directory writable, then retry.'


def _unreadable():
    return RedditError(5, 'Account protection state is unreadable, so requests are refused.',
                       'Check Reddit in the Aside browser, then run doctor --unblock; do not delete data/protection by '
                       'hand.', reason='protection_unreadable')


def _number(value):
    """A header value as a finite non-negative float (Reddit sends "64.0"), else None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def headers_of(ratelimit):
    """(used, remaining, reset) when all three are usable, else None."""
    if not isinstance(ratelimit, dict):
        return None
    values = tuple(_number(ratelimit.get(key)) for key in ('used', 'remaining', 'reset'))
    return None if None in values else values


def _no_wait():
    # A test seam: with a stand-in Aside (REDDIT_ASIDE_BIN) the waits are recorded but not slept, so the suite does not
    # spend minutes in pacing. Against the real browser this switch does nothing.
    return bool(os.environ.get('REDDIT_TEST_NO_WAIT') and os.environ.get('REDDIT_ASIDE_BIN'))


class _Store:
    """The protection files of one Aside account."""

    def __init__(self, directory):
        self.directory = directory

    def read(self, name):
        """The parsed object, None when absent; anything else raises (fail closed)."""
        try:
            value = json.loads((self.directory / name).read_text())
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            raise _unreadable() from None
        if not isinstance(value, dict):
            raise _unreadable()
        return value

    def write(self, name, value):
        """Atomic: a temporary file, fsync, then replace."""
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', dir=self.directory, prefix='.' + name, delete=False) as stream:
                temporary = stream.name
                json.dump(value, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.directory / name)
        except OSError:
            raise RedditError(5, 'Account protection state could not be saved.', _WRITABLE) from None
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def block(self):
        """The challenge block in force, or None."""
        record = self.read('blocked.json')
        if record is None:
            return None
        if record.get('reason') != 'challenge' or type(record.get('blocked_at')) not in (int, float):
            raise _unreadable()
        return record

    def buckets(self):
        record = self.read('buckets.json') or {}
        for name, bucket in record.items():
            if not isinstance(bucket, dict) or bucket.get('status') not in ('known', 'probe', 'unmetered', 'unknown'):
                raise _unreadable()
            for key in ('used', 'remaining', 'reset_at', 'blocked_until', 'until', 'started_at'):
                if key in bucket and bucket[key] is not None and (type(bucket[key]) not in (int, float)
                                                                  or not math.isfinite(bucket[key])):
                    raise _unreadable()
        return record

    def next_allowed(self):
        record = self.read('pace.json')
        if record is None:
            return 0.0
        value = record.get('next_allowed_at')
        if type(value) not in (int, float) or not math.isfinite(value):
            raise _unreadable()
        return value


def _alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _settle(bucket, now):
    """A bucket's state as of `now`: a passed reset or a dead probe's interval makes it unknown again."""
    if bucket is None:
        return {'status': 'unknown'}
    status = bucket['status']
    if status == 'known' and bucket.get('reset_at', 0) <= now:
        return {'status': 'unknown', **({'blocked_until': bucket['blocked_until']}
                                        if bucket.get('blocked_until', 0) > now else {})}
    if status == 'unmetered' and bucket.get('until', 0) <= now:
        return {'status': 'unknown'}
    if status == 'probe' and bucket.get('started_at', 0) + PROBE_SECONDS <= now and (
            not _alive(bucket.get('pid')) or bucket.get('pid') == os.getpid()):
        return {'status': 'unknown'}
    return bucket


def _wait(bucket, now):
    """Seconds before the bucket may be sent to again (0 when it may)."""
    waits = [0.0]
    if bucket.get('blocked_until'):
        waits.append(bucket['blocked_until'] - now)
    if bucket['status'] == 'known' and bucket.get('remaining', 1) <= 0:
        waits.append(bucket['reset_at'] - now)
    if bucket['status'] == 'probe':
        waits.append(bucket.get('started_at', now) + PROBE_SECONDS - now)
    if bucket['status'] == 'unmetered':
        waits.append(bucket.get('until', now) - now)
    return max(waits)


def status(directory):
    """What a harness or doctor may read without a lock or a request: the challenge block and, per bucket, its state
    and wait_seconds (how long before it may be sent to). Unreadable state reads as blocked."""
    store, now = _Store(directory), time.time()
    try:
        block = store.block()
        buckets = {name: _settle(bucket, now) for name, bucket in store.buckets().items()}
    except RedditError:
        return {'blocked': True, 'block_reason': 'protection_unreadable', 'buckets': {}}
    return {'blocked': bool(block), 'block_reason': block['reason'] if block else None,
            'buckets': {name: {**_public(bucket, now), 'wait_seconds': max(0.0, _wait(bucket, now))}
                        for name, bucket in buckets.items()}}


def _public(bucket, now):
    """A bucket as results show it."""
    shown = {'status': bucket['status']}
    if bucket['status'] == 'known':
        shown.update(remaining=bucket['remaining'], limit=bucket['remaining'] + bucket['used'],
                     resets_in=max(0, round(bucket['reset_at'] - now)))
    if bucket.get('blocked_until', 0) > now:
        shown['rate_limited_for'] = round(bucket['blocked_until'] - now)
    return shown


class Slot:
    """One request in progress, inside the lock."""

    def __init__(self, guard, bucket, metered):
        self._guard = guard
        self.bucket = bucket
        self.metered = metered
        self.outcome = 'sent'
        self._headers = None
        self._reported = False

    def report(self, ratelimit):
        """The answer's rate-limit headers ({used, remaining, reset} strings or None)."""
        self._reported = True
        self._headers = headers_of(ratelimit) if self.metered else None

    def classify(self, outcome):
        """Name what the answer was (ok, rate_limited, challenge, login_required, ...) for the request log."""
        self.outcome = outcome

    def rate_limit(self, seconds):
        """A 429: block this bucket for `seconds` (RATE_LIMIT_SECONDS when Reddit gave none)."""
        self._guard._rate_limited(self.bucket, seconds)

    def challenge(self):
        """A browser challenge: block every bucket until a person clears it and doctor --unblock verifies."""
        self._guard._store.write('blocked.json', {'reason': 'challenge', 'blocked_at': time.time(), 'expires_at': None})


class CheckSlot(Slot):
    """The one request doctor --unblock may make while a challenge stands; clear() lifts it inside the lock."""

    def clear(self):
        try:
            (self._guard._store.directory / 'blocked.json').unlink(missing_ok=True)
        except OSError:
            raise RedditError(5, 'The account block could not be cleared.', _WRITABLE) from None


class Guard:
    """The protection and request budget of one invocation for one Aside account."""

    def __init__(self, account, budget):
        if type(budget) is not int or not 1 <= budget <= MAX_BUDGET:
            raise RedditError(2, f'The request budget must be 1 to {MAX_BUDGET}.', 'Pass a smaller --max-requests.')
        self.budget = budget
        self.used = 0           # requests this invocation charged
        self.checked = False    # whether this invocation already made its one unblock check
        self.slowest = 0.0      # the longest slow-down gap Reddit's headers asked for (seconds)
        self.seen = {}          # bucket name → its state after this invocation's last answer from it
        try:
            self._store = _Store(state_dir('protection', account))
        except OSError:
            raise RedditError(5, 'Account protection storage is unavailable.', _WRITABLE) from None

    @property
    def remaining(self):
        return max(0, self.budget - self.used)

    @contextmanager
    def _locked(self):
        try:
            lock = open(self._store.directory / 'lock', 'a')
        except OSError:
            raise RedditError(5, 'Account protection lock is unavailable.', _WRITABLE) from None
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()

    def check(self):
        """Raise when a challenge block stands or the protection state cannot be read."""
        if self._store.block():
            raise RedditError(5, 'Reddit showed a browser challenge for this account; requests stay blocked until a '
                                 'person clears it.', _UNBLOCK, reason='challenge')
        self._store.buckets()

    def _refuse(self, name, bucket, now):
        """Raise when `bucket` may not be sent to now."""
        if bucket.get('blocked_until', 0) > now:
            seconds = math.ceil(bucket['blocked_until'] - now)
            raise RedditError(5, f'Reddit rate-limited this account ({name} requests); they are blocked for about '
                                 f'{seconds} more seconds.', f'Stop requests and retry after {seconds} seconds.',
                              reason='rate_limit')
        if bucket['status'] == 'known' and bucket['remaining'] <= 0:
            seconds = math.ceil(bucket['reset_at'] - now)
            raise RedditError(8, f'Reddit\'s request window for this account is used up ({name} requests); it resets '
                                 f'in {seconds} s.', f'Run more: (or the same --out command) after {seconds} s.',
                              reason='window_spent')
        if bucket['status'] == 'probe':
            # this process's own unanswered probe counts as sent, like a dead one's
            alive = _alive(bucket.get('pid')) and bucket.get('pid') != os.getpid()
            seconds = None if alive else math.ceil(max(1, bucket['started_at'] + PROBE_SECONDS - now))
            raise RedditError(8, 'Another invocation is making the first request of a new Reddit window '
                                 f'({name} requests).' if seconds is None else
                                 'An earlier invocation stopped while making the first request of a new Reddit window '
                                 f'({name} requests); it counts as sent and the next one may go in {seconds} s.',
                              'Run more: (or rerun) a few seconds later.' if seconds is None else
                              f'Run more: (or rerun) after {seconds} s.', reason='probe_pending')
        if bucket['status'] == 'unmetered':
            seconds = math.ceil(bucket['until'] - now)
            raise RedditError(6, f'Reddit did not report its request limit for {name} requests, so this skill sends '
                                 f'none for {seconds} more seconds.', 'Retry later; if it keeps happening, report it '
                                                                       '(Reddit may have changed its rate limits).',
                              reason='unmetered')

    @contextmanager
    def request(self, bucket, *, metered=True):
        """The critical section of one request to `bucket` (metered=False: a request Reddit does not count in a .json
        bucket, such as a share link — budgeted, paced and logged, never a probe)."""
        if self._held is not None:
            slot = self._held
            yield slot
            return
        with self._locked():
            self.check()
            with self._section(bucket, metered, Slot) as slot:
                yield slot

    _held = None  # the unblock check in progress: requests inside it share its critical section

    @contextmanager
    def _section(self, name, metered, kind):
        now = time.time()
        buckets = self._store.buckets()
        bucket = _settle(buckets.get(name), now) if metered else None
        if metered:
            self._refuse(name, bucket, now)
        if kind is Slot and self.used + 1 > self.budget:
            raise RedditError(8, 'The request budget (--max-requests) is spent.',
                              'Run more: to continue, or rerun with a larger --max-requests.', reason='budget')
        gap = self._store.next_allowed() - now
        if gap > MAX_WAIT_SECONDS:
            raise RedditError(8, f'Reddit\'s request window for this account is nearly used up: the next request would '
                                 f'have to wait {math.ceil(gap)} s.', 'Run more: (or the same --out command) later.',
                              reason='window_spent')
        if gap > 0 and not _no_wait():
            time.sleep(gap)
        now = time.time()
        # Reserve before sending, so a process killed after the request leaves it counted and paced.
        self._store.write('pace.json', {'next_allowed_at': now + random.uniform(*PACE_SECONDS)})
        if metered:
            bucket = _settle(self._store.buckets().get(name), now)
            if bucket['status'] == 'known':
                bucket = {**bucket, 'remaining': max(0, bucket['remaining'] - 1), 'used': bucket['used'] + 1}
            else:
                bucket = {'status': 'probe', 'pid': os.getpid(), 'started_at': now,
                          **({'blocked_until': bucket['blocked_until']} if bucket.get('blocked_until') else {})}
            self._put(name, bucket)
        self.used += 1
        slot = kind(self, name, metered)
        try:
            yield slot
        finally:
            self._after(slot)

    def _put(self, name, bucket):
        buckets = self._store.buckets()
        buckets[name] = bucket
        self._store.write('buckets.json', buckets)

    def _after(self, slot):
        """Record what the answer said about the bucket, slow down when it runs low, and log the request."""
        now = time.time()
        if slot.metered:
            current = self._store.buckets().get(slot.bucket) or {'status': 'unknown'}
            blocked = {'blocked_until': current['blocked_until']} if current.get('blocked_until', 0) > now else {}
            if slot._headers is not None:
                used, remaining, reset = slot._headers
                current = {'status': 'known', 'used': used, 'remaining': remaining, 'reset_at': now + reset,
                           'observed_at': now, **blocked}
            elif current.get('status') == 'probe':
                # The first request to this bucket came back without usable headers (or never came back): Reddit's
                # limit is unknown, so nothing more goes to it for a while.
                current = {'status': 'unmetered', 'until': now + UNMETERED_SECONDS, **blocked} if slot._reported \
                    else current
            self._put(slot.bucket, current)
            self.seen[slot.bucket] = current
            if current.get('status') == 'known' and 0 < current['remaining'] <= current['used']:
                gap = (current['reset_at'] - now) / current['remaining']
                self.slowest = max(self.slowest, gap)
                self._store.write('pace.json', {'next_allowed_at': max(self._store.next_allowed(), now + gap)})
        _log(self._store.directory, slot.bucket if slot.metered else 'share', slot.outcome)

    def _rate_limited(self, name, seconds):
        seconds = _number(seconds)
        until = time.time() + (RATE_LIMIT_SECONDS if seconds is None else seconds)
        current = self._store.buckets().get(name) or {'status': 'unknown'}
        self._put(name, {**current, 'blocked_until': max(until, current.get('blocked_until') or 0)})

    @contextmanager
    def verify_unblock(self):
        """The one check request doctor --unblock makes while a challenge stands, inside the lock: the block is lifted
        only when the caller calls slot.clear() after a clean answer. A failure, an exception or a killed process
        leaves it exactly as it was. A bucket's rate limit or spent window is not touched (one general request proves
        nothing about another bucket). One per invocation."""
        with self._locked():
            if self.checked:
                raise RedditError(5, 'This invocation already made its one unblock check.', _UNBLOCK)
            self.checked = True
            self._store.block()  # unreadable protection state fails closed here too
            with self._section('general', True, CheckSlot) as slot:
                self._held = slot
                try:
                    yield slot
                finally:
                    self._held = None

    def window(self):
        """The buckets this invocation used, as results show them."""
        now = time.time()
        return {name: _public(_settle(bucket, now), now) for name, bucket in self.seen.items()}

    def state(self):
        """What doctor reports: the block, every bucket, and when the next request may start."""
        block = self._store.block()
        now = time.time()
        buckets = {name: _settle(bucket, now) for name, bucket in self._store.buckets().items()}
        return {'blocked': bool(block), 'block_reason': block['reason'] if block else None,
                'buckets': {name: {**_public(bucket, now), 'wait_seconds': round(max(0.0, _wait(bucket, now)))}
                            for name, bucket in buckets.items()},
                'next_request_at': max(self._store.next_allowed(), now)}

    def recent(self):
        """Requests logged in the last hour and the last day, every invocation of this account together."""
        now, hour, day = time.time(), 0, 0
        for entry in _log_entries(self._store.directory):
            if now - entry['at'] < 3600:
                hour += entry['n']
            day += entry['n']
        return {'last_hour': hour, 'last_day': day}


def _log_entries(directory):
    """The logged requests of the last day; lines that do not parse are skipped (the log is never a gate)."""
    try:
        lines = (directory / 'requests.jsonl').read_text().splitlines()
    except OSError:
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


def _log(directory, bucket, outcome):
    """Append one request; once a line is a day old the file is rewritten without it. Observation only: a log that
    cannot be written never stops a request."""
    try:
        path = directory / 'requests.jsonl'
        with open(path, 'a') as stream:
            stream.write(json.dumps({'at': time.time(), 'bucket': bucket, 'n': 1, 'outcome': outcome}) + '\n')
        first = path.open().readline()
        try:
            stale = json.loads(first).get('at', 0) < time.time() - LOG_SECONDS
        except (ValueError, AttributeError):
            stale = True
        if stale:
            kept = ''.join(json.dumps(entry) + '\n' for entry in _log_entries(directory))
            temporary = path.with_name('.requests.jsonl.tmp')
            temporary.write_text(kept)
            os.replace(temporary, path)
    except OSError:
        pass
