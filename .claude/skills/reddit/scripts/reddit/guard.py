"""Account protection shared by every invocation of one Aside account: one cross-process lock, Reddit's request
buckets as its rate-limit headers report them, a challenge block, pacing, a per-command budget, a request log.

Reddit counts requests in buckets (wiki pages in one, other .json reads in another) and reports each bucket's state on
every answer: x-ratelimit-used, -remaining and -reset (seconds until the bucket's window resets). Nothing here assumes a
limit or a window length. A bucket is known (the last valid headers and when they reset), unknown (never seen, or its
reset has passed) or unmetered (the first request to it was answered without usable headers). An unknown bucket gets one
probe request at a time; a known bucket's request is reserved (remaining one less, used one more) and fsynced before it
is sent, so a process killed right after sending leaves it counted. A spent bucket is not sent to until it resets; the
command stops instead of waiting there. When a bucket runs low (remaining <= used) its next request waits (seconds to
the reset / remaining); those waits add up to at most MAX_WAIT_SECONDS in one command, which then stops instead. A 429
blocks its bucket for reset seconds, whatever state the bucket later moves through; a browser challenge blocks
everything until a person clears it and doctor --unblock verifies. A share link is requested as a page that Reddit
does not meter: it is budgeted, paced, logged and can be rate-limited, but it is never a probe. Unreadable or
incomplete protection state refuses every request.

Every request runs inside `Guard.request()`: under the lock it checks the blocks, the bucket, the budget and the
pacing gap, logs the request and reserves it, and the caller sends, reports the headers, classifies the answer and
records a block before the lock is released. The guard knows bucket names and three headers, not Reddit's codes.
"""
import fcntl
import json
import math
import os
import random
import secrets
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
# 성진: 한 명령의 늦춤 대기 합이 30초를 넘으면 기다리지 않고 멈춘다(more:로 이어 읽기) — 셸의 기본 2분 한도 안에서 명령이 끝나도록(기본 페이싱 1-2초는 따로). 셸 한도가 바뀌면 조정
MAX_WAIT_SECONDS = 30
LOG_SECONDS = 24 * 3600
STATUSES = {'known': ('used', 'remaining', 'reset_at'), 'probe': ('pid', 'started_at'), 'unmetered': ('until',),
            'unknown': ()}

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


def _valid(bucket):
    """Whether a stored bucket has what its status needs, with finite non-negative times and counts."""
    if not isinstance(bucket, dict) or bucket.get('status') not in STATUSES:
        return False
    for key in STATUSES[bucket['status']]:
        if key not in bucket:
            return False
    for key, value in bucket.items():
        if key == 'status':
            continue
        if key == 'pid':
            if type(value) is not int or value <= 0:
                return False
        elif type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            return False
    return True


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
        if not all(_valid(bucket) for bucket in record.values()):
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
    if pid == os.getpid():
        return False  # this process's own unanswered probe counts as sent, like a dead one's
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _lasting(bucket, now):
    """What outlives any change of a bucket's status: a rate limit and a slow-down still in force."""
    return {key: bucket[key] for key in ('blocked_until', 'slow_until') if bucket.get(key, 0) > now}


def _settle(bucket, now):
    """A bucket's state as of `now`: a passed reset, an expired unmetered interval or a dead probe's interval makes it
    unknown again, keeping a rate limit and a slow-down still in force."""
    if bucket is None:
        return {'status': 'unknown'}
    status = bucket['status']
    if (status == 'known' and bucket['reset_at'] <= now) or (status == 'unmetered' and bucket['until'] <= now) or (
            status == 'probe' and bucket['started_at'] + PROBE_SECONDS <= now and not _alive(bucket['pid'])):
        return {'status': 'unknown', **_lasting(bucket, now)}
    return bucket


def _wait(bucket, now):
    """Seconds before the bucket may be sent to again (0 when it may)."""
    waits = [0.0, bucket.get('blocked_until', 0) - now]
    if bucket['status'] == 'known' and bucket['remaining'] <= 0:
        waits.append(bucket['reset_at'] - now)
    if bucket['status'] == 'probe':
        waits.append(bucket['started_at'] + PROBE_SECONDS - now)
    if bucket['status'] == 'unmetered':
        waits.append(bucket['until'] - now)
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

    def __init__(self, guard, bucket, metered, request_id):
        self._guard = guard
        self.bucket = bucket
        self.metered = metered
        self.request_id = request_id
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

    used_inside = False

    def clear(self):
        try:
            (self._guard._store.directory / 'blocked.json').unlink(missing_ok=True)
        except OSError:
            raise RedditError(5, 'The account block could not be cleared.', _WRITABLE) from None


