import multiprocessing
import os
import pytest
from twitter_skill._blocked import account_lock, read_state, set_blocked, write_state
from twitter_skill._budget import Budget
from twitter_skill._errors import TwitterError


def reserve_in_process(home):
    os.environ['TWITTER_HOME'] = home
    with account_lock():
        Budget(clock=lambda: 1000, sleep=lambda _: None, jitter=lambda: 0).reserve('query')


@pytest.fixture
def budget(tmp_path, monkeypatch):
    monkeypatch.setenv('TWITTER_HOME', str(tmp_path))
    return Budget(maximum=40, clock=lambda: 1000, sleep=lambda _: None, jitter=lambda: 0)


def test_two_processes_share_reservations(budget, tmp_path):
    # fcntl is the production boundary; fork also preserves the test package import.
    context = multiprocessing.get_context('fork')
    workers = [context.Process(target=reserve_in_process, args=(str(tmp_path),)) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(5)
        assert worker.exitcode == 0
    assert budget.summary()['window'] == 2


def test_zero_bucket_blocks_only_that_operation_until_reset(budget):
    budget.observe('small', {'limit': 50, 'remaining': 0, 'reset': 1100}, 429, 'SearchTimeline')
    with pytest.raises(TwitterError) as exc:
        budget.reserve('small')
    assert exc.value.error == 'rate_limit'
    assert budget.used == 0
    budget.reserve('large')
    assert budget.used == 1
    budget.clock = lambda: 1101
    budget.reserve('small')
    assert budget.used == 2


def test_shared_window_prevents_another_request(budget):
    write_state('budget.json', {'requests': [999] * 200})
    with pytest.raises(TwitterError) as exc:
        budget.reserve('query')
    assert exc.value.error == 'window'
    assert budget.used == 0


def test_explicit_collection_stops_at_forty_requests(budget):
    for _ in range(40):
        budget.reserve('query')
    with pytest.raises(TwitterError) as exc:
        budget.reserve('query')
    assert (exc.value.code, exc.value.error) == (8, 'budget')
    assert budget.summary()['window'] == 40


def test_headers_replace_reservation_and_expired_bucket_is_discarded(budget):
    budget.observe('query', {'limit': 50, 'remaining': 10, 'reset': 1100})
    budget.reserve('query')
    budget.observe('query', {'limit': 50, 'remaining': 8, 'reset': 1100}, operation='SearchTimeline')
    assert budget.summary()['operations']['SearchTimeline']['remaining'] == 8
    budget.clock = lambda: 1200
    budget.reserve('query')
    assert 'query' not in read_state('budget.json')['buckets']


def test_permanent_block_survives_later_rate_limit_and_expiry(budget):
    set_blocked('account_locked')
    budget.observe('query', {'limit': 50, 'remaining': 0, 'reset': 1001}, 429)
    budget.clock = lambda: 99999
    with pytest.raises(TwitterError) as exc:
        budget.reserve('different')
    assert exc.value.error == 'account_locked'
    assert read_state('budget.json')['block']['expires_at'] is None
