"""guard: account protection on the real filesystem (fixtures/limits.json; fixtures/stores.json protection, unblock).

Times are injected: `clock` is the wall clock buckets and blocks are judged by, `monotonic` the command's deadline,
and `sleep` records waits instead of sleeping.
"""
import json
import os
import subprocess
import sys
import time

import pytest

from conftest import SKILL, fixture
from twitter import guard
from twitter.errors import TwitterError

LIMITS = fixture('limits.json')
CASES = {case['name']: case for case in LIMITS['cases']}


class Clock:
    """A wall clock and a monotonic clock that only move when the guard sleeps."""

    def __init__(self, now):
        self.now, self.mono, self.slept = float(now), 0.0, []

    def time(self):
        return self.now

    def monotonic(self):
        return self.mono

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds
        self.mono += seconds


def write(data_dir, name, value):
    path = data_dir / 'protection'
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(value if isinstance(value, str) else json.dumps(value))


def read(data_dir, name):
    path = data_dir / 'protection' / name
    return json.loads(path.read_text()) if path.exists() else None


def make(clock, budget=25, deadline=100):
    return guard.Guard(budget, deadline_seconds=deadline, clock=clock.time, monotonic=clock.monotonic,
                       sleep=clock.sleep)


def prepare(data_dir, case):
    if case.get('last_request_at') is not None:
        write(data_dir, 'pace.json', {'next_allowed_at': case['last_request_at'] + 1.0})
    buckets = dict(case.get('buckets') or {})
    if case.get('bucket'):
        bucket = dict(case['bucket'])
        if case.get('last_request_at') is not None and 0 < bucket['remaining'] < bucket['limit'] * 0.2:
            bucket['next_at'] = case['last_request_at'] + (bucket['reset'] - case['last_request_at']) / bucket['remaining']
        buckets[case['operation']] = bucket
    if buckets:
        write(data_dir, 'buckets.json', buckets)


# --- limits.json: the decision one request faces ------------------------------------------------------------------

@pytest.mark.parametrize('name', ['healthy-bucket-normal-pace', 'low-bucket-stretches', 'other-operation-unaffected',
                                  'no-account-window', 'expired-bucket-forgotten'])
def test_a_request_goes_after_the_wait_its_bucket_allows(data_dir, name):
    case = CASES[name]
    prepare(data_dir, case)
    clock = Clock(case['now'])
    g = make(clock, deadline=case['deadline_in'])
    with g.request(operation=case['operation']):
        pass
    expected = case['expected']
    low, high = expected.get('wait_between', [0, 1.0])
    assert low - 1e-6 <= sum(clock.slept) <= high + 1e-6, clock.slept
    if 'bucket_after' in expected:
        assert (read(data_dir, 'buckets.json') or {}).get(case['operation']) == expected['bucket_after']


def test_pacing_waits_one_to_two_seconds_after_the_previous_request(data_dir):
    clock = Clock(1000)
    g = make(clock)
    with g.request(operation='TweetDetail'):
        pass
    with g.request(operation='TweetDetail'):
        pass
    assert 1.0 <= clock.slept[-1] <= 2.0


@pytest.mark.parametrize('name', ['empty-bucket-refuses', 'stretched-wait-past-deadline', 'limit-and-deadline-limit-first'])
def test_an_operations_limit_stops_only_that_operation(data_dir, name):
    case = CASES[name]
    prepare(data_dir, case)
    clock = Clock(case['now'])
    g = make(clock, deadline=case['deadline_in'])
    with pytest.raises(TwitterError) as error:
        with g.request(operation=case['operation']):
            pytest.fail('no request may be sent')
    assert error.value.code == 10 and error.value.reason == 'rate_limited'
    assert error.value.details['reset'] == case['expected']['reset']
    assert error.value.details['next_allowed_at'] == case['expected']['next_allowed_at']
    assert read(data_dir, 'blocked.json') is None  # a limit is never an account block
    assert g.used == 0 and clock.slept == []
    with g.request(operation='Viewer'):  # another operation still goes
        pass


