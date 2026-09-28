"""Record and replay Aside responses for model scenario runs, keyed by what the CLI actually asked for.

The fake Aside hands a call here when THREADS_RECORD or THREADS_REPLAY names a snapshot directory:

  page|<path?query>
  graphql|<name>|<doc_id>|<canonical JSON of the variables without __relay_internal__ flags>
  capture|<seed URL>|<sorted targets>|<actions JSON>|<request_budget>

Recording serves a key already in the snapshot from the snapshot and sends only new keys to the real Aside
(THREADS_REAL_ASIDE, normally the live bridge, whose ledger caps the live requests), so one snapshot stays one moment
of Threads. Replay never makes up a response: an unrecorded key fails the call with exit 97, prints `harness_miss` on
stderr and is appended to THREADS_HARNESS_LOG, and a run with a miss is invalid.
"""
import fcntl
import json
import os
import re
import subprocess
import sys
from pathlib import Path

MISS = 97


def key(snippet, args):
    if snippet == 'page':
        return 'page|' + args['path']
    if snippet == 'graphql':
        variables = {k: v for k, v in (args.get('variables') or {}).items() if not k.startswith('__relay_internal__')}
        return '|'.join(['graphql', args['name'], args['doc_id'],
                         json.dumps(variables, sort_keys=True, separators=(',', ':'), ensure_ascii=False)])
    return '|'.join(['capture', args['url'], ','.join(sorted(args['targets'])),
                     json.dumps(args.get('actions'), sort_keys=True), str(args['request_budget'])])


def load(snapshot):
    path = Path(snapshot) / 'responses.ndjson'
    return {row['key']: row for row in map(json.loads, path.read_text().splitlines())} if path.exists() else {}


def serve(row):
    sys.stdout.write(row['stdout'])
    sys.stderr.write(row.get('stderr', ''))
    return row['exit']


def handle(argv, snippet, args):
    wanted = key(snippet, args)
    if os.environ.get('THREADS_REPLAY'):
        row = load(os.environ['THREADS_REPLAY']).get(wanted)
        if row is not None:
            return serve(row)
        print('harness_miss ' + wanted, file=sys.stderr)
        log = os.environ.get('THREADS_HARNESS_LOG')
        if log:
            with open(log, 'a') as stream:
                stream.write(json.dumps({'harness_miss': wanted}) + '\n')
        return MISS
    snapshot = Path(os.environ['THREADS_RECORD'])
    snapshot.mkdir(parents=True, exist_ok=True)
    with (snapshot / 'responses.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        row = load(snapshot).get(wanted)
        if row is None:
            # The real Aside (or the live bridge) must not see the harness variables, or it would hand the call back.
            forward = {k: v for k, v in os.environ.items() if k not in ('THREADS_RECORD', 'THREADS_REPLAY')}
            done = subprocess.run([os.environ['THREADS_REAL_ASIDE'], *argv[1:]], capture_output=True, text=True,
                                  timeout=130, env=forward)
            row = {'key': wanted, 'stdout': done.stdout, 'stderr': done.stderr[-2000:], 'exit': done.returncode}
            # A failed live call (the ledger's cap, a lost connection) stays unrecorded, so it can be tried again.
            if done.returncode == 0:
                with (snapshot / 'responses.ndjson').open('a') as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    return serve(row)


def main():
    """Run as the fake Aside's delegate: the same argv the CLI gave the fake."""
    source = sys.argv[-1]
    args = json.JSONDecoder().raw_decode(source.removeprefix('const ARGS = '))[0]
    snippet = re.search(r'// threads-snippet: (\w+)', source)[1]
    log = os.environ.get('THREADS_FAKE_LOG')
    if log:
        with open(log, 'a') as stream:
            stream.write(json.dumps({'snippet': snippet, 'key': key(snippet, args), 'name': args.get('name'),
                                     'path': args.get('path')}, ensure_ascii=False) + '\n')
    return handle(sys.argv, snippet, args)


if __name__ == '__main__':
    sys.exit(main())
