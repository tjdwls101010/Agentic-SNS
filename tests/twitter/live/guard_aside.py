#!/usr/bin/env python3
"""Persistent cumulative live guard: API<=40; refresh verification<=2, separately."""
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

path = Path(os.environ.get('TWITTER_LIVE_LEDGER', '/tmp/twitter-skill-live-ledger.json'))
code = sys.argv[-1]
kind = 'graphql' if '// twitter-snippet: graphql' in code else 'auxiliary'
if os.environ.get('TWITTER_LIVE_REFRESH') == '1' and kind == 'graphql':
    kind = 'refresh_api'
with path.open('a+') as stream:
    fcntl.flock(stream, fcntl.LOCK_EX)
    stream.seek(0)
    data = json.loads(stream.read() or '{}')
    if data.get(kind, 0) >= {'graphql': 40, 'refresh_api': 2, 'auxiliary': 20}[kind]:
        sys.exit('Live request allowance exhausted')
    data[kind] = data.get(kind, 0) + 1
    stream.seek(0)
    stream.truncate()
    json.dump(data, stream)
result = subprocess.run([os.environ.get('TWITTER_REAL_ASIDE', 'aside'), *sys.argv[1:]], capture_output=True)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.exit(result.returncode)