def test_past_the_deadline_the_limit_is_not_weighed_again(data_dir):
    case = CASES['limit-and-deadline-past-deadline']
    prepare(data_dir, case)
    clock = Clock(case['now'])
    g = make(clock, deadline=0)
    clock.mono = 1  # already past it
    with pytest.raises(TwitterError) as error:
        with g.request(operation=case['operation']):
            pytest.fail('no request may be sent')
    assert error.value.code == 6 and error.value.reason == 'time_limit'


def test_pacing_that_would_end_after_the_deadline_is_a_time_limit(data_dir):
    clock = Clock(1000)
    write(data_dir, 'pace.json', {'next_allowed_at': 1001.5})
    g = make(clock, deadline=1)
    with pytest.raises(TwitterError) as error:
        with g.request(operation='TweetDetail'):
            pytest.fail('no request may be sent')
    assert error.value.code == 6 and error.value.reason == 'time_limit' and clock.slept == []


@pytest.mark.parametrize('name', ['429-without-reset', '429-with-past-reset', '429-with-future-reset', 'headers-replace-bucket'])
def test_a_response_updates_its_operations_bucket(data_dir, name):
    case = CASES[name]
    if case.get('bucket'):
        write(data_dir, 'buckets.json', {case['observe']['operation']: case['bucket']})
    clock = Clock(case['now'])
    g = make(clock)
    observed = case['observe']
    with g.request(operation=observed['operation']) as slot:
        slot.observe(observed['status'], observed['headers'])
    bucket = read(data_dir, 'buckets.json')[observed['operation']]
    assert {k: bucket[k] for k in ('limit', 'remaining', 'reset')} == case['expected']['bucket_after']
    assert read(data_dir, 'blocked.json') is None


def test_a_bucket_reported_by_the_tab_is_recorded_without_a_request(data_dir):
    clock = Clock(1000)
    g = make(clock)
    with g.observe() as slot:
        slot.record_bucket('ViewerBadgeCounts', 429, None)
    assert read(data_dir, 'buckets.json')['ViewerBadgeCounts']['reset'] == 1900
    assert g.used == 0
    with pytest.raises(TwitterError) as error:
        with g.request(operation='ViewerBadgeCounts'):
            pass
    assert error.value.code == 10


def test_per_command_cap(data_dir):
    clock = Clock(1000)
    g = make(clock, budget=2)
    for _ in range(2):
        with g.request(operation='TweetDetail'):
            pass
    with pytest.raises(TwitterError) as error:
        with g.request(operation='TweetDetail'):
            pass
    assert error.value.code == 8 and error.value.reason == 'budget'


@pytest.mark.parametrize('budget', [0, 401, True, '25'])
def test_cap_ceiling(budget):
    with pytest.raises(TwitterError) as error:
        guard.Guard(budget)
    assert error.value.code == 2


# --- stores.json protection: blocks a person must clear ----------------------------------------------------------

def test_no_state_is_open(data_dir):
    g = make(Clock(1000))
    with g.request(operation='Viewer'):
        pass
    assert g.used == 1


@pytest.mark.parametrize('reason, account', [('account_locked', '1000000099'), ('challenge', None)])
def test_a_person_cleared_block_stops_every_request(data_dir, reason, account):
    write(data_dir, 'blocked.json', {'reason': reason, 'blocked_at': 1, 'account_id': account})
    g = make(Clock(1000))
    with pytest.raises(TwitterError) as error:
        with g.request(operation='Viewer'):
            pytest.fail('no request may be sent')
    assert error.value.code == 5 and error.value.reason == reason


