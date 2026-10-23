"""The comment-tree snapshot store on a real filesystem (data/reddit/<account>/snapshots/): one file per read generation,
a day to live, the oldest evicted past a size cap, a reference that cannot name another file, one process at a time."""
import os
import subprocess
import sys
import time

import pytest

from sns.clock import Deadline
from sns.errors import SnsError
from sns.reddit import snapshots
from tests.sns.support.cli import CLI

KEY = ['t3_aaa1', None, 'confidence']


def store(account='u0', seconds=30):
    return snapshots.Snapshots(account, Deadline(seconds))


def test_a_new_generation_leaves_the_old_one_alone(data_dir):
    snaps = store()
    with snaps.locked():
        first = snaps.new(KEY)
        snaps.save(first, {'observed_at': 1, 'shown': ['t1_a']})
        time.sleep(0.002)
        second = snaps.new(KEY)
        snaps.save(second, {'observed_at': 2, 'shown': []})
    assert first != second and snaps.latest(KEY) == second
    assert snaps.load(first) == {'observed_at': 1, 'shown': ['t1_a']}
    assert snaps.latest(['t3_bbb2', None, 'confidence']) is None


def test_the_snapshots_of_two_accounts_are_apart(data_dir):
    generation = store('u0').new(KEY)
    store('u0').save(generation, {'x': 1})
    assert store('u1').load(generation) is None and (data_dir / 'reddit/u0/snapshots').is_dir()


def test_expired_generation_is_gone(data_dir):
    snaps = store()
    generation = snaps.new(KEY)
    snaps.save(generation, {})
    path = data_dir / f'reddit/u0/snapshots/{generation}.json'
    old = time.time() - snapshots.TTL_SECONDS - 5
    os.utime(path, (old, old))
    assert snaps.load(generation) is None and snaps.latest(KEY) is None


def test_size_cap_evicts_the_oldest_others(data_dir, monkeypatch):
    snaps = store()
    monkeypatch.setattr(snapshots, 'MAX_BYTES', 2500)
    made = []
    for index in range(3):
        generation = snaps.new(['t3_x%d' % index, None, 'new'])
        snaps.save(generation, {'pad': 'x' * 1000})
        made.append(generation)
        time.sleep(0.01)
    assert snaps.load(made[0]) is None and snaps.load(made[2]) is not None
    assert 0 < snaps.size() <= 2500


def test_a_thread_larger_than_the_cap_is_refused_for_out(data_dir, monkeypatch):
    snaps = store()
    monkeypatch.setattr(snapshots, 'MAX_BYTES', 100)
    with pytest.raises(SnsError) as caught:
        snaps.save(snaps.new(KEY), {'pad': 'x' * 1000})
    assert caught.value.kind == 'failed' and '--out' in caught.value.fix


def test_corrupt_or_foreign_snapshot_reference(data_dir):
    snaps = store()
    generation = snaps.new(KEY)
    (data_dir / f'reddit/u0/snapshots/{generation}.json').write_text('{')
    with pytest.raises(SnsError) as caught:
        snaps.load(generation)
    assert caught.value.kind == 'argument' and 'post again' in caught.value.fix
    with pytest.raises(SnsError):
        snaps.load('../../etc/passwd')


def test_a_snapshot_reference_cannot_name_another_file(data_dir):
    snaps = store()
    victim = data_dir / 'reddit/u0/protection'
    victim.mkdir(parents=True)
    (victim / 'scopes.json').write_text('{}')
    with pytest.raises(SnsError):
        snaps.save('../protection/scopes', {'x': 1})
    assert (victim / 'scopes.json').read_text() == '{}'


HOLDER = '''
import sys, time
from sns.clock import Deadline
from sns.reddit import snapshots
from tests.sns.support.cli import CLI
with snapshots.Snapshots('u0', Deadline(30)).locked():
    open(sys.argv[1], 'w').write('in'); time.sleep(1.5)
'''


def hold(data_dir, tmp_path):
    flag = tmp_path / 'in'
    env = {**os.environ, 'SNS_DATA_DIR': str(data_dir), 'PYTHONPATH': str(CLI.parent)}
    child = subprocess.Popen([sys.executable, '-c', HOLDER, str(flag)], env=env)
    while not flag.exists() and child.poll() is None:
        time.sleep(0.02)
    return child


def test_snapshots_are_changed_one_process_at_a_time(data_dir, tmp_path):
    child = hold(data_dir, tmp_path)
    started = time.time()
    with store().locked():
        waited = time.time() - started
    child.wait(timeout=10)
    assert waited > 1.0


def test_the_wait_for_the_lock_ends_at_the_deadline(data_dir, tmp_path):
    child = hold(data_dir, tmp_path)
    try:
        with pytest.raises(SnsError) as caught:
            with store(seconds=0.4).locked():
                pass
        assert caught.value.reason == 'time_limit'
    finally:
        child.wait(timeout=10)
