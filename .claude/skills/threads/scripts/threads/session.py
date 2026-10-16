"""What the skill knows about its browser session: the dedicated tab, the latest command's use token, and query ids
learned from the tab.

One file per Aside account (data/session/<account>.json). This is a cache: unreadable or missing state only means a
new tab is opened and the bundled query ids are used, so it never blocks a request; an unreadable file is reported
(reset) so the result can say the session was started over. Opening a tab happens under a per-account lock, so two
commands starting together open one tab: the second re-reads the session inside the lock and finds the first's tab.
"""
import fcntl
import json
import os
import secrets
import tempfile
import time
from contextlib import contextmanager

from threads.paths import state_dir


class Session:
    def __init__(self, account_key):
        self.account_key = account_key
        self.reset = False
        self._depth = 0  # opening() is re-entrant within one process: the lock order is always session, then guard
        self._data = self._load()

    def _path(self):
        return state_dir('session') / f'{self.account_key}.json'

    def _load(self):
        empty = {'tab': None, 'token': None, 'ack': 0, 'renames': {}, 'active': {}, 'released': None, 'dirty': False,
                 'queries': {}}
        try:
            data = json.loads(self._path().read_text())
        except FileNotFoundError:
            self.reset = False
            return empty
        except (OSError, ValueError):
            self.reset = True
            return empty
        if not isinstance(data, dict) or not isinstance(data.get('queries', {}), dict):
            self.reset = True
            return empty
        self.reset = False
        return {'tab': data.get('tab') if isinstance(data.get('tab'), str) else None,
                'token': data.get('token') if isinstance(data.get('token'), str) else None,
                'ack': data.get('ack') if type(data.get('ack')) in (int, float) else 0,
                'renames': data.get('renames') if isinstance(data.get('renames'), dict) else {},
                'active': data.get('active') if isinstance(data.get('active'), dict) else {},
                'released': data.get('released') if isinstance(data.get('released'), str) else None,
                'dirty': data.get('dirty') is True,
                'queries': data.get('queries', {})}

    def reload(self):
        """Read the file again (inside opening(): another process may have opened the tab meanwhile)."""
        self._data = self._load()
        return self

    def _save(self):
        try:
            directory = state_dir('session')
            with tempfile.NamedTemporaryFile('w', dir=directory, prefix='.session', delete=False) as stream:
                json.dump(self._data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(stream.name, 0o600)
            os.replace(stream.name, directory / f'{self.account_key}.json')
            self.reset = False
        except OSError:
            pass  # a cache that cannot be written costs a later tab open, nothing else

    @contextmanager
    def opening(self):
        """The per-account lock under which the dedicated tab is found, re-checked, opened and recorded, and under
        which an idle tab is blanked."""
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        try:
            lock = open(state_dir('session') / f'{self.account_key}.lock', 'a')
        except OSError:
            yield  # without a writable session directory there is nothing to coordinate through
            return
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._depth = 1
            yield
        finally:
            self._depth = 0
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()

    @property
    def tab(self):
        return self._data['tab']

    @property
    def token(self):
        return self._data['token']

    def set_tab(self, target_id):
        self._data = {**self._load(), 'tab': target_id}
        self._save()

    def touch(self):
        """Mark a new use of the tab by this process; returns its token. While a command holds a token it is active,
        and no idle blanker empties the tab."""
        token = f'{time.time():.3f}-{secrets.token_hex(4)}'
        with self.opening():
            current = self._load()
            current['active'] = {**self._alive(current['active']), token: os.getpid()}
            self._data = {**current, 'token': token}
            self._save()
        return token

    def release(self, token):
        """The command that holds `token` is done with the tab: it is no longer active and is the last one released."""
        with self.opening():
            current = self._load()
            current['active'] = {k: v for k, v in self._alive(current['active']).items() if k != token}
            self._data = {**current, 'released': token}
            self._save()

    @property
    def dirty(self):
        """The tab should have been emptied (a block was recorded) and could not be: the idle blanker keeps trying."""
        return self._data['dirty']

    def set_dirty(self, value):
        with self.opening():
            self._data = {**self._load(), 'dirty': bool(value)}
            self._save()

    @staticmethod
    def _alive(active):
        alive = {}
        for token, pid in active.items():
            try:
                os.kill(int(pid), 0)
                alive[token] = pid
            except (OSError, ValueError, TypeError):
                pass  # a command that died without releasing does not hold the tab
        return alive

    @property
    def active(self):
        """Tokens of commands still running that use the tab."""
        return self._alive(self._data['active'])

    @property
    def released(self):
        return self._data['released']

    @property
    def ack(self):
        """The time of the last tab signal already moved into account protection; the tab drops signals up to it."""
        return self._data['ack']

    def acknowledge(self, moment):
        if type(moment) in (int, float) and moment > self._data['ack']:
            self._data = {**self._load(), 'ack': moment}
            self._save()

    def renamed(self, key):
        """The current name a renamed query was found under, or None."""
        value = self._data['renames'].get(key)
        return value if isinstance(value, str) else None

    def rename(self, key, name):
        current = self._load()
        current['renames'][key] = name
        self._data = current
        self._save()

    def query(self, name):
        """The query id (and provider values) learned for `name`, or None."""
        value = self._data['queries'].get(name)
        return value if isinstance(value, dict) and isinstance(value.get('doc_id'), str) else None

    def learn(self, name, doc_id, flags=None):
        """Remember a query id the live tab or a learning read gave, with its provider values when known."""
        current = self._load()
        previous = current['queries'].get(name) if isinstance(current['queries'].get(name), dict) else {}
        entry = {'doc_id': doc_id, 'flags': flags if flags is not None else previous.get('flags'), 'learned_at': time.time()}
        if previous.get('doc_id') == doc_id and previous.get('flags') == entry['flags']:
            return
        current['queries'][name] = entry
        self._data = current
        self._save()
