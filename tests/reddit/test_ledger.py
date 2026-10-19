"""The development request ledger (contrast/reddit/ledger.py): it records every action at once, and its watch stops a
whole process group at the first block signal the skill logged during a run."""
import json
import subprocess
import time
from datetime import date

from contrast.reddit import ledger

TODAY = date(2026, 10, 19)


def entry(at, outcome='ok', n=1, bucket='general'):
    return json.dumps({'at': at, 'bucket': bucket, 'n': n, 'outcome': outcome}) + '\n'


def test_add_records_at_once_without_a_target(tmp_path):
    path = tmp_path / 'l.tsv'
    ledger.add(path, 'P2 R1', 9, 'morechildren batches', today=TODAY)
    ledger.add(path, 'P2 R1', 400, 'well past any old daily target', today=TODAY)
    assert path.read_text().splitlines() == ['date\tstage\trequests\tnote',
                                             '2026-10-19\tP2 R1\t9\tmorechildren batches',
                                             '2026-10-19\tP2 R1\t400\twell past any old daily target']


def test_watch_stops_the_process_group_at_a_block_signal(tmp_path):
    log = tmp_path / 'protection/u0/requests.jsonl'
    log.parent.mkdir(parents=True)
    # before the run: a rate limit an earlier run already reacted to must not stop this one
    log.write_text(entry(time.time() - 3600, 'rate_limited'))
    started = time.time()
    child = subprocess.Popen(['sh', '-c', 'sleep 60 & sleep 60'], start_new_session=True)
    with log.open('a') as stream:
        stream.write(entry(time.time(), 'ok', 3))
        stream.write(entry(time.time(), 'rate_limited', bucket='wiki'))
    outcome = ledger.watch(child, logs=lambda: ledger.request_logs(tmp_path / 'protection'), started_at=started,
                           poll=0.05)
    assert outcome == {'outcome': 'block_stop', 'signal': 'rate_limited', 'counted': 4}
    assert child.wait(timeout=5) != 0
    states = subprocess.run(['ps', '-o', 'stat=', '-g', str(child.pid)], capture_output=True, text=True).stdout.split()
    assert all(s.startswith('Z') for s in states), 'the background sleep in the group must be gone too'


def test_each_block_outcome_stops_a_run(tmp_path):
    for outcome in ('challenge', 'login_required'):
        log = tmp_path / outcome / 'acct/requests.jsonl'
        log.parent.mkdir(parents=True)
        started = time.time()
        log.write_text(entry(started + 0.01, outcome))
        child = subprocess.Popen(['sleep', '30'], start_new_session=True)
        result = ledger.watch(child, logs=lambda: ledger.request_logs(tmp_path / outcome), started_at=started,
                              poll=0.05)
        assert result['outcome'] == 'block_stop' and result['signal'] == outcome


def test_watch_lets_a_clean_run_finish(tmp_path):
    log = tmp_path / 'protection/u0/requests.jsonl'
    log.parent.mkdir(parents=True)
    started = time.time()
    log.write_text(entry(started + 0.01, 'ok', 2) + entry(started + 0.02, 'unavailable'))
    child = subprocess.Popen(['sh', '-c', 'exit 0'], start_new_session=True)
    outcome = ledger.watch(child, logs=lambda: ledger.request_logs(tmp_path / 'protection'), started_at=started,
                           poll=0.05)
    assert outcome == {'outcome': 'finished', 'signal': None, 'counted': 3}