@pytest.mark.parametrize('name, value', [
    ('blocked.json', 'not json'),
    ('blocked.json', {'reason': 'other', 'blocked_at': 1, 'account_id': None}),
    ('blocked.json', {'reason': 'rate_limit', 'blocked_at': 1, 'expires_at': 5}),  # the threads-style block is not X's
    ('blocked.json', {'reason': 'challenge', 'blocked_at': 1, 'account_id': 7}),
    ('buckets.json', 'not json'),
    ('buckets.json', {'TweetDetail': {'limit': 'x', 'remaining': 1, 'reset': 2}}),
    ('pace.json', {'next_allowed_at': 'soon'}),
])
def test_unreadable_state_fails_closed(data_dir, name, value):
    write(data_dir, name, value)
    g = make(Clock(1000))
    with pytest.raises(TwitterError) as error:
        with g.request(operation='TweetDetail'):
            pytest.fail('no request may be sent')
    assert error.value.code == 5


def test_a_block_is_recorded_with_its_account(data_dir):
    g = make(Clock(1000))
    with pytest.raises(TwitterError):
        with g.request(operation='HomeTimeline') as slot:
            slot.block('account_locked', '1000000099')
            raise TwitterError(5, 'locked', 'fix', reason='account_locked')
    record = read(data_dir, 'blocked.json')
    assert record['reason'] == 'account_locked' and record['account_id'] == '1000000099'
    assert read(data_dir, 'buckets.json') is None or 'HomeTimeline' not in read(data_dir, 'buckets.json')


def test_a_limit_never_replaces_or_lifts_a_block(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'account_locked', 'blocked_at': 1, 'account_id': '1000000099'})
    g = make(Clock(1000))
    with g.observe(allow_blocked=True) as slot:
        slot.record_bucket('SearchTimeline', 429, {'limit': 50, 'remaining': 0, 'reset': 1500})
    assert read(data_dir, 'blocked.json')['reason'] == 'account_locked'


def test_the_pace_is_recorded_before_the_request(data_dir):
    clock = Clock(1000)
    g = make(clock)
    with g.request(operation='TweetDetail'):
        nxt = read(data_dir, 'pace.json')['next_allowed_at']
        assert 1001.0 <= nxt <= 1002.0


def test_a_block_is_seen_by_another_process_before_its_request(data_dir):
    code = ('import json, os, time\nfrom twitter import guard\ng = guard.Guard(5)\n'
            'with g.request(operation="HomeTimeline") as slot:\n    print("in", flush=True)\n    time.sleep(0.8)\n'
            '    slot.block("account_locked", "1")\n')
    holder = subprocess.Popen([sys.executable, '-c', code], env={**os.environ, 'PYTHONPATH': str(SKILL / 'scripts')},
                              stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == 'in'
    g = guard.Guard(5)
    with pytest.raises(TwitterError) as error:
        with g.request(operation='TweetDetail'):
            pytest.fail('the block must be seen first')
    holder.wait(timeout=10)
    assert error.value.code == 5


def test_waiting_for_the_lock_past_the_deadline_is_a_time_limit(data_dir):
    code = ('import time\nfrom twitter import guard\ng = guard.Guard(5)\n'
            'with g.request(operation="HomeTimeline"):\n    print("in", flush=True)\n    time.sleep(3)\n')
    holder = subprocess.Popen([sys.executable, '-c', code], env={**os.environ, 'PYTHONPATH': str(SKILL / 'scripts')},
                              stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == 'in'
    g = guard.Guard(5, deadline_seconds=0.6)
    started = time.monotonic()
    with pytest.raises(TwitterError) as error:
        with g.request(operation='TweetDetail'):
            pytest.fail('no request may be sent')
    assert error.value.code == 6 and error.value.reason == 'time_limit'
    assert time.monotonic() - started < 2.0
    holder.wait(timeout=10)


def test_charged_and_unwatched_requests_are_logged_and_rolled(data_dir):
    clock = Clock(1000)
    old = json.dumps({'at': time.time() - guard.LOG_SECONDS - 10, 'kind': 'query', 'n': 3})
    write(data_dir, 'requests.jsonl', old + '\n')
    g = make(clock)
    with g.request(operation='TweetDetail'):
        pass
    g.log_unwatched(4)
    lines = [json.loads(line) for line in (data_dir / 'protection/requests.jsonl').read_text().splitlines()]
    assert [(line['kind'], line['n']) for line in lines] == [('query', 1), ('unwatched', 4)]
    assert lines[0]['operation'] == 'TweetDetail'


def test_what_a_look_at_the_tab_charges_is_logged_too(data_dir):
    """The page's own requests a look saw are charged to the command; the day's log must not miss them."""
    g = make(Clock(1000))
    with g.observe() as slot:
        slot.charge(3)
    with g.observe():
        pass
    lines = [json.loads(line) for line in (data_dir / 'protection/requests.jsonl').read_text().splitlines()]
    assert [(line['kind'], line['n']) for line in lines] == [('background', 3)] and g.count == 3


# --- stores.json unblock: the verification slot -------------------------------------------------------------------

def test_the_verification_slot_passes_the_block_and_clears_only_when_asked(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'account_locked', 'blocked_at': 1, 'account_id': '1000000099'})
    write(data_dir, 'buckets.json', {'SearchTimeline': {'limit': 50, 'remaining': 0, 'reset': 1500}})
    g = make(Clock(1000))
    with g.verify_unblock(operation='Viewer') as slot:
        assert slot.block_record['account_id'] == '1000000099'
        slot.clear()
    assert read(data_dir, 'blocked.json') is None
    assert read(data_dir, 'buckets.json')['SearchTimeline']['remaining'] == 0  # buckets are not cleared
    assert g.setup == 1 and g.used == 0


def test_the_verification_slot_keeps_the_block_on_any_failure(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'challenge', 'blocked_at': 1, 'account_id': None})
    g = make(Clock(1000))
    with pytest.raises(RuntimeError):
        with g.verify_unblock(operation='Viewer'):
            raise RuntimeError('the check failed')
    assert read(data_dir, 'blocked.json')['reason'] == 'challenge'