class Guard:
    """The protection and request budget of one invocation for one Aside account."""

    def __init__(self, account, budget):
        if type(budget) is not int or isinstance(budget, bool) or not 1 <= budget <= MAX_BUDGET:
            raise RedditError(2, f'The request budget must be 1 to {MAX_BUDGET}.', 'Pass a smaller --max-requests.')
        self.budget = budget
        self.used = 0           # requests this invocation charged
        self.checked = False    # whether this invocation already made its one unblock check
        self.slowest = 0.0      # the longest slow-down gap Reddit's headers asked for (seconds)
        self.waited = 0.0       # slow-down seconds this invocation already waited
        self.seen = {}          # bucket name → its state after this invocation's last answer from it
        self._held = None       # the unblock check in progress
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
        self._store.next_allowed()

    def _refuse(self, name, bucket, metered, now):
        """Raise when `bucket` may not be sent to now."""
        if bucket.get('blocked_until', 0) > now:
            seconds = math.ceil(bucket['blocked_until'] - now)
            raise RedditError(5, f'Reddit rate-limited this account ({name} requests); they are blocked for about '
                                 f'{seconds} more seconds.', f'Stop requests and retry after {seconds} seconds.',
                              reason='rate_limit')
        if not metered:
            return
        if bucket['status'] == 'known' and bucket['remaining'] <= 0:
            seconds = math.ceil(bucket['reset_at'] - now)
            raise RedditError(8, f'Reddit\'s request window for this account is used up ({name} requests); it resets '
                                 f'in {seconds} s.', f'Run more: (or the same --out command) after {seconds} s.',
                              reason='window_spent')
        if bucket['status'] == 'probe':
            seconds = None if _alive(bucket['pid']) else math.ceil(max(1, bucket['started_at'] + PROBE_SECONDS - now))
            raise RedditError(8, 'Another invocation is making the first request of a new Reddit window '
                                 f'({name} requests).' if seconds is None else
                                 'An earlier request stopped while making the first request of a new Reddit window '
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
        """The critical section of one request to `bucket` (metered=False: a share link, which Reddit does not count
        in a .json bucket — budgeted, paced, logged and rate-limitable, never a probe). Inside an unblock check, the
        one general request of that check."""
        if self._held is not None:
            held = self._held
            if bucket != 'general' or not metered or held.used_inside:
                raise RedditError(5, 'An unblock check makes one general request and nothing else.', _UNBLOCK)
            held.used_inside = True
            yield held
            return
        with self._locked():
            self.check()
            with self._section(bucket, metered, Slot) as slot:
                yield slot

    @contextmanager
    def _section(self, name, metered, kind):
        now = time.time()
        bucket = _settle(self._store.buckets().get(name), now)
        self._refuse(name, bucket, metered, now)
        if self.used + 1 > self.budget:
            raise RedditError(8, 'The request budget (--max-requests) is spent.',
                              'Run more: to continue, or rerun with a larger --max-requests.', reason='budget')
        pace = self._store.next_allowed() - now
        slow = bucket.get('slow_until', 0) - now
        if pace > MAX_WAIT_SECONDS or (slow > max(pace, 0) and self.waited + slow > MAX_WAIT_SECONDS):
            raise RedditError(8, f'Reddit\'s request window for this account is nearly used up ({name} requests): the '
                                 f'next request would wait {math.ceil(slow)} s more.',
                              'Run more: (or the same --out command) in a minute or after the reset.',
                              reason='window_spent')
        gap = max(pace, slow)
        if gap > 0:
            if slow > max(pace, 0):
                self.waited += slow
            if not _no_wait():
                time.sleep(gap)
        now = time.time()
        request_id = secrets.token_hex(6)
        # Reserve and log before sending, so a process killed after the request leaves it counted, paced and logged.
        self._store.write('pace.json', {'next_allowed_at': now + random.uniform(*PACE_SECONDS)})
        bucket = _settle(self._store.buckets().get(name), now)
        if metered and bucket['status'] == 'known':
            bucket = {**bucket, 'remaining': max(0, bucket['remaining'] - 1), 'used': bucket['used'] + 1}
        elif metered:
            bucket = {'status': 'probe', 'pid': os.getpid(), 'started_at': now, **_lasting(bucket, now)}
        self._put(name, bucket)
        _log(self._store.directory, {'id': request_id, 'bucket': name, 'n': 1, 'outcome': 'sent'})
        self.used += 1
        slot = kind(self, name, metered, request_id)
        try:
            yield slot
        finally:
            self._after(slot)

    def _put(self, name, bucket):
        buckets = self._store.buckets()
        buckets[name] = bucket
        self._store.write('buckets.json', buckets)

    def _after(self, slot):
        """Record what the answer said about the bucket, slow its next request down when it runs low, and log the
        outcome against the request already logged."""
        now = time.time()
        current = self._store.buckets().get(slot.bucket) or {'status': 'unknown'}
        lasting = {k: v for k, v in _lasting(current, now).items() if k == 'blocked_until'}
        if slot.metered:
            if slot._headers is not None:
                used, remaining, reset = slot._headers
                current = {'status': 'known', 'used': used, 'remaining': remaining, 'reset_at': now + reset,
                           'observed_at': now, **lasting}
                if 0 < remaining <= used:
                    gap = reset / remaining
                    self.slowest = max(self.slowest, gap)
                    current['slow_until'] = now + gap
            elif current['status'] == 'probe' and slot._reported:
                # The first request to this bucket came back without usable headers: Reddit's limit is unknown, so
                # nothing more goes to it for a while.
                current = {'status': 'unmetered', 'until': now + UNMETERED_SECONDS, **lasting}
        self._put(slot.bucket, current)
        self.seen[slot.bucket] = current
        if slot.outcome != 'sent':
            _log(self._store.directory, {'id': slot.request_id, 'bucket': slot.bucket, 'n': 0, 'outcome': slot.outcome})

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
        nothing about another bucket). One per invocation, within the budget."""
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
    """The logged lines of the last day; lines that do not parse are skipped (the log is never a gate)."""
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


def _log(directory, entry):
    """Append one line (n 1 when a request is sent; n 0 with its outcome once answered); once the first line is a day
    old the file is rewritten without the old lines. Observation only: a log that cannot be written never stops a
    request."""
    try:
        path = directory / 'requests.jsonl'
        with open(path, 'a') as stream:
            stream.write(json.dumps({'at': time.time(), **entry}) + '\n')
        first = path.open().readline()
        try:
            stale = json.loads(first).get('at', 0) < time.time() - LOG_SECONDS
        except (ValueError, AttributeError):
            stale = True
        if stale:
            kept = ''.join(json.dumps(line) + '\n' for line in _log_entries(directory))
            temporary = path.with_name('.requests.jsonl.tmp')
            temporary.write_text(kept)
            os.replace(temporary, path)
    except OSError:
        pass
