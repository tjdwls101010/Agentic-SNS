"""What the skill knows about its browser session, per Aside account, under data/session/.

The state is split by how it may be written, so nothing written inside the account-protection lock ever needs the
session lock (the lock order everywhere is session, then protection):
- <account>.json: the dedicated tab, the latest use token, the commands still using the tab (leases) and the last one
  released. Written only under the session lock (opening()); found, re-checked, opened and recorded there, so two
  commands starting together open one tab.
- <account>.ack: the time of the last tab signal already moved into account protection (only grows).
- <account>.dirty: present while the tab should have been emptied after a block and could not be.
- <account>.queries.json: query ids learned from the tab and renamed queries. A cache: a lost update costs a relearn.
Unreadable or missing state only means a new tab is opened and the bundled query ids are used, so it never blocks a
request; an unreadable tab record is reported (reset) so the result can say the session was started over.
"""
import fcntl
import json
import os
import secrets
import tempfile
import time
from contextlib import contextmanager

from threads.paths import state_dir


def _write(path, text):
    try:
        with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.' + path.name, delete=False) as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(stream.name, 0o600)
        os.replace(stream.name, path)
    except OSError:
        pass  # a cache that cannot be written costs a later tab open or relearn, nothing else


class Session:
    def __init__(self, account_key):
        self.account_key = account_key
        self.reset = False
        self._depth = 0  # opening() is re-entrant within one process
        self._data = self._load()

    def _path(self, suffix='.json'):
        return state_dir('session') / f'{self.account_key}{suffix}'

    def _load(self):
        empty = {'tab': None, 'token': None, 'active': {}, 'released': None}
        try:
            data = json.loads(self._path().read_text())
        except FileNotFoundError:
            self.reset = False
            return empty
        except (OSError, ValueError):
            self.reset = True
            return empty
        if not isinstance(data, dict):
            self.reset = True
            return empty
        self.reset = False
        return {'tab': data.get('tab') if isinstance(data.get('tab'), str) else None,
                'token': data.get('token') if isinstance(data.get('token'), str) else None,
                'active': data.get('active') if isinstance(data.get('active'), dict) else {},
                'released': data.get('released') if isinstance(data.get('released'), str) else None}

    def reload(self):
        """Read the tab record again (inside opening(): another process may have opened the tab meanwhile)."""
        self._data = self._load()
        return self

    def _save(self):
        _write(self._path(), json.dumps(self._data))
        self.reset = False

    @contextmanager
    def opening(self):
        """The per-account lock under which the tab record is read and written: the dedicated tab is found,
        re-checked, opened and recorded, leases change, and an idle tab is emptied."""
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

    # --- the tab record (under opening()) --------------------------------------------------------------------

    @property
    def tab(self):
        return self._data['tab']

    @property
    def token(self):
        return self._data['token']

    def set_tab(self, target_id):
        with self.opening():
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

    # --- written without the session lock (safe inside the protection lock) -----------------------------------

    @property
    def ack(self):
        """The time of the last tab signal already moved into account protection; the tab drops signals up to it."""
        try:
            value = json.loads(self._path('.ack').read_text())
        except (OSError, ValueError):
            return 0
        return value if type(value) in (int, float) else 0

    def acknowledge(self, moment):
        if type(moment) in (int, float) and moment > self.ack:
            _write(self._path('.ack'), json.dumps(moment))

    @property
    def dirty(self):
        """The tab should have been emptied (a block was recorded) and could not be: the idle blanker keeps trying."""
        return self._path('.dirty').exists()

    def set_dirty(self, value):
        try:
            if value:
                self._path('.dirty').write_text('1')
            else:
                self._path('.dirty').unlink(missing_ok=True)
        except OSError:
            pass

    def _queries(self):
        try:
            data = json.loads(self._path('.queries.json').read_text())
        except (OSError, ValueError):
            return {'queries': {}, 'renames': {}}
        if not isinstance(data, dict):
            return {'queries': {}, 'renames': {}}
        return {'queries': data.get('queries') if isinstance(data.get('queries'), dict) else {},
                'renames': data.get('renames') if isinstance(data.get('renames'), dict) else {}}

    def renamed(self, key):
        """The current name a renamed query was found under, or None."""
        value = self._queries()['renames'].get(key)
        return value if isinstance(value, str) else None

    def rename(self, key, name):
        data = self._queries()
        data['renames'][key] = name
        _write(self._path('.queries.json'), json.dumps(data))

    def query(self, name):
        """The query id (and provider values) learned for `name`, or None."""
        value = self._queries()['queries'].get(name)
        return value if isinstance(value, dict) and isinstance(value.get('doc_id'), str) else None

    def learn(self, name, doc_id, flags=None):
        """Remember a query id the live tab or a learning read gave, with its provider values when known."""
        data = self._queries()
        previous = data['queries'].get(name) if isinstance(data['queries'].get(name), dict) else {}
        entry = {'doc_id': doc_id, 'flags': flags if flags is not None else previous.get('flags'), 'learned_at': time.time()}
        if previous.get('doc_id') == doc_id and previous.get('flags') == entry['flags']:
            return
        data['queries'][name] = entry
        _write(self._path('.queries.json'), json.dumps(data))
