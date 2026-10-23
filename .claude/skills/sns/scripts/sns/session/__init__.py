"""What the skill knows about its browser session for one platform and Aside account, under
data/<platform>/<account>/session/.

The state is split by how it may be written, so nothing written inside the account-protection lock ever needs the
session lock (the lock order everywhere is session, then protection):
- tab.json: the dedicated tab, the latest use token, the commands still using the tab (leases) and the last one
  released. Written only under the session lock (opening()); the tab is found, re-checked, opened and recorded there, so
  two commands starting together open one tab.
- ack: the time of the last tab signal already moved into account protection (only grows).
- dirty: present while the tab should have been emptied and could not be; the idle cleanup keeps trying.
- queries.json: query ids learned from the page and queries found under a new name. A cache: a lost update costs a
  relearn.
- nonce.json: how many of the skill's own requests were sent and how many the tab's timing list matched by nonce.
- viewer.json: the platform account seen last (a hint for 12 hours, never proof of who is logged in now).
Unreadable or missing state only means a new tab is opened and the bundled query ids are used, so it never blocks a
request; an unreadable tab record is reported (reset) so the result can say the session was started over.
"""
import json
import os
import secrets
import time
from contextlib import contextmanager

from sns.atomic import locked, write_json
from sns.errors import SnsError
from sns.paths import scope

VIEWER_SECONDS = 12 * 3600


def _quiet():
    return OSError()


def _save(path, value):
    try:
        write_json(path, value, _quiet)
    except OSError:
        pass  # a cache that cannot be written costs a later tab open or relearn, nothing else


def _load(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None, False
    except (OSError, ValueError, UnicodeError):
        return None, True
    return (value, False) if isinstance(value, dict) else (None, True)


class Session:
    """The browser session of one platform and Aside account."""

    def __init__(self, platform, account, deadline=None):
        self.platform, self.account, self.deadline = platform, account, deadline
        self.directory = scope(platform, account, 'session')
        self.reset = False
        self._depth = 0  # opening() is re-entrant within one process
        self._data = self._read()

    def _path(self, name):
        return self.directory / name

    def _read(self):
        empty = {'tab': None, 'token': None, 'active': {}, 'released': None}
        data, broken = _load(self._path('tab.json'))
        self.reset = broken
        if data is None:
            return empty
        return {'tab': data.get('tab') if isinstance(data.get('tab'), str) else None,
                'token': data.get('token') if isinstance(data.get('token'), str) else None,
                'active': data.get('active') if isinstance(data.get('active'), dict) else {},
                'released': data.get('released') if isinstance(data.get('released'), str) else None}

    def reload(self):
        """Read the tab record again (inside opening(): another process may have opened the tab meanwhile)."""
        self._data = self._read()
        return self

    def _store(self):
        _save(self._path('tab.json'), self._data)
        self.reset = False

    @contextmanager
    def opening(self):
        """The lock under which the tab record is read and written: the dedicated tab is found, re-checked, opened and
        recorded, leases change, and an idle tab is emptied. Waited for until the deadline."""
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return

        def late():
            return SnsError('failed', 'The command reached its time limit while another command was opening the '
                                      'browser tab.', 'Run the command again.', reason='time_limit')
        with locked(self._path('tab.lock'), self.deadline, late):
            self._depth = 1
            try:
                yield
            finally:
                self._depth = 0

    # --- the tab record (under opening()) ------------------------------------------------------------------------

    @property
    def tab(self):
        return self._data['tab']

    @property
    def token(self):
        return self._data['token']

    def set_tab(self, target_id):
        with self.opening():
            self._data = {**self._read(), 'tab': target_id}
            self._store()

    def touch(self):
        """Mark a new use of the tab by this process; returns its token. While a command holds a token it is active,
        and no idle cleanup empties the tab."""
        token = f'{time.time():.3f}-{secrets.token_hex(4)}'
        with self.opening():
            current = self._read()
            current['active'] = {**self._alive(current['active']), token: os.getpid()}
            self._data = {**current, 'token': token}
            self._store()
        return token

    def release(self, token):
        """The command that holds `token` is done with the tab: it is no longer active and is the last one released."""
        with self.opening():
            current = self._read()
            current['active'] = {k: v for k, v in self._alive(current['active']).items() if k != token}
            self._data = {**current, 'released': token}
            self._store()

    @staticmethod
    def _alive(active):
        alive = {}
        for token, pid in active.items():
            try:
                os.kill(int(pid), 0)
                alive[token] = pid
            except PermissionError:
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
        """The time of the last tab signal already moved into account protection."""
        data, _ = _load(self._path('ack.json'))
        value = (data or {}).get('at')
        return value if type(value) in (int, float) else 0

    def acknowledge(self, moment):
        if type(moment) in (int, float) and moment > self.ack:
            _save(self._path('ack.json'), {'at': moment})

    @property
    def dirty(self):
        """The tab should have been emptied and could not be: the idle cleanup keeps trying."""
        return self._path('dirty').exists()

    def set_dirty(self, value):
        try:
            if value:
                self._path('dirty').write_text('1')
            else:
                self._path('dirty').unlink(missing_ok=True)
        except OSError:
            pass

    def _queries(self):
        data, _ = _load(self._path('queries.json'))
        data = data or {}
        return {'queries': data.get('queries') if isinstance(data.get('queries'), dict) else {},
                'renames': data.get('renames') if isinstance(data.get('renames'), dict) else {}}

    def query(self, name):
        """The query id (and provider values) learned for `name`, or None."""
        value = self._queries()['queries'].get(name)
        return value if isinstance(value, dict) and isinstance(value.get('doc_id'), str) else None

    def learn(self, name, doc_id, flags=None):
        """Remember a query id the live page or a learning read gave, with its provider values when known."""
        data = self._queries()
        previous = data['queries'].get(name) if isinstance(data['queries'].get(name), dict) else {}
        entry = {'doc_id': doc_id, 'flags': flags if flags is not None else previous.get('flags'),
                 'learned_at': time.time()}
        if previous.get('doc_id') == doc_id and previous.get('flags') == entry['flags']:
            return
        data['queries'][name] = entry
        _save(self._path('queries.json'), data)

    def renamed(self, key):
        """The current name a renamed query was found under, or None."""
        value = self._queries()['renames'].get(key)
        return value if isinstance(value, str) else None

    def rename(self, key, name):
        data = self._queries()
        data['renames'][key] = name
        _save(self._path('queries.json'), data)

    @property
    def nonce(self):
        data, _ = _load(self._path('nonce.json'))
        data = data or {}
        return {key: data.get(key) if type(data.get(key)) is int else 0 for key in ('sent', 'matched')}

    def note_nonce(self, sent, matched):
        """Add one command's own requests and the timing entries matched to them by their nonce."""
        if not sent and not matched:
            return
        data = self.nonce
        _save(self._path('nonce.json'), {'sent': data['sent'] + sent, 'matched': data['matched'] + matched,
                                         'at': time.time()})

    def viewer_hint(self):
        """The platform account seen within the last 12 hours ({viewer, extra…}), or None. A hint, not proof."""
        data, _ = _load(self._path('viewer.json'))
        if not data or not isinstance(data.get('viewer'), str) or type(data.get('seen_at')) not in (int, float) \
                or time.time() - data['seen_at'] > VIEWER_SECONDS:
            return None
        return data

    def remember_viewer(self, viewer, **extra):
        if isinstance(viewer, str) and viewer:
            _save(self._path('viewer.json'), {'viewer': viewer, **extra, 'seen_at': time.time()})
