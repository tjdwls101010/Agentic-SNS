"""guard: account protection on the real filesystem (fixtures/stores.json, protection)."""
import json
import os
import subprocess
import sys
import time

import pytest

from conftest import SKILL
from facebook import guard
from facebook.errors import FacebookError


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
    with pytest.raises(FacebookError) as error:
        request()
    assert error.value.code == 5 and 'checkpoint' in error.value.message


def test_rate_limit_expires(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'rate_limit', 'blocked_at': 1, 'expires_at': time.time() - 1})
    assert request().used == 1


def test_rate_limit_active(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'rate_limit', 'blocked_at': 1, 'expires_at': time.time() + 600})
    with pytest.raises(FacebookError) as error:
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
    with pytest.raises(FacebookError) as error:
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
    with pytest.raises(FacebookError):
        request()


def test_second_process_sees_a_block_recorded_inside_the_lock(data_dir):
    holder = subprocess.Popen([sys.executable, '-c', (
        'import time\nfrom facebook import guard\ng = guard.Guard(2)\n'
        'with g.request() as slot:\n    print("in", flush=True)\n    time.sleep(1.0)\n    slot.block("checkpoint")\n')],
        env={**os.environ, 'PYTHONPATH': str(SKILL / 'scripts')}, stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == 'in'
    with pytest.raises(FacebookError) as error:
        request()
    holder.wait(timeout=10)
    assert error.value.code == 5 and 'checkpoint' in error.value.message


def test_budget_refuses_past_its_end_and_counts_charges(data_dir):
    g = guard.Guard(2)
    with g.request() as slot:
        slot.charge(2)
    assert g.used == 2 and g.remaining == 0
    with pytest.raises(FacebookError) as error:
        with g.request():
            pass
    assert error.value.code == 8


@pytest.mark.parametrize('budget', [0, 401, '3'])
def test_budget_bounds(budget):
    with pytest.raises(FacebookError) as error:
        guard.Guard(budget)
    assert error.value.code == 2


def test_unblock_clears_the_block_and_keeps_pacing(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'checkpoint', 'blocked_at': 1, 'expires_at': None})
    write(data_dir, 'pace.json', {'next_allowed_at': 5.0})
    guard.unblock()
    assert not (data_dir / 'protection/blocked.json').exists()
    assert json.loads((data_dir / 'protection/pace.json').read_text()) == {'next_allowed_at': 5.0}
    assert guard.Guard(1).state()['blocked'] is False


@pytest.mark.parametrize('name', ['blocked.json', 'pace.json'])
def test_a_json_null_state_file_fails_closed(data_dir, name):
    """Review finding 2: a corrupted file holding `null` must not read as 'no state'."""
    write(data_dir, name, 'null')
    with pytest.raises(FacebookError) as error:
        request()
    assert error.value.code == 5 and 'unreadable' in error.value.message


def test_observing_the_tab_happens_under_the_lock_and_respects_a_block(data_dir):
    """Review finding 7: a state probe and the block it may record form one critical section."""
    g = guard.Guard(1)
    with g.observe() as slot:
        slot.block('checkpoint')
    assert g.count == 0
    with pytest.raises(FacebookError):
        with g.observe():
            pass
