#!/usr/bin/env python3
"""Synthetic, sequence-aware external Aside stand-in for complete CLI journeys."""
import json
import os
from pathlib import Path
import sys

source = sys.argv[4]
args = json.loads(source.split('const ARGS = ', 1)[1].split(';\n', 1)[0])
log = Path(os.environ['REDDIT_FAKE_LOG'])
history = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
with log.open('a') as stream:
    stream.write(json.dumps(args) + '\n')
scenarios = json.loads(Path(os.environ['REDDIT_CLI_RESPONSES']).read_text())
path = args.get('path', args.get('url'))
responses = scenarios[path]
if isinstance(responses, list):
    index = sum(item.get('path', item.get('url')) == path for item in history)
    response = responses[min(index, len(responses) - 1)]
else:
    response = responses
print(json.dumps({'status': response.get('status', 200), 'url': 'https://www.reddit.com' + path,
                  'body': json.dumps(response['body']), 'ratelimit': {'remaining': '90', 'used': '10', 'reset': '600'}}))
