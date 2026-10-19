"""Development request ledger for the twitter rebuild (plan X6): every live action is recorded; a daily target is off
unless 성진 sets one for the day.

The app requests things by itself inside its tab, so nothing can cap the account's requests before they happen. What
this does: every action is written to the ledger as soon as it ends, whatever it cost. When TWITTER_DAY_TARGET is set,
an action starts only when its reservation fits what is left today, with no slack, so an overshoot stops the day by
itself; and during a contrast run, watch() reads the skill's own request log and stops the run's whole process group at
the target. Without it, check() always fits and watch() only waits.

The ledger is a TSV (date, stage, requests, note) kept outside the repository. The skill's request log is
data/protection/requests.jsonl, one JSON object per charged request batch: {"at": unix seconds, "kind": str, "n": int}.

  python3 ledger.py check LEDGER ACTION [--count N]   exit 0 when it fits, 1 when it does not
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

# 성진: 개발 중 실계정 요청 목표치 없음(X6). TWITTER_DAY_TARGET은 성진이 그날 목표를 정할 때만 쓴다
DAY_TARGET = int(os.environ['TWITTER_DAY_TARGET']) if os.environ.get('TWITTER_DAY_TARGET') else None
# Planning-session measurements (an idle minute about 5, one direct read 1); a tab opening is measured in P2 R1.
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
    """Requests written today, and on every day."""
    today = (today or date.today()).isoformat()
    rows = _rows(ledger)
    return {'today': sum(n for d, _, n in rows if d == today), 'all': sum(n for _, _, n in rows)}


def check(ledger, action, *, count=1, today=None, target=None):
    """Whether `count` actions of kind `action` may start; with a day target, the reservation must fit exactly what
    is left. target defaults to TWITTER_DAY_TARGET."""
    target = DAY_TARGET if target is None else target
    reservation = RESERVATIONS[action] * count
    used = totals(ledger, today)
    if target is None:
        return {'ok': True, 'target': None, 'reservation': reservation, 'today': used['today']}
    left = target - used['today']
    return {'ok': left >= reservation, 'target': target, 'reservation': reservation, 'today': used['today'],
            'left_day': left}


def add(ledger, stage, requests, note, *, today=None):
    """Write one finished action at once, whatever it cost."""
    path = Path(ledger)
    if not path.exists():
        path.write_text('date\tphase\trequests\tnote\n')
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


def watch(process, *, ledger, log, started_at, limit=None, poll=1.0, on_stop=None, today=None):
    """Wait for `process` (started with start_new_session=True). With a limit, stop its whole group once today's
    ledger plus what the skill logged since `started_at` reaches it; on_stop runs after the group is gone (e.g. blank
    the tab). Without one, only wait."""
    base = totals(ledger, today)['today']
    while True:
        counted = logged(log, started_at)
        if limit is not None and base + counted >= limit:
            _stop_group(process)
            if on_stop:
                on_stop()
            return {'outcome': 'budget_stop', 'counted': base + counted}
        if process.poll() is not None:
            return {'outcome': 'finished', 'counted': base + logged(log, started_at)}
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
    parser = argparse.ArgumentParser(description='Development request ledger for the twitter rebuild.')
    commands = parser.add_subparsers(dest='command', required=True)
    c = commands.add_parser('check')
    c.add_argument('ledger')
    c.add_argument('action', choices=sorted(RESERVATIONS))
    c.add_argument('--count', type=int, default=1)
    a = commands.add_parser('add')
    a.add_argument('ledger')
    a.add_argument('stage')
    a.add_argument('requests', type=int)
    a.add_argument('note')
    args = parser.parse_args(argv)
    if args.command == 'check':
        result = check(args.ledger, args.action, count=args.count)
        print(json.dumps(result))
        return 0 if result['ok'] else 1
    add(args.ledger, args.stage, args.requests, args.note)
    return 0


if __name__ == '__main__':
    sys.exit(main())
