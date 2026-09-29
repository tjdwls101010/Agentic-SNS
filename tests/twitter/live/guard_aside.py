#!/usr/bin/env python3
"""Live Aside guard: reserve one slot in a locked ledger, refuse before sending when a cap is reached, then run the real Aside.

TWITTER_LIVE_TOTAL (default 150) caps every attempt recorded in TWITTER_LIVE_LEDGER, whatever the snippet and whether it later fails; TWITTER_LIVE_WINDOW (default 50/600) caps attempts within the trailing seconds. TWITTER_REAL_ASIDE is the Aside to run. A ledger from the earlier per-kind guard counts its recorded attempts toward the total.
"""
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

path = Path(os.environ.get('TWITTER_LIVE_LEDGER', '/tmp/twitter-skill-live-ledger.json'))
total = int(os.environ.get('TWITTER_LIVE_TOTAL', '150'))
limit, seconds = (int(part) for part in os.environ.get('TWITTER_LIVE_WINDOW', '50/600').split('/'))
code = sys.argv[-1]
kind = code.split('// twitter-snippet: ', 1)[1].split('\n', 1)[0].strip() if '// twitter-snippet: ' in code else 'unknown'
with path.open('a+') as stream:
    fcntl.flock(stream, fcntl.LOCK_EX)
    stream.seek(0)
    data = json.loads(stream.read() or '{}')
    if 'total' not in data:
        data = dict(total=sum(v for v in data.values() if isinstance(v, int)), times=[], kinds=data)
    now = time.time()
    recent = [t for t in data['times'] if t > now - seconds]
    if data['total'] >= total:
        sys.exit(f'Live request allowance exhausted: {data["total"]}/{total} attempts in this ledger.')
    if len(recent) >= limit:
        sys.exit(f'Live request window is full: {len(recent)}/{limit} attempts in {seconds} s.')
    data.update(total=data['total'] + 1, times=[*recent, now])
    data['kinds'][kind] = data['kinds'].get(kind, 0) + 1
    stream.seek(0)
    stream.truncate()
    json.dump(data, stream)
result = subprocess.run([os.environ.get('TWITTER_REAL_ASIDE', 'aside'), *sys.argv[1:]], capture_output=True)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.exit(result.returncode)
