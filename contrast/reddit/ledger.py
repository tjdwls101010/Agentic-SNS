"""Development request ledger for the reddit rebuild (plan R9): a record, not a target.

There is no daily target: Reddit's own ten-minute buckets are the natural ceiling and the skill's guard stops a bucket
until its reset. What this does instead: every action is written to the ledger as soon as it ends, and during a
contrast run watch() reads the skill's own request logs and stops the run's whole process group at the first block
signal (a rate limit, a challenge, a logged-out answer), so nothing keeps sending after Reddit pushed back.

The ledger is a TSV (date, stage, requests, note) kept outside the repository. The skill's request log is
data/protection/<aside-account>/requests.jsonl, one JSON object per charged request:
{"at": unix seconds, "bucket": str, "n": int, "outcome": str}. The outcomes that stop a run are BLOCK_OUTCOMES.

  python3 ledger.py add LEDGER STAGE REQUESTS NOTE
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

BLOCK_OUTCOMES = ('rate_limited', 'challenge', 'login_required')


def add(ledger, stage, requests, note, *, today=None):
    """Write one finished action at once, whatever it cost."""
    path = Path(ledger)
    if not path.exists():
        path.write_text('date\tstage\trequests\tnote\n')
    with path.open('a') as stream:
        stream.write(f'{(today or date.today()).isoformat()}\t{stage}\t{int(requests)}\t{note}\n')
        stream.flush()
        os.fsync(stream.fileno())


def _entries(logs, since):
    """Every log entry written at or after `since`, across the given request logs."""
    found = []
    for log in logs:
        try:
            lines = Path(log).read_text().splitlines()
        except FileNotFoundError:
            continue
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue   # a line being written
            if isinstance(entry, dict) and type(entry.get('at')) in (int, float) and entry['at'] >= since:
                found.append(entry)
    return found


def request_logs(protection):
    """The request logs under a protection directory: one per Aside account key."""
    return sorted(Path(protection).glob('*/requests.jsonl'))


def logged(logs, since):
    """Requests the skill logged at or after `since`."""
    return sum(int(entry.get('n', 1)) for entry in _entries(logs, since))


def block_signal(logs, since):
    """The first block outcome logged at or after `since`, or None."""
    for entry in sorted(_entries(logs, since), key=lambda e: e['at']):
        if entry.get('outcome') in BLOCK_OUTCOMES:
            return entry['outcome']
    return None


def watch(process, *, logs, started_at, poll=1.0):
    """Wait for `process` (started with start_new_session=True); stop its whole group at the first block signal the
    skill logged since `started_at`. `logs` is a callable returning the request logs to read (accounts can appear
    while the run goes)."""
    while True:
        signal_seen = block_signal(logs(), started_at)
        if signal_seen:
            _stop_group(process)
            return {'outcome': 'block_stop', 'signal': signal_seen, 'counted': logged(logs(), started_at)}
        if process.poll() is not None:
            return {'outcome': 'finished', 'signal': None, 'counted': logged(logs(), started_at)}
        time.sleep(poll)


def group_alive(pgid):
    """Whether any live (non-zombie) process remains in the group."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass   # macOS answers EPERM for a group holding only zombies
    listed = subprocess.run(['ps', '-o', 'stat=', '-g', str(pgid)], capture_output=True, text=True).stdout.split()
    return any(not state.startswith('Z') for state in listed)


def _stop_group(process):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        deadline = time.time() + 5
        while time.time() < deadline:
            process.poll()   # reap the leader so the group can vanish
            if not group_alive(process.pid):
                return
            time.sleep(0.05)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Development request ledger for the reddit rebuild.')
    commands = parser.add_subparsers(dest='command', required=True)
    a = commands.add_parser('add')
    a.add_argument('ledger')
    a.add_argument('stage')
    a.add_argument('requests', type=int)
    a.add_argument('note')
    args = parser.parse_args(argv)
    add(args.ledger, args.stage, args.requests, args.note)
    return 0


if __name__ == '__main__':
    sys.exit(main())
