#!/usr/bin/env python3
"""Cumulative live request guard for separate CLI usability-review processes."""
import fcntl
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sys

ledger = Path(os.environ.get('REDDIT_LIVE_LEDGER', Path.home() / ('.cache/reddit-skill/live-validation-' + datetime.now(timezone.utc).strftime('%Y%m%d') + '.json')))
ledger.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
with ledger.with_suffix('.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    state = json.loads(ledger.read_text()) if ledger.exists() else {'requests': 0, 'calls': []}
    if state['requests'] >= 30:
        print('Live validation cap reached; no request sent.', file=sys.stderr)
        sys.exit(77)
    state['requests'] += 1
    state['calls'].append({'snippet': 'usability-cli', 'path': None, 'after': False})
    ledger.write_text(json.dumps(state))
binary = shutil.which('aside')
if binary is None or Path(binary).resolve() == Path(__file__).resolve():
    sys.exit(77)
os.execv(binary, [binary, *sys.argv[1:]])
