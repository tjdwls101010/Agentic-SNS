import json
import multiprocessing
from pathlib import Path
import pytest
from reddit_skill._budget import Budget
from reddit_skill._errors import RedditError


class Clock:
    def __init__(self, now=1000):
        self.now = now
        self.waits = []
    def time(self):
        return self.now
    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


def make_budget(tmp_path, clock):
    return Budget(tmp_path, clock=clock.time, monotonic=clock.time, sleep=clock.sleep, jitter=lambda: 0)


def test_reservation_headers_and_zero_only_block_next_request(tmp_path):
    clock = Clock()
    budget = make_budget(tmp_path, clock)
    with budget.request():
        budget.observe({'remaining': '0', 'used': '100', 'reset': '30'})
    assert budget.snapshot['remaining'] == 0
    assert budget.snapshot['expires_at'] == 1030
    with pytest.raises(RedditError) as caught:
        with budget.request():
            pytest.fail('depleted budget reached network')
    assert caught.value.code == 5
    clock.now = 1031
    with budget.request():
        pass
    assert budget.snapshot['remaining'] == 99


@pytest.mark.parametrize('headers', [{}, {'remaining': '50'}, {'remaining': 'nan', 'used': '1', 'reset': '3'}])
def test_incomplete_headers_keep_local_reservation(tmp_path, headers):
    clock = Clock()
    budget = make_budget(tmp_path, clock)
    with budget.request():
        budget.observe({'remaining': '80', 'used': '20', 'reset': '100'})
    with budget.request():
        budget.observe(headers)
    assert budget.snapshot['remaining'] == 79
    assert budget.snapshot['expires_at'] == 1100
    assert clock.waits == [1]


def test_failed_request_keeps_reservation_and_clock_rollback_discards_observation(tmp_path):
    clock = Clock()
    budget = make_budget(tmp_path, clock)
    with pytest.raises(RuntimeError):
        with budget.request():
            raise RuntimeError('lost process')
    assert budget.snapshot['remaining'] == 99
    clock.now = 999
    with budget.request():
        pass
    assert budget.snapshot['remaining'] == 99


def test_governor_and_challenge_unblock(tmp_path):
    clock = Clock()
    budget = make_budget(tmp_path, clock)
    with budget.request():
        budget.observe({'remaining': '10', 'used': '90', 'reset': '100'})
    with budget.request():
        budget.block('challenge')
    assert clock.waits == [10]
    clock.now += 1000
    with pytest.raises(RedditError):
        with budget.request():
            pass
    budget.unblock()
    with budget.request():
        pass


def reserve_worker(home, queue):
    budget = Budget(Path(home))
    try:
        with budget.request():
            queue.put('reserved')
    except RedditError as exc:
        queue.put(exc.code)


def test_two_processes_cannot_spend_same_last_request(tmp_path):
    import time
    now = time.time()
    (tmp_path / 'budget.json').write_text(json.dumps({'observed_at': now, 'expires_at': now + 100,
        'remaining': 1, 'used': 99, 'next_allowed_at': now, 'block': None}))
    context = multiprocessing.get_context('fork')
    queue = context.Queue()
    processes = [context.Process(target=reserve_worker, args=(str(tmp_path), queue)) for _ in range(2)]
    for process in processes:
        process.start()
    for process in processes:
        process.join(5)
        assert not process.is_alive()
        assert process.exitcode == 0
    assert sorted([queue.get(timeout=1), queue.get(timeout=1)], key=str) == [5, 'reserved']
    assert Budget(tmp_path).snapshot['remaining'] == 0


def test_unblock_without_challenge_is_idempotent(tmp_path):
    budget = make_budget(tmp_path, Clock())
    budget.unblock()
    with budget.request():
        budget.block('rate_limit', 30)
    budget.unblock()
    assert budget.snapshot['block']['reason'] == 'rate_limit'


def test_missing_headers_do_not_disable_governor(tmp_path):
    clock = Clock()
    budget = make_budget(tmp_path, clock)
    with budget.request():
        budget.observe({'remaining': '10', 'used': '90', 'reset': '100'})
    with budget.request():
        budget.observe({})
    with budget.request():
        budget.observe({})
    assert clock.waits == [10, 10]


def test_expiring_header_does_not_remove_minimum_request_spacing(tmp_path):
    clock = Clock()
    budget = make_budget(tmp_path, clock)
    with budget.request():
        budget.observe({'remaining': '0', 'used': '100', 'reset': '0'})
    with budget.request():
        pass
    assert clock.waits == [1]


def observe_worker(home, entered, release, queue):
    budget = Budget(Path(home))
    with budget.request():
        entered.set()
        if not release.wait(3):
            raise RuntimeError('test did not release request')
        budget.observe({'remaining': '0', 'used': '100', 'reset': '30'})
    queue.put('observed')


def test_response_update_is_inside_same_process_lock_as_reservation(tmp_path):
    context = multiprocessing.get_context('fork')
    entered, release, queue = context.Event(), context.Event(), context.Queue()
    first = context.Process(target=observe_worker, args=(str(tmp_path), entered, release, queue))
    second = context.Process(target=reserve_worker, args=(str(tmp_path), queue))
    first.start()
    assert entered.wait(3)
    second.start()
    # The in-flight first response closes the window before the second reservation.
    release.set()
    for process in (first, second):
        process.join(5)
        assert not process.is_alive()
        assert process.exitcode == 0
    assert sorted([queue.get(timeout=1), queue.get(timeout=1)], key=str) == [5, 'observed']
