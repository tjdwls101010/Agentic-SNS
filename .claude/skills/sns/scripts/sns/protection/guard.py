"""Account protection for one platform and one Aside account, shared by every invocation.

Every request runs inside `Guard.request()`: under one cross-process lock it checks the blocks, the scope and the
pacing gap, reserves the request (the next pacing time, the scope's remaining or its probe owner, a log line) and only
then lets the caller send; the caller records what the answer said (header facts, a hold, a person block) before the
lock is released, so another invocation never starts a request between a block and its record.

Two kinds of stop are kept apart because they end differently:
- a person block (a checkpoint, a challenge, a locked account, a network block, or state that could not be read) stops
  every request until a person clears it in the browser and `doctor --unblock` verifies it with one request;
- a hold passes by itself at its time: an account hold (a 429 on a platform without announced limits) stops every
  request of the account, a scope stop (an X operation, a Reddit bucket) only that scope. Unblock never lifts either.
Server-announced limits are one mechanism: a scope with a limit, a remaining count and a reset; nearly spent, its
requests are spaced out until the reset; spent, it stops until then. There is no request budget: a command ends at its
deadline, its natural end, or a platform's signal.
"""
import hashlib
import json
import math
import os
import random
import re
import secrets
import shutil
from contextlib import contextmanager

from sns.atomic import append_line, locked, read_json, write_json
from sns.clock import local
from sns.errors import SnsError
from sns.paths import scope as state_scope

PROBE_SECONDS = 125   # the longest an Aside call can be in flight: a dead owner's probe counts as sent until then
CALL_SECONDS = 3      # the least time a browser call needs: a wait that leaves less is a stop, not a lost request
LOG_SECONDS = 24 * 3600
# what an old install's protection/ holds that is worth taking in (its lock and its own provenance are not)
LEGACY_FILES = ('blocks.json', 'scopes.json', 'pace.json', 'requests.jsonl')
_STATUSES = {'known': ('limit', 'remaining', 'reset_at'), 'probe': ('pid', 'started_at'), 'unknown': ()}
_REASONS = {
    'checkpoint': 'asked this account to pass a security checkpoint',
    'challenge': 'showed a browser challenge for this account',
    'account_locked': 'locked or suspended this account',
    'network_blocked': 'blocked requests from this network',
}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _valid_scope(entry):
    """Whether a stored scope record has every field its status needs, each a number."""
    if not isinstance(entry, dict) or not isinstance(entry.get('status'), str) or entry['status'] not in _STATUSES:
        return False
    return all(_number(entry.get(key)) for key in _STATUSES[entry['status']]) and \
        all(_number(entry[key]) for key in ('slow_until', 'blocked_until', 'observed_at') if key in entry)


def _identity(person):
    """What names one person block across stores: its reason, when it was recorded and for which account; a block for
    an old install's unreadable files is named by the content it stands for, which does not change between tries."""
    source = person.get('source')
    if person.get('reason') == 'unreadable' and isinstance(source, dict) and source.get('broken_sha256'):
        return {'reason': 'unreadable', 'path': source.get('path'), 'broken_sha256': source['broken_sha256']}
    return {'reason': person.get('reason'), 'at': person.get('at'), 'viewer': person.get('viewer')}


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


class Slot:
    """One request (or one look at a tab) in progress, inside the lock."""

    def __init__(self, guard, scope, reserved, setup, request_id, logged=True):
        self._guard = guard
        self.scope = scope
        self.reserved = reserved
        self.setup = setup
        self.request_id = request_id
        self.logged = logged      # whether charges go to the request log now (a look's are logged once, at its end)
        self.outcome = 'sent'
        self.facts = {}

    @property
    def answered(self):
        """Whether an answer came back (it was classified or stated facts); a lost one leaves the request 'sent'."""
        return self.outcome != 'sent' or bool(self.facts)

    def fact(self, scope, fact):
        """What the answer's rate-limit headers stated about `scope` (a limits.Fact)."""
        self.facts[scope] = fact

    def classify(self, outcome):
        """Name what the answer was (ok, rate_limited, checkpoint, login_required, …) for the request log."""
        self.outcome = outcome

    def hold(self, until=None, scope=None):
        """A 429: stop the account (scope None) or `scope` until `until` (the platform's reset), or for the platform's
        default when it gave none. A later, shorter stop never shortens one in force. Returns the error that names
        the stop in force, for the caller to raise."""
        return self._guard._hold(until, scope)

    def block(self, reason, viewer=None):
        """A person block (one of the platform's person reasons), persisted before the lock is released. Returns the
        error that names it, for the caller to raise."""
        return self._guard._block(reason, viewer)

    def charge(self, count):
        """Record how many requests this slot actually made, when more than were reserved (a tab load)."""
        if type(count) is int and count > self.reserved:
            self._guard._recount(self, count - self.reserved)
            self.reserved = count

    def cancel(self):
        """Nothing was sent (the tab was gone before the request): give the reservation back."""
        self._guard._recount(self, -self.reserved)
        self.reserved = 0
        self.outcome = 'cancelled'  # an answer of sorts: nothing is in flight


