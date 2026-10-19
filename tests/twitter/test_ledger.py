"""The development ledger (contrast/twitter/ledger.py): it records every action; with a day target set it refuses an
action whose reservation does not fit what is left, and its watch stops a whole process group at the target."""
import json
import subprocess
import time
from datetime import date

from contrast.twitter import ledger

TODAY = date(2026, 10, 19)


def write_ledger(path, rows):
    path.write_text('date\tphase\trequests\tnote\n' + ''.join(f'{d}\t{s}\t{n}\t{m}\n' for d, s, n, m in rows))
    return path


def test_without_a_target_every_action_fits_and_is_still_recorded(tmp_path):
    path = write_ledger(tmp_path / 'l.tsv', [('2026-10-19', 'P2 R1', 5000, 'a large day')])
    fits = ledger.check(path, 'tab_open', count=10, today=TODAY, target=None)
    assert fits['ok'] is True and fits['today'] == 5000
    ledger.add(path, 'P2 R2', 7, 'replies', today=TODAY)
    assert path.read_text().splitlines()[-1] == '2026-10-19\tP2 R2\t7\treplies'
    assert ledger.totals(path, TODAY) == {'today': 5007, 'all': 5007}


def test_with_a_target_a_reservation_larger_than_what_is_left_is_refused(tmp_path):
    path = write_ledger(tmp_path / 'l.tsv', [('2026-10-18', 'P2 R1', 90, 'yesterday'),
                                             ('2026-10-19', 'P6 contrast', 260, '')])
    # today 260 of 300 → 40 left
    assert ledger.check(path, 'tab_open', today=TODAY, target=300)['ok'] is True            # 40 fits 40 exactly
    refused = ledger.check(path, 'navigation', count=2, today=TODAY, target=300)            # 60 > 40
    assert refused['ok'] is False and refused['left_day'] == 40


def test_overshoot_is_recorded_and_stops_the_day(tmp_path):
    path = write_ledger(tmp_path / 'l.tsv', [('2026-10-19', 'P6 contrast', 290, '')])
    ledger.add(path, 'P6 contrast a1-t5', 25, 'over the target', today=TODAY)
    assert ledger.check(path, 'direct', today=TODAY, target=300)['ok'] is False


def test_watch_stops_the_process_group_at_the_target(tmp_path):
    path = write_ledger(tmp_path / 'l.tsv', [(TODAY.isoformat(), 'P6 contrast', 290, '')])
    log = tmp_path / 'requests.jsonl'
    log.write_text(json.dumps({'at': time.time() - 3600, 'kind': 'query', 'n': 50}) + '\n')   # before the run: ignored
    child = subprocess.Popen(['sh', '-c', 'sleep 60 & sleep 60'], start_new_session=True)
    stopped = []
    started = time.time()
    with log.open('a') as stream:
        stream.write(json.dumps({'at': time.time(), 'kind': 'query', 'n': 6}) + '\n')
        stream.write(json.dumps({'at': time.time(), 'kind': 'tab_open', 'n': 5}) + '\n')
    outcome = ledger.watch(child, ledger=path, log=log, started_at=started, limit=300, poll=0.05,
                           on_stop=lambda: stopped.append(True), today=TODAY)
    assert outcome == {'outcome': 'budget_stop', 'counted': 301}
    assert stopped == [True]
    assert child.wait(timeout=5) != 0
    states = subprocess.run(['ps', '-o', 'stat=', '-g', str(child.pid)], capture_output=True, text=True).stdout.split()
    assert all(s.startswith('Z') for s in states), 'the background sleep in the group must be gone too'


def test_watch_without_a_target_only_waits_and_reports_what_was_logged(tmp_path):
    path = write_ledger(tmp_path / 'l.tsv', [(TODAY.isoformat(), 'P6 contrast', 5000, '')])
    log = tmp_path / 'requests.jsonl'
    started = time.time()
    log.write_text(json.dumps({'at': started + 1, 'kind': 'query', 'n': 400}) + '\n')
    child = subprocess.Popen(['sh', '-c', 'sleep 0.3'], start_new_session=True)
    outcome = ledger.watch(child, ledger=path, log=log, started_at=started, limit=None, poll=0.05, today=TODAY)
    assert outcome == {'outcome': 'finished', 'counted': 5400}