def test_the_verification_slot_obeys_the_viewer_bucket(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'challenge', 'blocked_at': 1, 'account_id': None})
    write(data_dir, 'buckets.json', {'Viewer': {'limit': 100, 'remaining': 0, 'reset': 1300}})
    g = make(Clock(1000))
    with pytest.raises(TwitterError) as error:
        with g.verify_unblock(operation='Viewer'):
            pytest.fail('no verification request may be sent')
    assert error.value.code == 5 and error.value.details['verification_reason'] == 'rate_limited'
    assert error.value.details['next_allowed_at'] == 1300
    assert read(data_dir, 'blocked.json')['reason'] == 'challenge'


def test_the_verification_slot_obeys_the_deadline(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'challenge', 'blocked_at': 1, 'account_id': None})
    clock = Clock(1000)
    g = make(clock, deadline=0)
    clock.mono = 1
    with pytest.raises(TwitterError) as error:
        with g.verify_unblock(operation='Viewer'):
            pytest.fail('no verification request may be sent')
    assert error.value.code == 5 and error.value.details['verification_reason'] == 'time_limit'


def test_one_verification_per_invocation(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'challenge', 'blocked_at': 1, 'account_id': None})
    g = make(Clock(1000))
    with g.verify_unblock(operation='Viewer'):
        pass
    with pytest.raises(TwitterError) as error:
        with g.verify_unblock(operation='Viewer'):
            pass
    assert error.value.code == 5


def test_state_reports_the_block_and_the_buckets_that_are_low(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'challenge', 'blocked_at': 1, 'account_id': None})
    write(data_dir, 'buckets.json', {'SearchTimeline': {'limit': 50, 'remaining': 3, 'reset': 1500},
                                     'TweetDetail': {'limit': 300, 'remaining': 290, 'reset': 1500},
                                     'Old': {'limit': 50, 'remaining': 0, 'reset': 900}})
    state = make(Clock(1000)).state()
    assert state['blocked'] and state['block_reason'] == 'challenge' and state['block_account_id'] is None
    assert set(state['buckets']) == {'SearchTimeline', 'TweetDetail'}  # expired ones are gone


