"""The development budget controller (contrast/threads/ledger.py): it refuses an action whose reservation does not
fit what is left, and its watch stops a whole process group once the day's target is reached."""
import json
import subprocess
import time
from datetime import date

from contrast.threads import ledger

TODAY = date(2026, 10, 17)


def write_ledger(path, rows):
    path.write_text('date\tstage\trequests\tnote\n' + ''.join(f'{d}\t{s}\t{n}\t{m}\n' for d, s, n, m in rows))
    return path


def test_reservation_larger_than_what_is_left_is_refused(tmp_path):
    path = write_ledger(tmp_path / 'l.tsv', [('2026-10-16', 'P2 R1', 90, 'yesterday'),
                                             ('2026-10-17', 'P6 contrast', 200, ''), ('2026-10-17', 'P2 R2', 60, '')])
    # today 260 of 300 → 40 left; recon 150 of 100 → nothing left for P2
    assert ledger.check(path, 'tab_open', stage='P6', today=TODAY)['ok'] is True        # 40 fits 40 exactly
    assert ledger.check(path, 'navigation', stage='P6', count=2, today=TODAY)['ok'] is False   # 60 > 40
    refused = ledger.check(path, 'direct', stage='P2 R3', today=TODAY)
    assert refused['ok'] is False and refused['limit'] == 'recon'


def test_recon_and_day_both_bound_recon(tmp_path):
    path = write_ledger(tmp_path / 'l.tsv', [('2026-10-17', 'P2 R1', 97, '')])
    assert ledger.check(path, 'direct', stage='P2 R2', today=TODAY)['ok'] is True       # 3 fits 3
    assert ledger.check(path, 'idle', stage='P2 R2', today=TODAY)['ok'] is False        # 5 > 3


def test_overshoot_is_recorded_and_stops_the_day(tmp_path):
    path = write_ledger(tmp_path / 'l.tsv', [('2026-10-17', 'P6 contrast', 290, '')])
    ledger.add(path, 'P6 contrast a1-t5', 25, 'over the target', today=TODAY)
    lines = path.read_text().splitlines()
    assert lines[-1] == '2026-10-17\tP6 contrast a1-t5\t25\tover the target'
    assert ledger.check(path, 'direct', stage='P6', today=TODAY)['ok'] is False


def test_watch_stops_the_process_group_at_the_target(tmp_path):
    path = write_ledger(tmp_path / 'l.tsv', [(TODAY.isoformat(), 'P6 contrast', 290, '')])
    log = tmp_path / 'requests.jsonl'
    log.write_text(json.dumps({'at': time.time() - 3600, 'kind': 'query', 'n': 50}) + '\n')   # before the run: ignored
    child = subprocess.Popen(['sh', '-c', 'sleep 60 & sleep 60'], start_new_session=True)
    stopped = []
    started = time.time()

    def grow():
        with log.open('a') as stream:
            stream.write(json.dumps({'at': time.time(), 'kind': 'query', 'n': 6}) + '\n')
            stream.write(json.dumps({'at': time.time(), 'kind': 'tab_open', 'n': 5}) + '\n')
    grow()
    outcome = ledger.watch(child, ledger=path, log=log, started_at=started, limit=300, poll=0.05,
                           on_stop=lambda: stopped.append(True), today=TODAY)
    assert outcome == {'outcome': 'budget_stop', 'counted': 301}
    assert stopped == [True]
    assert child.wait(timeout=5) != 0
    states = subprocess.run(['ps', '-o', 'stat=', '-g', str(child.pid)], capture_output=True, text=True).stdout.split()
    assert all(s.startswith('Z') for s in states), 'the background sleep in the group must be gone too'


def test_watch_lets_a_run_under_the_target_finish(tmp_path):
    path = write_ledger(tmp_path / 'l.tsv', [])
    log = tmp_path / 'requests.jsonl'
    child = subprocess.Popen(['sh', '-c', 'exit 0'], start_new_session=True)
    outcome = ledger.watch(child, ledger=path, log=log, started_at=time.time(), limit=300, poll=0.05, today=TODAY)
    assert outcome == {'outcome': 'finished', 'counted': 0}