class CheckSlot(Slot):
    """The one request doctor --unblock makes while a person block stands. `person` is the block it read when it
    started; clear() lifts exactly that block, inside the lock, after a verified answer."""

    def __init__(self, guard, scope, request_id, person):
        super().__init__(guard, scope, 1, True, request_id)
        self.person = person
        self.used_inside = False  # the client's one verification request consumes this reservation

    def clear(self):
        self._guard._clear_person(self.person)


class Guard:
    """The protection of one invocation for one platform and Aside account."""

    def __init__(self, platform, account, policy, deadline, *, title, site):
        self.platform, self.account, self.policy, self.deadline = platform, account, policy, deadline
        self.clock = deadline.clock
        self.title, self.site = title, site
        self.word = platform.replace('_', '-')
        self.directory = state_scope(platform, account, 'protection')
        self.used = 0          # requests this invocation sent for reading
        self.setup = 0         # of those counted apart: opening a tab, recovery, the unblock check
        self.checked = False   # whether this invocation already made its one unblock check
        self.seen = {}         # scope → its state after this invocation's last answer from it
        self._held = None      # the unblock check in progress: requests inside it share its critical section

    # --- counts and errors ---------------------------------------------------------------------------------------

    @property
    def count(self):
        """Every request this invocation made."""
        return self.used + self.setup

    def time_left(self):
        return self.deadline.left()

    def _add(self, count, setup):
        if setup:
            self.setup += count
        else:
            self.used += count

    def _recount(self, slot, extra):
        """A slot made more requests than it reserved (a tab load), or none (cancelled): the counts, the request log
        and a known scope's remaining follow."""
        self._add(extra, slot.setup)
        if slot.logged and extra:
            line = {'id': slot.request_id, 'n': extra, 'outcome': 'sent' if extra > 0 else 'cancelled'}
            if slot.scope is not None:
                line['scope'] = slot.scope
            self._log(line)
        if self._scoped(slot.scope):
            entry = self._scopes().get(slot.scope)
            if entry and entry['status'] == 'known':
                self._put_scope(slot.scope, {**entry, 'remaining': max(0, entry['remaining'] - extra)})

    def _unreadable(self, what='is unreadable'):
        return SnsError('blocked', f'Account protection state {what}, so requests are refused.',
                        f'Check {self.site} in the Aside browser, then run {self.word} doctor --unblock: it sets the '
                        'unreadable files aside and keeps the block until its check passes. Do not delete the '
                        'skill\'s state directory by hand.', reason='unreadable')

    def _fix(self):
        return (f'Stop requests. After a person checks {self.site} in the Aside browser (and clears what it shows '
                f'there), run {self.word} doctor --unblock.')

    def _person_error(self, person):
        if person['reason'] == 'unreadable':
            return SnsError('blocked', 'Account protection state could not be read and was set aside; requests stay '
                                       'blocked until a person checks the account.', self._fix(), reason='unreadable')
        return SnsError('blocked', f'{self.title} {_REASONS[person["reason"]]}; requests stay blocked until a person '
                                   'clears it.', self._fix(), reason=person['reason'], person=True)

    def _hold_error(self, hold):
        return SnsError('blocked', f'{self.title} rate-limited this account; requests stop until {local(hold["until"])} '
                                   'and resume by themselves then.',
                        f'Wait until {local(hold["until"])} (or read another platform meanwhile); doctor --unblock does '
                        'not lift it.', reason='rate_limited', until=hold['until'], scope=None)

    def _scope_error(self, scope, reset, next_allowed, slowed=False):
        state = 'nearly used up, so its requests are spaced out' if slowed else 'used up for now'
        return SnsError('scope_limit', f'{self.title}\'s limit for {scope} is {state}; it resets at {local(reset)}.',
                        'This is not an account problem and other commands still work. Retry this one after '
                        f'{local(next_allowed)}.', reason='rate_limited', scope=scope, reset=reset,
                        next_allowed_at=next_allowed, slowed=slowed)

    @staticmethod
    def _time_limit():
        return SnsError('failed', 'The command reached its time limit before it could send the next request.',
                        'Run the command again (or its more: line); nothing is wrong with the account.',
                        reason='time_limit')

    # --- files ---------------------------------------------------------------------------------------------------

    def _read(self, name):
        return read_json(self.directory / name, self._unreadable)

    def _write(self, name, value):
        write_json(self.directory / name, value, lambda: self._unreadable('could not be saved'))

    def _valid_person(self, person):
        return isinstance(person, dict) and person.get('reason') in (*self.policy.person, 'unreadable') \
            and _number(person.get('at')) and isinstance(person.get('viewer'), (str, type(None)))

    def _blocks(self):
        record = self._read('blocks.json') or {'person': None, 'hold': None}
        person, hold = record.get('person'), record.get('hold')
        if set(record) - {'person', 'hold'} or (person is not None and not self._valid_person(person)):
            raise self._unreadable()
        if hold is not None and not (isinstance(hold, dict) and _number(hold.get('until')) and _number(hold.get('at'))):
            raise self._unreadable()
        return {'person': person, 'hold': hold}

    def _active_hold(self, blocks):
        hold = blocks['hold']
        return hold if hold and hold['until'] > self.clock.time() else None

    def _scopes(self):
        record = self._read('scopes.json') or {}
        if not all(_valid_scope(entry) for entry in record.values()):
            raise self._unreadable()
        return record

    def _next_allowed(self):
        record = self._read('pace.json')
        if record is None:
            return 0.0
        if not _number(record.get('next_allowed_at')):
            raise self._unreadable()
        return record['next_allowed_at']

    def _lasting(self, entry, now):
        """What outlives a change of a scope's status: a stop and a slow-down still in force."""
        return {key: entry[key] for key in ('blocked_until', 'slow_until') if (entry or {}).get(key, 0) > now}

    def _settle(self, entry, now):
        """A scope as of `now`: a passed reset or a reclaimable probe makes it unknown, keeping what still lasts."""
        if entry is None:
            return {'status': 'unknown'}
        status = entry['status']
        if (status == 'known' and entry['reset_at'] <= now) or (
                status == 'probe' and entry['started_at'] + PROBE_SECONDS <= now and not _alive(entry['pid'])):
            return {'status': 'unknown', **self._lasting(entry, now)}
        return entry

    def _put_scope(self, name, entry):
        scopes = self._scopes()
        scopes[name] = entry
        self._write('scopes.json', scopes)

    def _log(self, entry):
        """Append one line; once the first line is a day old the file is rewritten without the old lines.
        Observation only: it is never read to refuse a request, and a log that cannot be written stops nothing."""
        path = self.directory / 'requests.jsonl'
        append_line(path, {'at': self.clock.time(), **entry})
        try:
            with open(path, encoding='utf-8') as stream:
                first = stream.readline()
            stale = json.loads(first).get('at', 0) < self.clock.time() - LOG_SECONDS
        except (OSError, ValueError, AttributeError):
            stale = True
        if stale:
            kept = ''.join(json.dumps(line) + '\n' for line in self._log_entries())
            temporary = path.with_name('.requests.jsonl.tmp')
            try:
                temporary.write_text(kept)
                os.replace(temporary, path)
            except OSError:
                pass

    def _log_entries(self):
        try:
            lines = (self.directory / 'requests.jsonl').read_text(encoding='utf-8').splitlines()
        except OSError:
            return []
        entries, cutoff = [], self.clock.time() - LOG_SECONDS
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and _number(entry.get('at')) and type(entry.get('n')) is int \
                    and entry['at'] >= cutoff:
                entries.append(entry)
        return entries

    @contextmanager
    def _locked(self, fail):
        with locked(self.directory / 'lock', self.deadline, fail, sleep=self.clock.sleep,
                    unavailable=lambda: self._unreadable('cannot be locked')):
            yield

    # --- the checks ----------------------------------------------------------------------------------------------

    def check(self):
        """Raise when a person block or an account hold stands, or the protection state cannot be read."""
        blocks = self._blocks()
        if blocks['person']:
            raise self._person_error(blocks['person'])
        hold = self._active_hold(blocks)
        if hold:
            raise self._hold_error(hold)
        self._scopes()
        self._next_allowed()

    def _scoped(self, scope):
        return scope is not None and self.policy.scope != 'account'

    def _metered(self, scope):
        """A scope whose limit the platform reports (probed, reserved, shown); an unmetered one is only stoppable."""
        return self._scoped(scope) and scope not in self.policy.unmetered

    def _wait(self, scope):
        """(pacing, scope wait): the seconds to wait before a request to `scope` may go, or raise the scope's stop or
        the deadline when the wait leaves less than CALL_SECONDS for the call."""
        if self.deadline.expired:
            raise self._time_limit()
        now = self.clock.time()
        pace = max(0.0, self._next_allowed() - now)
        if not self._scoped(scope):
            if pace + CALL_SECONDS >= self.time_left():
                raise self._time_limit()
            return pace, 0.0
        entry = self._settle(self._scopes().get(scope), now)
        if entry.get('blocked_until', 0) > now:
            raise self._scope_error(scope, entry['blocked_until'], entry['blocked_until'])
        if entry['status'] == 'known' and entry['remaining'] <= 0:
            raise self._scope_error(scope, entry['reset_at'], entry['reset_at'])
        if not self._metered(scope):
            if pace + CALL_SECONDS >= self.time_left():
                raise self._time_limit()
            return pace, 0.0
        wait = max(0.0, entry.get('slow_until', 0) - now)
        if entry['status'] == 'probe':
            # another live command's first request to this scope: never go before it is answered (pacing may not
            # cover it), look again shortly; a dead or lost one counts as sent until the longest Aside call could
            # have ended
            if _alive(entry['pid']):
                wait = max(wait, 1.0, pace + 0.001)
            else:
                wait = max(wait, entry['started_at'] + PROBE_SECONDS - now)
        if max(pace, wait) + CALL_SECONDS >= self.time_left():
            if wait > 0 and wait >= pace:
                reset = entry.get('reset_at') or now + wait
                raise self._scope_error(scope, reset, now + wait, slowed=True)
            raise self._time_limit()
        return pace, wait

    def _reserve(self, scope, kind, reserve, setup):
        """Inside the lock, before sending: the next pacing time, the scope's reservation, one log line."""
        now = self.clock.time()
        self._write('pace.json', {'next_allowed_at': now + random.uniform(*self.policy.pace)})
        if self._metered(scope):
            entry = self._settle(self._scopes().get(scope), now)
            if entry['status'] == 'known':
                entry = {**entry, 'remaining': max(0, entry['remaining'] - reserve)}
            else:
                entry = {'status': 'probe', 'pid': os.getpid(), 'started_at': now, **self._lasting(entry, now)}
            self._put_scope(scope, entry)
        request_id = secrets.token_hex(6)
        line = {'id': request_id, 'kind': kind, 'n': reserve, 'outcome': 'sent'}
        if scope is not None:
            line['scope'] = scope
        self._log(line)
        self._add(reserve, setup)
        return request_id

    def _after(self, slot):
        """Inside the lock, after the answer: the next pacing gap, what the headers said, the outcome in the log."""
        now = self.clock.time()
        try:
            self._write('pace.json', {'next_allowed_at': now + random.uniform(*self.policy.pace)})
        except SnsError:
            pass  # the reservation before sending already spaced this request out
        for name, fact in slot.facts.items():
            if self._metered(name):
                self._apply_fact(name, fact, now)
        if self._metered(slot.scope) and slot.scope not in slot.facts:
            entry = self._settle(self._scopes().get(slot.scope), now)
            if entry['status'] == 'probe' and entry.get('pid') == os.getpid() and slot.answered:
                # answered without usable headers: the scope's limit stays unknown; pacing alone spaces requests (a
                # lost answer keeps the probe: the request may still be in flight)
                self._put_scope(slot.scope, {'status': 'unknown', **self._lasting(entry, now)})
        if self._metered(slot.scope):
            self.seen[slot.scope] = self._settle(self._scopes().get(slot.scope), now)
        if slot.outcome != 'sent':
            line = {'id': slot.request_id, 'n': 0, 'outcome': slot.outcome}
            if slot.scope is not None:
                line['scope'] = slot.scope
            self._log(line)

    def _apply_fact(self, name, fact, now):
        if not all(_number(v) for v in (fact.limit, fact.remaining, fact.reset_at)):
            return
        current = self._settle(self._scopes().get(name), now)
        entry = {'status': 'known', 'limit': fact.limit, 'remaining': fact.remaining, 'reset_at': fact.reset_at,
                 'observed_at': now}
        # a stop in force outlives a later fact: an explicit one, and a spent window until its reset
        stops = [current.get('blocked_until', 0)]
        if current['status'] == 'known' and current['remaining'] <= 0:
            stops.append(current['reset_at'])
        if max(stops) > now:
            entry['blocked_until'] = max(stops)
        remaining, limit = fact.remaining, fact.limit
        low = (self.policy.slow == 'fraction' and 0 < remaining < limit * self.policy.slow_fraction) or \
            (self.policy.slow == 'used' and 0 < remaining <= limit - remaining)
        if low and fact.reset_at > now:
            entry['slow_until'] = now + (fact.reset_at - now) / remaining
        self._put_scope(name, entry)

    def _hold(self, until, scope):
        now = self.clock.time()
        until = until if _number(until) and until > now else now + self.policy.hold_seconds
        if self._scoped(scope):
            current = self._settle(self._scopes().get(scope), now)
            stop = max(until, current.get('blocked_until', 0))
            self._put_scope(scope, {**current, 'blocked_until': stop})
            return self._scope_error(scope, stop, stop)
        blocks = self._blocks()
        held = self._active_hold(blocks)
        if held and held['until'] >= until:
            return self._hold_error(held)
        blocks['hold'] = {'reason': 'rate_limit', 'at': now, 'until': until}
        self._write('blocks.json', blocks)
        return self._hold_error(blocks['hold'])

    def _block(self, reason, viewer):
        if reason not in self.policy.person:
            raise ValueError(f'{reason!r} is not a person reason of {self.platform}')
        blocks = self._blocks()
        blocks['person'] = {'reason': reason, 'at': self.clock.time(),
                            'viewer': viewer if isinstance(viewer, str) else None}
        self._write('blocks.json', blocks)
        return self._person_error(blocks['person'])

    def _clear_person(self, person):
        if person is None:
            return
        blocks = self._blocks()
        if blocks['person'] != person:
            return
        # a block an old install still owed (another stood when it came in) takes this one's place in the same write,
        # so no moment passes with neither standing; the queue and the record of this clear follow. Should the second
        # write not happen, the next clear finds this block's own copy in the queue and drops it
        entries = self._provenance()
        cleared = _identity(person)
        waiting = [e for e in entries if e['kind'] == 'owed' and _identity(e['person']) != cleared]
        blocks['person'] = waiting[0]['person'] if waiting else None
        self._write('blocks.json', blocks)
        placed = _identity(waiting[0]['person']) if waiting else None
        entries = [e for e in entries if not (e['kind'] == 'owed' and _identity(e['person']) in (cleared, placed))]
        entries.append({'kind': 'cleared', 'at': self.clock.time(), 'person': cleared})
        self._write('imported.json', {'entries': entries})

    # --- requests ------------------------------------------------------------------------------------------------

    @contextmanager
    def request(self, scope=None, reserve=1, kind='query', setup=False):
        """The critical section of one request (see the module docstring). setup=True counts it apart (opening a tab,
        recovery). Inside an unblock check it is part of that check: the same critical section, the block standing."""
        if self._held is not None:
            held = self._held
            if not held.used_inside and not setup and scope == held.scope:
                held.used_inside = True  # the check's own request: already reserved, counted and logged
                yield held
                return
            request_id = self._reserve(None, kind, reserve, True)
            slot = Slot(self, scope, reserve, True, request_id)
            try:
                yield slot
            finally:
                self._after(slot)
            return
        while True:
            with self._locked(self._time_limit):
                self.check()
                pace, wait = self._wait(scope)
                if wait <= pace:
                    self.clock.sleep(pace)
                    slot = Slot(self, scope, reserve, setup, self._reserve(scope, kind, reserve, setup))
                    try:
                        yield slot
                    finally:
                        self._after(slot)
                    return
            # a slowed scope (or a reclaimable probe) is waited out without the lock, so other scopes' requests go
            # meanwhile; then everything is weighed again
            self.clock.sleep(wait)

    @contextmanager
    def observe(self, allow_blocked=False):
        """The critical section of looking at a tab without a request: a standing block stops it unless allow_blocked
        (emptying the tab, which sends nothing); a block the look sees is recorded before the lock is released."""
        slot = Slot(self, None, 0, False, None, logged=False)
        if self._held is not None:
            yield slot
            return
        with self._locked(self._time_limit):
            if not allow_blocked:
                self.check()
            yield slot
        if slot.reserved:  # requests the page made on its own that the look saw and charged to this command
            self._log({'id': secrets.token_hex(6), 'kind': 'background', 'n': slot.reserved, 'outcome': 'seen'})
        if slot.outcome != 'sent':  # what the look found (a block signal) belongs in the log a run is watched by
            self._log({'id': secrets.token_hex(6), 'kind': 'look', 'n': 0, 'outcome': slot.outcome})

    def log_unwatched(self, count):
        """Requests an open tab made while no command watched it: logged, never charged to a command."""
        if type(count) is int and count > 0:
            self._log({'id': secrets.token_hex(6), 'kind': 'unwatched', 'n': count, 'outcome': 'seen'})

    @property
    def checking(self):
        """Whether this invocation is inside its one unblock check."""
        return self._held is not None

    @contextmanager
    def verify_unblock(self, scope=None):
        """The one check request doctor --unblock may make while a person block stands, inside the lock. A hold or the
        check's scope stop still applies (the check would itself be a request), and so do pacing and the deadline:
        when they refuse, the block stays and the refusal names why. The block is lifted only when the caller calls
        clear() after a verified answer; a failure, an exception or a killed process leaves it as it was."""
        def refused(why, **details):
            return SnsError('blocked', f'The block stays: the check that could lift it was not made ({why}).',
                            self._fix(), reason='verification', verification_reason=why, **details)

        with self._locked(lambda: refused('time_limit')):
            if self.checked:
                raise SnsError('blocked', 'This invocation already made its one unblock check.', self._fix())
            self.checked = True
            self._set_aside_unreadable()
            blocks = self._blocks()
            hold = self._active_hold(blocks)
            if hold:
                raise refused('rate_limited', until=hold['until'])
            try:
                pace, wait = self._wait(scope)
            except SnsError as error:
                if error.kind == 'scope_limit':
                    raise refused('rate_limited', reset=error.details['reset'],
                                  next_allowed_at=error.details['next_allowed_at']) from None
                raise refused('time_limit') from None
            self.clock.sleep(max(pace, wait))
            slot = CheckSlot(self, scope, self._reserve(scope, 'unblock_check', 1, True), blocks['person'])
            self._held = slot
            try:
                yield slot
            finally:
                self._held = None
                self._after(slot)

    def _set_aside_unreadable(self):
        """Inside the unblock check's lock: an unreadable state file is copied for a person as
        <name>.unreadable-<time> and replaced; a person block for unreadable state stands until the check lifts it."""
        broken = []
        for name, read in (('blocks.json', self._blocks), ('scopes.json', self._scopes),
                           ('pace.json', self._next_allowed)):
            try:
                read()
            except SnsError as error:
                if error.reason != 'unreadable':
                    raise
                broken.append(name)
        if not broken:
            return
        stamp = int(self.clock.time())
        for name in broken:
            target, extra = self.directory / f'{name}.unreadable-{stamp}', 1
            while target.exists():
                target, extra = self.directory / f'{name}.unreadable-{stamp}-{extra}', extra + 1
            try:
                shutil.copyfile(self.directory / name, target)
                if name != 'blocks.json':
                    (self.directory / name).unlink()
            except OSError:
                raise SnsError('blocked', f'Account protection file {name} is not a readable file, so requests are '
                                          'refused and it cannot be set aside.',
                               f'A person should repair or remove it in the skill\'s state directory after checking {self.site} '
                               'in the Aside browser.', reason='unreadable') from None
        blocks = {'person': None, 'hold': None} if 'blocks.json' in broken else self._blocks()
        blocks['person'] = blocks['person'] or {'reason': 'unreadable', 'at': self.clock.time(), 'viewer': None}
        self._write('blocks.json', blocks)

    # --- reports and the legacy converter -------------------------------------------------------------------------

    def _public(self, entry, now):
        shown = {'status': entry['status']}
        if entry['status'] == 'known':
            shown.update(limit=entry['limit'], remaining=entry['remaining'], reset_at=entry['reset_at'])
        if entry.get('blocked_until', 0) > now:
            shown['blocked_until'] = entry['blocked_until']
        if entry.get('slow_until', 0) > now:
            shown['slow_until'] = entry['slow_until']
        return shown

    def limits(self):
        """The scopes this invocation used, as results show them."""
        now = self.clock.time()
        return {name: self._public(self._settle(entry, now), now) for name, entry in self.seen.items()}

    def state(self):
        """What doctor reports: the person block and hold in force, every scope, and when the next request may go."""
        blocks, now = self._blocks(), self.clock.time()
        hold = self._active_hold(blocks)
        person = blocks['person']
        return {'blocked': bool(person or hold), 'block_reason': person['reason'] if person else
                ('rate_limited' if hold else None), 'person': person, 'hold': hold,
                'scopes': {name: self._public(self._settle(entry, now), now) for name, entry in self._scopes().items()},
                'next_request_at': max(self._next_allowed(), now)}

    def recent(self):
        """Requests logged in the last hour and the last day, every invocation of this account together."""
        now, hour, day = self.clock.time(), 0, 0
        for entry in self._log_entries():
            if now - entry['at'] < 3600:
                hour += entry['n']
            day += entry['n']
        return {'last_hour': hour, 'last_day': day}

    def _provenance(self):
        record = self._read('imported.json') or {'entries': []}
        entries = record.get('entries')
        if not isinstance(entries, list) or not all(isinstance(e, dict) and e.get('kind') in ('imported', 'exported',
                                                                                               'cleared', 'owed')
                                                    for e in entries):
            raise self._unreadable()
        return entries

    def snapshot(self):
        """A read-only copy for the legacy converter: the person block, the hold and the scopes in force, and the
        provenance of what was imported from or exported to the old skills."""
        blocks, now = self._blocks(), self.clock.time()
        return {'person': blocks['person'], 'hold': self._active_hold(blocks),
                'scopes': {name: self._settle(entry, now) for name, entry in self._scopes().items()},
                'provenance': self._provenance()}

    def merge(self, person=None, hold=None, scopes=None, source=None):
        """Fold state read from an old skill in, keeping the stricter side of each slot (a later time; an existing
        person block stays as it is) and recording the source; the same input twice changes nothing more."""
        if person is not None and person.get('reason') not in (*self.policy.person, 'unreadable'):
            raise ValueError(f'{person.get("reason")!r} is not a person reason of {self.platform}')
        with self._locked(self._time_limit):
            self._merge(person, hold, scopes, source)
            if source is not None:
                entries = self._provenance()
                mark = {'kind': 'imported', 'path': source.get('path'), 'sha256': source.get('sha256')}
                if not any({k: e.get(k) for k in mark} == mark for e in entries):
                    entries.append({**mark, 'at': self.clock.time()})
                    self._write('imported.json', {'entries': entries})

    def _merge(self, person, hold, scopes, source):
        """merge() inside the lock: the stricter side of each slot."""
        now = self.clock.time()
        blocks = self._blocks()
        if person is not None and blocks['person'] is None:
            blocks['person'] = {'reason': person['reason'], 'at': person.get('at') or now,
                                'viewer': person.get('viewer') if isinstance(person.get('viewer'), str) else None,
                                'source': source}
        if hold is not None and _number(hold.get('until')) and hold['until'] > now:
            current = self._active_hold(blocks)
            if not current or current['until'] < hold['until']:
                blocks['hold'] = {'reason': 'rate_limit', 'at': hold.get('at') or now, 'until': hold['until'],
                                  'source': source}
        self._write('blocks.json', blocks)
        stored = self._scopes()
        for name, given in (scopes or {}).items():
            entry = self._settle(stored.get(name), now)
            for key in ('blocked_until', 'slow_until'):
                if _number(given.get(key)) and given[key] > max(now, entry.get(key, 0)):
                    entry[key] = given[key]
            spent = entry['status'] == 'known' and entry['remaining'] <= 0
            later = entry['status'] != 'probe' or given.get('started_at', 0) > entry.get('started_at', 0)
            if given.get('status') == 'probe' and not spent and later and _valid_scope(given) and \
                    self._settle(given, now)['status'] == 'probe':
                # an old copy's request in flight in this scope: no other request until it is answered or reclaimable
                # (a spent scope already stops until its reset; of two probes the later one is kept)
                # 성진: 옛 사본 둘이 같은 범위에 동시에 요청 중일 때 하나만 남긴다 — 둘 다 기록해야 할 사례가 보이면 목록으로
                entry = {'status': 'probe', 'pid': given['pid'], 'started_at': given['started_at'],
                         **self._lasting(entry, now)}
            if all(_number(given.get(k)) for k in ('limit', 'remaining', 'reset_at')) and given['reset_at'] > now:
                if entry['status'] == 'known':
                    entry['remaining'] = min(entry['remaining'], given['remaining'])
                    entry['reset_at'] = max(entry['reset_at'], given['reset_at'])
                else:
                    entry.update(status='known', limit=given['limit'], remaining=given['remaining'],
                                 reset_at=given['reset_at'])
                    entry.pop('pid', None)
                    entry.pop('started_at', None)
            stored[name] = entry
        self._write('scopes.json', stored)

    def adopt(self, legacy):
        """Take in the protection state an install from before the state moved left in `legacy` (its old
        data/<platform>/<account>/protection/), every time its content differs from what was last taken from that
        path (a copy of the old version still writing there, or one put back by hand), inside this lock. A person
        block stays whichever side has it, unless it is the very block a person cleared here; a hold and a scope stop
        keep the later end; pacing keeps the later next request; the request log takes the old lines of the last day
        it does not have yet. An old file that cannot be read is a person block for unreadable state (doctor --unblock
        lifts it), and what the other old files hold is still taken in. True when something was taken in."""
        names = [name for name in LEGACY_FILES if (legacy / name).exists() or (legacy / name).is_symlink()]
        if not names:
            return False
        raw, broken = {}, []
        for name in names:
            try:
                raw[name] = (legacy / name).read_bytes()
            except OSError:
                broken.append(name)
        digest = hashlib.sha256()
        for name in names:
            digest.update(name.encode() + b'\0' + raw.get(name, b'unreadable') + b'\0')
        mark = {'kind': 'imported', 'path': str(legacy), 'sha256': digest.hexdigest()}
        try:
            if self._last_import(self._provenance(), mark['path']) == mark['sha256']:
                return False  # the usual case, without waiting for the lock
        except SnsError:
            pass  # unreadable provenance: decided under the lock, which reports it
        with self._locked(self._time_limit):
            entries = self._provenance()
            if self._last_import(entries, mark['path']) == mark['sha256']:
                return False
            now = self.clock.time()
            source = {'path': mark['path'], 'sha256': mark['sha256']}
            parsed, unreadable = self._legacy_state(raw)
            broken += unreadable
            # every person block this old state stands for: its own, and one for each file that could not be read;
            # one person block stands at a time, so the source counts as taken in only once each of them has stood
            # (it stands now, or a person cleared it) — until then every command of this install tries again, and
            # the holds, scopes, pacing and log merge the same way each time
            owed = []
            if parsed['person'] is not None:
                owed.append(dict(parsed['person']))
            synthesized = None
            if broken:
                # named by the broken files alone, so an old copy that keeps writing its log does not bring it back
                damaged = hashlib.sha256()
                for name in sorted(broken):
                    damaged.update(name.encode() + b'\0' + raw.get(name, b'unreadable') + b'\0')
                synthesized = {'reason': 'unreadable', 'at': now, 'viewer': None,
                               'source': {**source, 'files': sorted(broken), 'broken_sha256': damaged.hexdigest()}}
                owed.append(synthesized)
            cleared = [e.get('person') for e in entries if e['kind'] == 'cleared']
            waiting = [_identity(e['person']) for e in entries if e['kind'] == 'owed']
            standing = self._blocks()['person']
            owed = [b for b in owed if _identity(b) not in cleared and _identity(b) not in waiting and
                    (standing is None or _identity(standing) != _identity(b))]
            place = owed.pop(0) if owed and standing is None else None
            self._merge(place, parsed['hold'], parsed['scopes'], source)
            if place is not None and place is synthesized:
                blocks = self._blocks()  # _merge records its own source; the unreadable block keeps the one naming files
                blocks['person']['source'] = place['source']
                self._write('blocks.json', blocks)
            if parsed['next_allowed_at'] > self._next_allowed():
                self._write('pace.json', {'next_allowed_at': parsed['next_allowed_at']})
            self._adopt_log(parsed['log'])
            # the rest wait in this store, not in the old folder (a later update may remove it): each takes the
            # standing block's place when a person clears that one
            for block in owed:
                entries.append({'kind': 'owed', 'at': now,
                                'person': {**block, 'source': block.get('source') or source}})
            entries.append({**mark, 'at': now})
            self._write('imported.json', {'entries': entries})
            return True

    @staticmethod
    def _last_import(entries, path):
        last = next((e for e in reversed(entries) if e['kind'] == 'imported' and e.get('path') == path), None)
        return last.get('sha256') if last else None

    def _legacy_state(self, raw):
        """The old protection files read with this store's own rules, file by file: (what could be read, the names
        of the files that could not)."""
        state = {'person': None, 'hold': None, 'scopes': {}, 'next_allowed_at': 0.0, 'log': []}
        broken = []

        def load(name):
            value = json.loads(raw[name].decode('utf-8'))
            if not isinstance(value, dict):
                raise ValueError(name)
            return value
        if 'blocks.json' in raw:
            try:
                blocks = load('blocks.json')
            except (ValueError, UnicodeError):
                blocks = None
            if blocks is None:
                broken.append('blocks.json')
            else:
                # each record on its own: a broken person record does not take a valid hold beside it down
                person, hold = blocks.get('person'), blocks.get('hold')
                if person is None or self._valid_person(person):
                    state['person'] = person
                else:
                    broken.append('blocks.json')
                if hold is None or (isinstance(hold, dict) and _number(hold.get('until'))):
                    state['hold'] = hold
                elif 'blocks.json' not in broken:
                    broken.append('blocks.json')
                if set(blocks) - {'person', 'hold'} and 'blocks.json' not in broken:
                    broken.append('blocks.json')
        if 'scopes.json' in raw:
            try:
                scopes = load('scopes.json')
            except (ValueError, UnicodeError):
                scopes = None
            if scopes is None:
                broken.append('scopes.json')
            else:
                # the records this store would accept come in; any other makes the file unreadable
                state['scopes'] = {name: entry for name, entry in scopes.items() if _valid_scope(entry)}
                if len(state['scopes']) != len(scopes):
                    broken.append('scopes.json')
        if 'pace.json' in raw:
            try:
                next_allowed = load('pace.json').get('next_allowed_at')
                if not _number(next_allowed):
                    raise ValueError('pace')
                state['next_allowed_at'] = next_allowed
            except (ValueError, UnicodeError):
                broken.append('pace.json')
        if 'requests.jsonl' in raw:
            # a log line that cannot be read is skipped, as the store's own log reader does
            state['log'] = [line for line in raw['requests.jsonl'].decode('utf-8', 'replace').splitlines()
                            if line.strip()]
        return state, broken

    def _adopt_log(self, lines):
        """Add the old log's lines of the last day this log does not have yet (the same line twice is one request),
        in time order, so requests_last_day goes on from both and taking the same lines in again adds nothing."""
        cutoff, wanted = self.clock.time() - LOG_SECONDS, []
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and _number(entry.get('at')) and type(entry.get('n')) is int \
                    and entry['at'] >= cutoff:
                wanted.append(entry)
        if not wanted:
            return
        mine = self._log_entries()
        have = {json.dumps(entry, sort_keys=True) for entry in mine}
        added = []
        for entry in wanted:
            key = json.dumps(entry, sort_keys=True)
            if key not in have:
                have.add(key)
                added.append(entry)
        if not added:
            return
        merged = sorted(mine + added, key=lambda entry: entry['at'])
        path = self.directory / 'requests.jsonl'
        temporary = path.with_name('.requests.jsonl.adopt')
        try:
            temporary.write_text(''.join(json.dumps(entry) + '\n' for entry in merged), encoding='utf-8')
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except OSError:
            raise self._unreadable('could not be saved') from None


def open_guard(platform, account, policy, deadline, *, title, site):
    """The protection of one invocation: `policy` is the platform's limits.LimitPolicy, `deadline` the invocation's."""
    return Guard(platform, account, policy, deadline, title=title, site=site)
