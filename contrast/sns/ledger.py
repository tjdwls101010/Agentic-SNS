"""A record of live development requests, and the safety stop of a contrast run (maintenance code).

There is no daily target (decision S2): the record says what each live action cost, and watch() reads the skill's own
request logs during a contrast run and stops the run's whole process group at the first block signal (a rate limit, a
checkpoint, a challenge, a lock, a network block, a login wall), so nothing keeps sending after a platform pushed back.

The record is a TSV (date, stage, requests, note) kept outside the repository. The skill's request log is
data/<platform>/<aside account>/protection/requests.jsonl: one JSON line per request when it is sent (n 1, outcome
sent) and one when its answer is classified (n 0, outcome ok / rate_limited / checkpoint / …).

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

BLOCK_OUTCOMES = ('rate_limited', 'challenge', 'checkpoint', 'account_locked', 'network_blocked', 'login_required')


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
    found = []
    for log in logs:
        try:
            lines = Path(log).read_text().splitlines()
        except (FileNotFoundError, NotADirectoryError):
            continue
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue  # a line being written
            if isinstance(entry, dict) and type(entry.get('at')) in (int, float) and entry['at'] >= since:
                found.append(entry)
    return found


def request_logs(data_dir, platforms=None):
    """Every request log under a data directory: data/<platform>/<account>/protection/requests.jsonl."""
    root = Path(data_dir)
    names = platforms or [p.name for p in root.iterdir() if p.is_dir() and p.name not in ('handles', 'images')] \
        if root.exists() else []
    return sorted(log for name in names for log in (root / name).glob('*/protection/requests.jsonl'))


def logged(logs, since):
    """Requests the skill sent at or after `since`."""
    return sum(int(entry.get('n', 1)) for entry in _entries(logs, since)
               if entry.get('outcome') in ('sent', 'cancelled', 'seen') or 'outcome' not in entry)


def block_signal(logs, since):
    """The first block outcome logged at or after `since`, or None."""
    for entry in sorted(_entries(logs, since), key=lambda e: e['at']):
        if entry.get('outcome') in BLOCK_OUTCOMES:
            return entry['outcome']
    return None


def watch(process, *, logs, started_at, poll=1.0, on_signal=None):
    """Wait for `process` (started with start_new_session=True); stop its whole group at the first block signal the
    skill logged since `started_at`. `logs` returns the request logs to read; on_signal(signal) runs right after the
    stop."""
    while True:
        seen = block_signal(logs(), started_at)
        if seen:
            stop_group(process)
            if on_signal:
                on_signal(seen)
            return {'outcome': 'block_stop', 'signal': seen, 'counted': logged(logs(), started_at)}
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
        pass  # macOS answers EPERM for a group holding only zombies
    listed = subprocess.run(['ps', '-o', 'stat=', '-g', str(pgid)], capture_output=True, text=True).stdout.split()
    return any(not state.startswith('Z') for state in listed)


def stop_group(process):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        deadline = time.time() + 5
        while time.time() < deadline:
            process.poll()  # reap the leader so the group can vanish
            if not group_alive(process.pid):
                return
            time.sleep(0.05)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Development request record.')
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
