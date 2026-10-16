"""guard: account protection on the real filesystem (fixtures/stores.json, protection)."""
import json
import os
import subprocess
import sys
import time

import pytest

from conftest import SKILL
from threads import guard
from threads.errors import ThreadsError


def write(data_dir, name, value):
    path = data_dir / 'protection'
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(value if isinstance(value, str) else json.dumps(value))


def request(budget=5):
    g = guard.Guard(budget)
    with g.request():
        pass
    return g


def test_no_state_is_open(data_dir):
    assert request().used == 1


def test_checkpoint_blocks_until_cleared(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'checkpoint', 'blocked_at': 1, 'expires_at': None})
    with pytest.raises(ThreadsError) as error:
        request()
    assert error.value.code == 5 and 'checkpoint' in error.value.message


def test_rate_limit_expires(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'rate_limit', 'blocked_at': 1, 'expires_at': time.time() - 1})
    assert request().used == 1


def test_rate_limit_active(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'rate_limit', 'blocked_at': 1, 'expires_at': time.time() + 600})
    with pytest.raises(ThreadsError) as error:
        request()
    assert error.value.code == 5


@pytest.mark.parametrize('name, value', [
    ('blocked.json', 'not json'),
    ('blocked.json', {'reason': 'other', 'expires_at': None}),
    ('blocked.json', {'reason': 'checkpoint', 'expires_at': 5}),
    ('blocked.json', {'reason': 'rate_limit', 'expires_at': 'soon'}),
    ('pace.json', {'next_allowed_at': 'soon'}),
    ('pace.json', '['),
])
def test_unreadable_state_fails_closed(data_dir, name, value):
    write(data_dir, name, value)
    with pytest.raises(ThreadsError) as error:
        request()
    assert error.value.code == 5 and 'unreadable' in error.value.message


def test_pacing_waits_for_the_recorded_time(data_dir):
    write(data_dir, 'pace.json', {'next_allowed_at': time.time() + 1.2})
    started = time.monotonic()
    request()
    assert time.monotonic() - started >= 1.1


def test_pace_is_recorded_before_the_request_runs(data_dir):
    g = guard.Guard(2)
    with g.request():
        started = time.time()
        recorded = json.loads((data_dir / 'protection/pace.json').read_text())['next_allowed_at']
        assert started + 0.9 <= recorded <= started + 2.1


def test_block_inside_slot_persists_rate_limit_for_30_minutes(data_dir):
    g = guard.Guard(2)
    with g.request() as slot:
        slot.block('rate_limit')
    record = json.loads((data_dir / 'protection/blocked.json').read_text())
    assert record['reason'] == 'rate_limit'
    assert 1790 <= record['expires_at'] - time.time() <= 1800
    with pytest.raises(ThreadsError):
        request()


def test_second_process_sees_a_block_recorded_inside_the_lock(data_dir):
    holder = subprocess.Popen([sys.executable, '-c', (
        'import time\nfrom threads import guard\ng = guard.Guard(2)\n'
        'with g.request() as slot:\n    print("in", flush=True)\n    time.sleep(1.0)\n    slot.block("checkpoint")\n')],
        env={**os.environ, 'PYTHONPATH': str(SKILL / 'scripts')}, stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == 'in'
    with pytest.raises(ThreadsError) as error:
        request()
    holder.wait(timeout=10)
    assert error.value.code == 5 and 'checkpoint' in error.value.message


def test_budget_refuses_past_its_end_and_counts_charges(data_dir):
    g = guard.Guard(2)
    with g.request() as slot:
        slot.charge(2)
    assert g.used == 2 and g.remaining == 0
    with pytest.raises(ThreadsError) as error:
        with g.request():
            pass
    assert error.value.code == 8


@pytest.mark.parametrize('budget', [0, 401, '3'])
def test_budget_bounds(budget):
    with pytest.raises(ThreadsError) as error:
        guard.Guard(budget)
    assert error.value.code == 2


def test_a_verified_unblock_keeps_pacing(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'checkpoint', 'blocked_at': 1, 'expires_at': None})
    write(data_dir, 'pace.json', {'next_allowed_at': 5.0})
    with guard.Guard(1).verify_unblock() as slot:
        slot.clear()
    assert not (data_dir / 'protection/blocked.json').exists()
    assert json.loads((data_dir / 'protection/pace.json').read_text())['next_allowed_at'] > 5.0  # paced, not reset
    assert guard.Guard(1).state()['blocked'] is False
    assert not hasattr(guard, 'unblock')  # nothing clears a block without the check


