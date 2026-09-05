import json
import multiprocessing
import time

import pytest

from threads_skill._budget import Budget
from threads_skill._blocked import account_lock, cache_dir, check_blocked, set_blocked, write_state
from threads_skill._errors import ThreadsError


def reserve_one():
    with Budget().request():
        pass


def test_independent_processes_share_reservations():
    ctx = multiprocessing.get_context('fork')
    workers = [ctx.Process(target=reserve_one) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(5)
        assert worker.exitcode == 0
    assert Budget().snapshot()['window_used'] == 2


def test_window_full_refuses_before_request_and_checkpoint_cannot_be_downgraded():
    with account_lock():
        write_state('budget.json', {'requests': [time.time()] * 120})
    with pytest.raises(ThreadsError) as error:
        reserve_one()
    assert error.value.code == 5
    with account_lock():
        set_blocked('checkpoint')
        set_blocked('rate_limit')
    assert json.loads((cache_dir() / 'blocked.json').read_text())['expires_at'] is None
    with pytest.raises(ThreadsError) as error:
        check_blocked()
    assert error.value.error == 'checkpoint'


def test_request_failure_still_spends_budget_and_local_cap_is_partial():
    budget = Budget(max_requests=1)
    with pytest.raises(RuntimeError):
        with budget.request():
            raise RuntimeError('network lost')
    with pytest.raises(ThreadsError) as error:
        with budget.request():
            pytest.fail('must not issue the second request')
    assert (error.value.code, error.value.error) == (8, 'budget')
    assert budget.snapshot()['used'] == 1