def test_a_low_bucket_seen_in_a_response_stretches_the_next_request(data_dir):
    clock = Clock(1000)
    g = make(clock)
    with g.request(operation='SearchTimeline') as slot:
        slot.observe(200, {'x-rate-limit-limit': '50', 'x-rate-limit-remaining': '5', 'x-rate-limit-reset': '1300'})
    clock.slept.clear()
    with g.request(operation='SearchTimeline'):
        pass
    assert abs(sum(clock.slept) - 60) < 1e-6  # (1300 - 1000) / 5


def test_looking_at_the_tab_is_refused_under_a_block_unless_it_only_empties_it(data_dir):
    write(data_dir, 'blocked.json', {'reason': 'challenge', 'blocked_at': 1, 'account_id': None})
    g = make(Clock(1000))
    with pytest.raises(TwitterError) as error:
        with g.observe():
            pytest.fail('a look must not start under a block')
    assert error.value.code == 5
    with g.observe(allow_blocked=True):
        pass


def test_a_wait_that_leaves_too_little_time_for_the_call_is_refused_without_sleeping(data_dir):
    """Sleeping until just before the deadline only to time out in the browser call is a lost request (P3 review 10)."""
    clock = Clock(1000)
    write(data_dir, 'buckets.json', {'SearchTimeline': {'limit': 50, 'remaining': 5, 'reset': 1300, 'next_at': 1008}})
    g = make(clock, deadline=10)
    with pytest.raises(TwitterError) as error:
        with g.request(operation='SearchTimeline'):
            pytest.fail('no request may be sent')
    assert error.value.code == 10 and error.value.details['next_allowed_at'] == 1008 and clock.slept == []
    write(data_dir, 'pace.json', {'next_allowed_at': 1001.5})
    with pytest.raises(TwitterError) as error:
        with make(clock, deadline=3).request(operation='TweetDetail'):
            pytest.fail('no request may be sent')
    assert error.value.reason == 'time_limit' and clock.slept == []


def test_one_operations_slowdown_is_waited_out_without_holding_the_lock(data_dir):
    """Another operation's command must not queue behind a stretched limit (plan X4; P3 review 11)."""
    import fcntl
    clock = Clock(1000)
    write(data_dir, 'buckets.json', {'SearchTimeline': {'limit': 50, 'remaining': 5, 'reset': 1300, 'next_at': 1060}})
    free = []

    def sleep(seconds):
        with open(data_dir / 'protection' / 'lock', 'a') as other:
            try:
                fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(other, fcntl.LOCK_UN)
                free.append(seconds)
            except BlockingIOError:
                pass
        clock.sleep(seconds)

    g = guard.Guard(25, deadline_seconds=100, clock=clock.time, monotonic=clock.monotonic, sleep=sleep)
    with g.request(operation='SearchTimeline'):
        pass
    assert 60 in free and g.used == 1


def test_the_unblock_check_sets_unreadable_state_aside_and_keeps_a_block_until_it_passes(data_dir):
    """Otherwise an unreadable file refuses every request, the unblock check included, with no way out but deleting
    protection by hand."""
    clock = Clock(1000)
    write(data_dir, 'blocked.json', 'not json')
    write(data_dir, 'buckets.json', {'Viewer': 'broken'})
    with make(clock).verify_unblock() as slot:
        assert slot.block_record == {'reason': 'account_locked', 'blocked_at': 1000, 'account_id': None}
    assert (data_dir / 'protection/blocked.json.unreadable').read_text() == 'not json'
    assert (data_dir / 'protection/buckets.json.unreadable').exists() and read(data_dir, 'buckets.json') is None
    assert read(data_dir, 'blocked.json')['reason'] == 'account_locked'  # not cleared: the caller did not call clear()
    with pytest.raises(TwitterError) as error:
        with make(clock).request(operation='TweetDetail'):
            pytest.fail('still blocked')
    assert error.value.code == 5 and error.value.reason == 'account_locked'