@pytest.mark.parametrize('name', ['blocked.json', 'pace.json'])
def test_a_json_null_state_file_fails_closed(data_dir, name):
    """Review finding 2: a corrupted file holding `null` must not read as 'no state'."""
    write(data_dir, name, 'null')
    with pytest.raises(ThreadsError) as error:
        request()
    assert error.value.code == 5 and 'unreadable' in error.value.message


def test_observing_the_tab_happens_under_the_lock_and_respects_a_block(data_dir):
    """Review finding 7: a state probe and the block it may record form one critical section."""
    g = guard.Guard(1)
    with g.observe() as slot:
        slot.block('checkpoint')
    assert g.count == 0
    with pytest.raises(ThreadsError):
        with g.observe():
            pass


# --- threads: verified unblock, no checkpoint downgrade, the observation log (fixtures/stores.json, protection) ---

CHECKPOINT = {'reason': 'checkpoint', 'blocked_at': 1, 'expires_at': None}


def test_unblock_clears_only_after_a_clean_check(data_dir):
    write(data_dir, 'blocked.json', CHECKPOINT)
    g = guard.Guard(1)
    with g.verify_unblock() as slot:
        assert (data_dir / 'protection/blocked.json').exists()  # the block stands while the check runs
        slot.clear()
    assert not (data_dir / 'protection/blocked.json').exists()
    assert g.count == 1  # the one check request is counted


def test_unblock_check_that_fails_keeps_the_block(data_dir):
    write(data_dir, 'blocked.json', CHECKPOINT)
    g = guard.Guard(1)
    with pytest.raises(ThreadsError):
        with g.verify_unblock():
            raise ThreadsError(4, 'login page', 'log in')
    assert json.loads((data_dir / 'protection/blocked.json').read_text())['reason'] == 'checkpoint'


def test_unblock_check_killed_mid_request_keeps_the_block(data_dir):
    write(data_dir, 'blocked.json', CHECKPOINT)
    holder = subprocess.Popen([sys.executable, '-c', (
        'import time\nfrom threads import guard\ng = guard.Guard(1)\n'
        'with g.verify_unblock() as slot:\n    print("in", flush=True)\n    time.sleep(30)\n    slot.clear()\n')],
        env={**os.environ, 'PYTHONPATH': str(SKILL / 'scripts')}, stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == 'in'
    holder.kill()
    holder.wait(timeout=10)
    assert json.loads((data_dir / 'protection/blocked.json').read_text())['reason'] == 'checkpoint'
    with pytest.raises(ThreadsError) as error:
        request()
    assert error.value.code == 5


def test_a_rate_limit_seen_by_the_check_does_not_downgrade_a_checkpoint(data_dir):
    write(data_dir, 'blocked.json', CHECKPOINT)
    g = guard.Guard(1)
    with g.verify_unblock() as slot:
        slot.block('rate_limit')
    record = json.loads((data_dir / 'protection/blocked.json').read_text())
    assert record['reason'] == 'checkpoint' and record['expires_at'] is None


def test_unblock_check_is_one_request_per_invocation(data_dir):
    write(data_dir, 'blocked.json', CHECKPOINT)
    g = guard.Guard(5)
    with g.verify_unblock():
        pass
    with pytest.raises(ThreadsError) as error:
        with g.verify_unblock():
            pass
    assert error.value.code == 5


def log_lines(data_dir):
    path = data_dir / 'protection/requests.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_every_charged_request_is_logged_with_its_kind(data_dir):
    g = guard.Guard(5)
    with g.request() as slot:
        slot.charge(3)
    with g.request(reserve=30, budgeted=False) as slot:  # what is logged is what is charged: here above the reservation
        slot.charge(34)
    with g.request() as slot:
        slot.cancel()
    g.log_unwatched(4)
    assert [(line['kind'], line['n']) for line in log_lines(data_dir)] == [('query', 3), ('tab_open', 34),
                                                                          ('unwatched', 4)]
    assert all(abs(line['at'] - time.time()) < 60 for line in log_lines(data_dir))


def test_the_log_keeps_one_day_and_never_enforces(data_dir):
    old = [{'at': time.time() - 25 * 3600, 'kind': 'query', 'n': 1}]
    recent = [{'at': time.time() - 60, 'kind': 'query', 'n': 1}] * 500
    write(data_dir, 'requests.jsonl', ''.join(json.dumps(line) + '\n' for line in old + recent))
    assert request().used == 1  # no shared window: 500 in the last minutes do not stop a request
    lines = log_lines(data_dir)
    assert len(lines) == 501 and all(time.time() - line['at'] < 24 * 3600 for line in lines)
    assert guard.Guard(1).recent() == {'last_hour': 501, 'last_day': 501}


def test_an_unreadable_log_never_blocks(data_dir):
    write(data_dir, 'requests.jsonl', 'not json\n{"at": "x"}\n')
    assert request().used == 1
