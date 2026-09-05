"""A persisted, cumulative 30-request cap applies before every live Aside spawn."""
import json
from datetime import datetime, timezone
from pathlib import Path
import os
import pytest


@pytest.fixture(autouse=True)
def live_request_cap(monkeypatch):
    from reddit_skill import _transport
    original = _transport.run_snippet
    path = Path(os.environ.get('REDDIT_LIVE_LEDGER', Path.home() / ('.cache/reddit-skill/live-validation-' + datetime.now(timezone.utc).strftime('%Y%m%d') + '.json')))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    def guarded(name, args):
        import fcntl
        with path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(path.read_text()) if path.exists() else {'requests': 0, 'calls': []}
            cost = 1
            if state['requests'] + cost > 30:
                pytest.skip('Cumulative live 30-request guard reached; no request sent.')
            state['requests'] += cost
            state['calls'].append({'snippet': name, 'path': args.get('path'), 'after': bool(args.get('query', {}).get('after'))})
            path.write_text(json.dumps(state))
        return original(name, args)
    monkeypatch.setattr(_transport, 'run_snippet', guarded)
