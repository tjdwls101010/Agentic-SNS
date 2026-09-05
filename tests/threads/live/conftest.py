"""Persisted cumulative live cap; every attempted HTTP request spends one slot."""
import fcntl
import json
import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def request_cap(monkeypatch):
    from threads_skill import _transport
    original = _transport.run_snippet
    path = Path(os.environ.get('THREADS_LIVE_LEDGER', Path.home() / '.cache/threads-skill/live-validation.json'))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    def guarded(name, args):
        with path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(path.read_text()) if path.exists() else {'requests': 0, 'calls': []}
            if state['requests'] >= 30:
                pytest.fail('Cumulative live 30-request guard reached; no request sent.')
            state['requests'] += 1
            state['calls'].append({'snippet': name, 'path': args.get('path'), 'operation': args.get('name'),
                                   'after': bool((args.get('variables') or {}).get('after'))})
            path.write_text(json.dumps(state))
            path.chmod(0o600)
        return original(name, args)
    monkeypatch.setattr(_transport, 'run_snippet', guarded)
