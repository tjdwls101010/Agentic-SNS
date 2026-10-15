"""Process-shared reservations, pacing and blocks for the Aside Reddit account."""
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import random
import tempfile
import time

from ._errors import RedditError


def _number(value):
    if isinstance(value, bool):
        raise ValueError
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError
    return number


class Budget:
    def __init__(self, home=None, *, clock=time.time, monotonic=time.monotonic,
                 sleep=time.sleep, jitter=None):
        self.home = Path(home or os.environ.get('REDDIT_HOME', Path.home() / '.cache/reddit-skill'))
        self.clock, self.monotonic, self.sleep = clock, monotonic, sleep
        self.jitter = jitter or (lambda: random.uniform(0, 0.5))
        self._state = None

    @contextmanager
    def account_lock(self):
        try:
            self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
            lock = (self.home / 'account.lock').open('a')
        except OSError:
            raise RedditError(6, 'Cannot open the Reddit budget directory.') from None
        with lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _fresh(self):
        now = self.clock()
        return {'observed_at': now, 'expires_at': now + 600, 'remaining': 100,
                'used': 0, 'next_allowed_at': now, 'block': None}

    def _read(self):
        try:
            state = json.loads((self.home / 'budget.json').read_text())
            for key in ('observed_at', 'expires_at', 'remaining', 'used', 'next_allowed_at'):
                state[key] = _number(state[key])
            block = state.get('block')
            if block is not None:
                if not isinstance(block, dict) or block.get('reason') not in {'challenge', 'rate_limit'}:
                    raise ValueError
                if block['expires_at'] is not None:
                    block['expires_at'] = _number(block['expires_at'])
            now = self.clock()
            if state['observed_at'] > now or state['expires_at'] <= now:
                next_allowed = state['next_allowed_at'] if state['observed_at'] <= now else now
                state = self._fresh()
                state['next_allowed_at'] = next_allowed
                if block and block['reason'] == 'challenge':
                    state['block'] = block
            elif block and block['expires_at'] is not None and block['expires_at'] <= now:
                state['block'] = None
            return state
        except FileNotFoundError:
            return self._fresh()
        except (OSError, ValueError, KeyError, TypeError):
            raise RedditError(6, 'The Reddit budget file is unreadable or malformed.',
                              'Inspect the local budget file before making more requests.') from None

    def _save(self):
        name = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=self.home, delete=False) as stream:
                name = stream.name
                json.dump(self._state, stream, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.home / 'budget.json')
        except OSError:
            raise RedditError(6, 'Cannot persist the Reddit request budget.') from None
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    @property
    def snapshot(self):
        """Current shared state; reading never reserves a request."""
        with self.account_lock():
            return self._read()

    @contextmanager
    def request(self):
        """Hold the flock through reservation, external request and response observation."""
        with self.account_lock():
            self._state = self._read()
            try:
                state = self._state
                block = state.get('block')
                if block or state['remaining'] <= 0:
                    expires = block['expires_at'] if block else state['expires_at']
                    fix = ('Check Reddit in Aside, then run doctor --unblock.' if expires is None else
                           f'Stop requests; retry after {math.ceil(max(0, expires - self.clock()))} seconds.')
                    raise RedditError(5, 'Reddit requests are blocked.', fix)
                deadline = self.monotonic() + max(0, state['next_allowed_at'] - self.clock())
                while (delay := deadline - self.monotonic()) > 0:
                    self.sleep(delay)
                # The window may have expired while normal pacing was in progress.
                if state['expires_at'] <= self.clock():
                    self._state = state = self._fresh()
                state['remaining'] = max(0, state['remaining'] - 1)
                state['used'] += 1
                state['observed_at'] = self.clock()
                state['next_allowed_at'] = self.clock() + 1 + max(0, min(0.5, self.jitter()))
                self._govern()
                self._save()
                yield self
            finally:
                self._state = None

    def observe(self, headers):
        """Update inside request(); invalid or partial header sets keep the reservation."""
        if self._state is None:
            raise RuntimeError('observe requires an active request')
        try:
            remaining, used, reset = (_number(headers[key]) for key in ('remaining', 'used', 'reset'))
        except (KeyError, TypeError, ValueError):
            return
        now = self.clock()
        self._state.update(observed_at=now, expires_at=now + reset, remaining=remaining, used=used)
        if remaining == 0:
            self._state['block'] = {'reason': 'rate_limit', 'expires_at': now + reset}
        self._govern()
        self._save()

    def _govern(self):
        state = self._state
        if 0 < state['remaining'] <= state['used']:
            delay = max(0, state['expires_at'] - self.clock()) / state['remaining']
            state['next_allowed_at'] = max(state['next_allowed_at'], self.clock() + delay)

    def block(self, reason, seconds=None):
        """Persist a classification decision inside the active request lock."""
        if self._state is None:
            raise RuntimeError('block requires an active request')
        if reason not in {'challenge', 'rate_limit'}:
            raise ValueError('Unknown block reason')
        expires = None if reason == 'challenge' else self.clock() + (600 if seconds is None else _number(seconds))
        self._state['block'] = {'reason': reason, 'expires_at': expires}
        if reason == 'rate_limit':
            self._state.update(remaining=0, expires_at=expires)
        self._save()

    def unblock(self):
        """doctor --unblock clears challenges; rate limits expire automatically."""
        with self.account_lock():
            self._state = self._read()
            try:
                if (self._state.get('block') or {}).get('reason') == 'challenge':
                    self._state['block'] = None
                    self._save()
            finally:
                self._state = None
