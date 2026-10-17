"""Development request budget for the threads rebuild (plan T9): targets, not guarantees.

The app requests things by itself inside its tab, so nothing can cap the account's requests before they happen. What
this does instead: an action starts only when its reservation fits what is left today (300) and, for live recon
stages (P2 ...), what is left of the recon allowance (100), with no slack; every action is written to the ledger as
soon as it ends, overshoot included, so an overshoot stops the day by itself. During a contrast run, watch() reads the
skill's own request log and stops the run's whole process group at the day's target.

The ledger is a TSV (date, stage, requests, note) kept outside the repository. The skill's request log is
data/protection/requests.jsonl, one JSON object per charged request batch: {"at": unix seconds, "kind": str, "n": int}.

  python3 ledger.py check LEDGER ACTION --stage STAGE [--count N]   exit 0 when it fits, 1 when it does not
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

# 성진: 하루 목표 300(T9). THREADS_DAY_TARGET은 성진이 그날 목표를 바꿀 때만 쓴다(T17)
DAY_TARGET = int(os.environ.get('THREADS_DAY_TARGET') or 300)
RECON_TARGET = 100
# Measured in the planning session (opening a tab 38, a screen move 22, an idle minute a few, one direct read 1-3).
RESERVATIONS = {'tab_open': 40, 'navigation': 30, 'direct': 3, 'idle': 5}


def _rows(ledger):
    try:
        lines = Path(ledger).read_text().splitlines()[1:]
    except FileNotFoundError:
        return []
    rows = []
    for line in lines:
        day, stage, requests, *_ = line.split('\t') + ['']
        rows.append((day, stage, int(requests)))
    return rows


def totals(ledger, today=None):
    """Requests written today, and requests written by recon stages (P2 ...) on any day."""
    today = (today or date.today()).isoformat()
    rows = _rows(ledger)
    return {'today': sum(n for d, _, n in rows if d == today),
            'recon': sum(n for _, s, n in rows if s.startswith('P2'))}


def check(ledger, action, *, stage, count=1, today=None):
    """Whether `count` actions of kind `action` may start for `stage`; the reservation must fit exactly what is left."""
    reservation = RESERVATIONS[action] * count
    used = totals(ledger, today)
    left = {'day': DAY_TARGET - used['today']}
    if stage.startswith('P2'):
        left['recon'] = RECON_TARGET - used['recon']
    short = [name for name, value in left.items() if value < reservation]
    return {'ok': not short, 'limit': short[0] if short else None, 'reservation': reservation,
            **{'left_' + name: value for name, value in left.items()}}


def add(ledger, stage, requests, note, *, today=None):
    """Write one finished action at once, whatever it cost."""
    path = Path(ledger)
    if not path.exists():
        path.write_text('date\tstage\trequests\tnote\n')
    with path.open('a') as stream:
        stream.write(f'{(today or date.today()).isoformat()}\t{stage}\t{int(requests)}\t{note}\n')
        stream.flush()
        os.fsync(stream.fileno())


def logged(log, since):
    """Requests the skill logged at or after `since`."""
    try:
        lines = Path(log).read_text().splitlines()
    except FileNotFoundError:
        return 0
    total = 0
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue   # a line being written
        if isinstance(entry, dict) and entry.get('at', 0) >= since:
            total += int(entry.get('n', 1))
    return total


def watch(process, *, ledger, log, started_at, limit, poll=1.0, on_stop=None, today=None):
    """Wait for `process` (started with start_new_session=True); stop its whole group once today's ledger plus what the
    skill logged since `started_at` reaches `limit`. on_stop runs after the group is gone (e.g. blank the tab)."""
    base = totals(ledger, today)['today']
    while True:
        counted = logged(log, started_at)
        if base + counted >= limit:
            _stop_group(process)
            if on_stop:
                on_stop()
            return {'outcome': 'budget_stop', 'counted': base + counted}
        if process.poll() is not None:
            return {'outcome': 'finished', 'counted': base + counted}
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
    parser = argparse.ArgumentParser(description='Development request budget for the threads rebuild.')
    commands = parser.add_subparsers(dest='command', required=True)
    c = commands.add_parser('check')
    c.add_argument('ledger')
    c.add_argument('action', choices=sorted(RESERVATIONS))
    c.add_argument('--stage', required=True)
    c.add_argument('--count', type=int, default=1)
    a = commands.add_parser('add')
    a.add_argument('ledger')
    a.add_argument('stage')
    a.add_argument('requests', type=int)
    a.add_argument('note')
    args = parser.parse_args(argv)
    if args.command == 'check':
        result = check(args.ledger, args.action, stage=args.stage, count=args.count)
        print(json.dumps(result))
        return 0 if result['ok'] else 1
    add(args.ledger, args.stage, args.requests, args.note)
    return 0


if __name__ == '__main__':
    sys.exit(main())
