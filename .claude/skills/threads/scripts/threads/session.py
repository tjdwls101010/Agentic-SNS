"""What the skill knows about its browser session: the dedicated tab, and query ids learned from it.

One file per Aside account (data/session/<account>.json). This is a cache: unreadable or missing state only means a
new tab is opened and the bundled query ids are used, so it never blocks a request.
"""
import json
import os
import tempfile
import time

from threads.paths import state_dir


class Session:
    def __init__(self, account_key):
        self.account_key = account_key
        self._data = self._load()

    def _path(self):
        return state_dir('session') / f'{self.account_key}.json'

    def _load(self):
        try:
            data = json.loads(self._path().read_text())
            if isinstance(data, dict) and isinstance(data.get('queries', {}), dict):
                return {'tab': data.get('tab') if isinstance(data.get('tab'), str) else None,
                        'queries': data.get('queries', {})}
        except (OSError, ValueError):
            pass
        return {'tab': None, 'queries': {}}

    def _save(self):
        try:
            directory = state_dir('session')
            with tempfile.NamedTemporaryFile('w', dir=directory, prefix='.session', delete=False) as stream:
                json.dump(self._data, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(stream.name, 0o600)
            os.replace(stream.name, directory / f'{self.account_key}.json')
        except OSError:
            pass  # a cache that cannot be written costs a later tab open, nothing else

    @property
    def tab(self):
        return self._data['tab']

    def set_tab(self, target_id):
        self._data = {**self._load(), 'tab': target_id}
        self._save()

    def query(self, name):
        """The query id (and provider flags) learned for `name`, or None."""
        value = self._data['queries'].get(name)
        return value if isinstance(value, dict) and isinstance(value.get('doc_id'), str) else None

    def learn(self, name, doc_id, flags=None):
        """Remember a query id the live page used, with its provider flags when the page gave them."""
        current = self._load()
        previous = current['queries'].get(name) if isinstance(current['queries'].get(name), dict) else {}
        entry = {'doc_id': doc_id, 'flags': flags if flags is not None else previous.get('flags'), 'learned_at': time.time()}
        if previous.get('doc_id') == doc_id and previous.get('flags') == entry['flags']:
            return
        current['queries'][name] = entry
        self._data = current
        self._save()
