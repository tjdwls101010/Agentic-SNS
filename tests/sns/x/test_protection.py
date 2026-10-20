"""What is X's own in account protection (the mechanisms are the core's: tests/sns/core/test_protection.py, run over the
five policy rows): the adapter's policy row; X's per-operation 15-minute windows as fixtures/limits.json states them, run
at the protection interface with X's policy and X's header parsing; and the decisions the X client makes with the fake
Aside — what is a hold on one operation, what is only a fact, what a limit another operation showed in the tab does, and
what a lock or challenge does — together with the request-log outcomes the contrast watch reads."""
import json
import time

import pytest

from contrast.sns import ledger
from sns import protection
from sns.clock import Deadline
from sns.errors import SnsError
from sns.session import Session
from sns.x import PLATFORM, web
from tests.sns.support.clocks import FakeClock
from tests.sns.support.policies import POLICIES
from tests.sns.x.data import fixture
from tests.sns.x.scenes import ACCOUNT, ASIDE, known_tab, limits, query_result, queries, run, stand_block, state, state_of

LIMITS = fixture('limits.json')
CASES = {case['name']: case for case in LIMITS['cases']}
LOCK_SIGNAL = {'path': '/i/api/graphql/abc/HomeTimeline', 'status': 200, 'codes': [326], 'html': False, 'rate': None,
               'at': 1792148826874}
USER = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'example_author', 'name': 'Example'}}


def timeline(ids, bottom='CUR1'):
    entries = [{'entryId': f'tweet-{i}', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {
        'result': {'__typename': 'Tweet', 'rest_id': i, 'core': {'user_results': {'result': USER}},
                   'legacy': {'full_text': f'post {i}', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026'}}}}}}
               for i in ids]
    if bottom:
        entries.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}})
    return {'data': {'home': {'home_timeline_urt': {'instructions': [{'type': 'TimelineAddEntries',
                                                                       'entries': entries}]}}}}


def rate(limit, remaining, reset):
    return {'x-rate-limit-limit': str(limit), 'x-rate-limit-remaining': str(remaining), 'x-rate-limit-reset': str(reset)}


def limited(reset=None, remaining='0'):
    headers = {} if reset is None else rate(500, remaining, reset)
    return query_result('{"errors":[{"code":88,"message":"Rate limit exceeded"}]}', status=429, headers=headers)


# --- the policy row -----------------------------------------------------------------------------------------------------

def test_the_adapter_policy_is_the_x_row_of_the_plan():
    assert PLATFORM.policy == POLICIES['x']
    assert PLATFORM.policy.scope == 'operation' and PLATFORM.policy.hold_seconds == 900  # X's windows are 15 minutes
    assert PLATFORM.policy.person == ('challenge', 'account_locked')
    assert PLATFORM.unblock_scope == 'Viewer' and PLATFORM.idle_action == 'close'


def test_only_a_lock_or_a_challenge_is_a_person_block_of_x(data_dir):
    with protection.open('x', ASIDE, PLATFORM.policy, Deadline(100), title='X', site='x.com').request() as slot:
        with pytest.raises(ValueError):
            slot.block('checkpoint')  # the Meta platforms' reason, not X's
        slot.block('challenge', viewer=ACCOUNT)
    assert state_of()['block_reason'] == 'challenge'


# --- fixtures/limits.json at the protection interface: X's policy, X's headers ----------------------------------------

def guard_at(clock, seconds=100):
    return protection.open('x', ASIDE, PLATFORM.policy, Deadline(seconds, clock), title='X', site='x.com')


def window_from(headers):
    """The Fact X's headers state, as the client hands it to the guard."""
    return web.fact(headers)


def prepare(case, clock):
    """The world of a case: what the last request (at last_request_at) and its response headers left behind."""
    buckets = dict(case.get('buckets') or {})
    if case.get('bucket'):
        buckets[case['operation']] = case['bucket']
    if case.get('last_request_at') is not None or buckets:
        clock.now = case.get('last_request_at', case['now'])
        earlier = guard_at(clock, 1000)
        for scope in list(buckets) or [case['operation']]:
            headers = buckets.get(scope)
            with earlier.request(scope=scope) as slot:
                slot.classify('ok')  # every answer is classified: an unclassified one is a lost request and keeps its probe
                if headers:
                    slot.fact(scope, window_from(rate(headers['limit'], headers['remaining'], headers['reset'])))
    if case.get('recent_requests'):
        guard_at(clock, 1000).log_unwatched(case['recent_requests'])
    clock.now = case['now']


@pytest.mark.parametrize('name', ['no-bucket-normal-pace', 'healthy-bucket-normal-pace', 'low-bucket-stretches',
                                  'other-operation-unaffected', 'no-account-window', 'expired-bucket-forgotten'])
def test_a_request_goes_after_the_wait_its_operations_window_allows(data_dir, name):
    case = CASES[name]
    clock = FakeClock()
    prepare(case, clock)
    slept = len(clock.slept)
    with guard_at(clock, case['deadline_in']).request(scope=case['operation']) as slot:
        slot.classify('ok')
    low, high = case['expected'].get('wait_between', [0, 1.0])
    assert low - 1e-6 <= sum(clock.slept[slept:]) <= high + 1e-6, clock.slept[slept:]
    if 'bucket_after' in case['expected']:  # null: a window that has reset is forgotten, not carried
        assert limits()[case['operation']]['status'] != 'known'


@pytest.mark.parametrize('name', ['empty-bucket-refuses', 'stretched-wait-past-deadline', 'limit-and-deadline-limit-first'])
def test_an_operations_window_stops_only_that_operation_before_anything_is_sent(data_dir, name):
    case = CASES[name]
    clock = FakeClock()
    prepare(case, clock)
    slept = len(clock.slept)
    with pytest.raises(SnsError) as caught:
        with guard_at(clock, case['deadline_in']).request(scope=case['operation']):
            pytest.fail('no request may be sent')
    error, expected = caught.value, case['expected']
    assert error.kind == 'scope_limit' and error.reason == 'rate_limited'  # exit 10, never an account problem
    assert error.details['reset'] == expected['reset'] and error.details['next_allowed_at'] == expected['next_allowed_at']
    assert not state_of()['blocked'] and len(clock.slept) == slept
    with guard_at(clock).request(scope='Viewer') as slot:  # another operation still goes
        slot.classify('ok')


def test_past_the_deadline_the_limit_is_not_weighed_again(data_dir):
    case = CASES['limit-and-deadline-past-deadline']
    clock = FakeClock()
    prepare(case, clock)
    with pytest.raises(SnsError) as caught:
        with guard_at(clock, case['deadline_in']).request(scope=case['operation']):
            pytest.fail('no request may be sent')
    assert caught.value.kind == 'failed' and caught.value.reason == 'time_limit'  # exit 6 before any record


def test_x_slows_an_operation_below_a_fifth_of_its_window_and_not_at_a_fifth(data_dir):
    """The policy's 20%: 9 of 50 left stretches the gap to (reset - now) / remaining, 10 of 50 does not."""
    for remaining, slowed in ((9, True), (10, False)):
        clock = FakeClock()
        with guard_at(clock).request(scope=f'Op{remaining}') as slot:
            slot.classify('ok')
            slot.fact(f'Op{remaining}', window_from(rate(50, remaining, int(clock.now) + 300)))
        assert ('slow_until' in limits()[f'Op{remaining}']) is slowed


def test_every_measured_window_is_a_limit_the_client_keeps_per_operation(browser):
    """measured_limits_15min: X's own windows (limit per 15 minutes) are what the guard shows, operation by operation."""
    reset = int(time.time()) + 900
    known_tab(browser).respond('x.query', query_result(timeline(['1850000000000000001']), headers=rate(
        LIMITS['measured_limits_15min']['HomeTimeline'], 499, reset)))
    code, out, _ = run(browser, 'feed')
    assert code == 0, out
    shown = limits()['HomeTimeline']
    assert (shown['limit'], shown['remaining'], shown['reset_at']) == (500, 499, reset)
    assert LIMITS['measured_limits_15min'] == {'UserTweets': 50, 'SearchTimeline': 50, 'TweetDetail': 300,
                                               'HomeTimeline': 500, 'Viewer': 100}


# --- what the client decides with a response -----------------------------------------------------------------------

@pytest.mark.parametrize('name', ['429-without-reset', '429-with-past-reset', '429-with-future-reset'])
def test_a_429_holds_that_operation_until_x_says_or_one_window_when_x_does_not(browser, name):
    """The case's times are relative to its `now`: the same offsets from the real clock."""
    case = CASES[name]
    observed = case['observe']
    now = time.time()
    headers = {k: (str(int(v) - 1000 + int(now)) if k.endswith('reset') else v) for k, v in observed['headers'].items()}
    known_tab(browser).respond('x.query', query_result('{"errors":[{"code":88}]}', status=429, headers=headers))
    code, out, _ = run(browser, 'feed')
    envelope = json.loads(out)
    expected_reset = case['expected']['bucket_after']['reset'] - 1000 + now
    assert code == 10 and envelope['error'] == 'scope_limit' and envelope['stop_reason'] == 'rate_limited'
    assert envelope['limit']['scope'] == 'HomeTimeline'
    assert limits()['HomeTimeline']['blocked_until'] == pytest.approx(expected_reset, abs=5)
    assert not state_of()['blocked']  # a limit is never an account block


def test_headers_replace_the_window_a_response_reports(browser):
    case = CASES['headers-replace-bucket']
    now = time.time()
    earlier = case['bucket']
    shifted = lambda moment: int(moment - 1000 + now)  # noqa: E731
    with guard_at(FakeClockAt(now)).request(scope='HomeTimeline') as slot:
        slot.fact('HomeTimeline', window_from(rate(earlier['limit'], 250, shifted(earlier['reset']))))
    known_tab(browser).respond('x.query', query_result(timeline(['1850000000000000001']), headers=rate(
        300, case['observe']['headers']['x-rate-limit-remaining'], shifted(1700))))
    code, out, _ = run(browser, 'feed')
    assert code == 0, out
    assert limits()['HomeTimeline']['remaining'] == 250 and limits()['HomeTimeline']['reset_at'] == shifted(1700)


def FakeClockAt(moment):
    clock = FakeClock(start=moment)
    return clock


def test_one_operations_429_leaves_the_others_reading(browser):
    known_tab(browser).respond('x.query', limited(int(time.time()) + 600))
    code, out, _ = run(browser, 'feed')
    assert code == 10
    browser.respond('x.state', state())
    browser.respond('x.query', query_result({'data': {'search_by_raw_query': {'search_timeline': {'timeline': {
        'instructions': [{'type': 'TimelineAddEntries', 'entries': []}]}}}}}))
    code, out, _ = run(browser, 'search', 'words')
    assert code == 7 and json.loads(out)['error'] == 'empty'  # reached X: an explicit nothing, not a refusal


def test_a_window_shown_in_a_responses_headers_slows_the_next_request_of_that_operation(browser):
    reset = int(time.time()) + 300
    known_tab(browser).respond('x.query', query_result(timeline(['1850000000000000001']), headers=rate(500, 20, reset)))
    browser.respond('x.query', query_result(timeline(['1850000000000000002'], bottom=None), headers=rate(500, 19, reset)))
    code, out, _ = run(browser, 'feed', '--limit', '2')
    assert code == 0, out
    shown = limits()['HomeTimeline']
    assert 'slow_until' in shown and shown['remaining'] == 19  # 4% left: spaced out until the reset


def another_operations_signal(**extra):
    return {'path': '/i/api/graphql/abc/ViewerBadgeCounts', 'status': 429, 'codes': [88], 'html': False,
            'rate': {'limit': 50, 'remaining': 0, 'reset': int(time.time()) + 600}, 'at': 55, **extra}


def test_another_operations_limit_seen_in_the_tab_holds_that_operation_and_the_read_goes_on(browser):
    signal = another_operations_signal()
    known_tab(browser).respond('x.query', query_result(timeline(['1850000000000000001']), signals=[signal]))
    code, out, _ = run(browser, 'feed')
    assert code == 0, out
    assert limits()['ViewerBadgeCounts']['blocked_until'] == signal['rate']['reset']
    assert not state_of()['blocked'] and Session('x', ASIDE).ack == 55
    assert 'HomeTimeline' in limits() and 'blocked_until' not in limits()['HomeTimeline']


def test_a_spent_window_reported_with_a_200_by_the_tab_is_held_until_its_reset(browser):
    signal = another_operations_signal(status=200, codes=[])
    known_tab(browser, signals=[signal]).respond('x.query', query_result(timeline(['1850000000000000001'])))
    code, out, _ = run(browser, 'feed')
    assert code == 0, out  # the first look held that other operation; the feed itself was not stopped
    assert limits()['ViewerBadgeCounts']['blocked_until'] == signal['rate']['reset']


def test_the_asked_operations_own_limit_in_the_tab_ends_the_read_with_exit_10_before_any_query(browser):
    reset = int(time.time()) + 600
    signal = {'path': '/i/api/graphql/abc/HomeTimeline', 'status': 429, 'codes': [88], 'html': False,
              'rate': {'limit': 500, 'remaining': 0, 'reset': reset}, 'at': 77}
    known_tab(browser, signals=[signal])
    code, out, _ = run(browser, 'feed')
    envelope = json.loads(out)
    assert code == 10 and envelope['limit']['scope'] == 'HomeTimeline' and envelope['limit']['reset'] == reset
    assert queries(browser) == []


def test_a_limit_the_page_found_while_the_call_ran_stops_the_call_with_that_operations_hold(browser):
    reset = int(time.time()) + 600
    signal = {'path': '/i/api/graphql/abc/HomeTimeline', 'status': 429, 'codes': [88], 'html': False,
              'rate': {'limit': 500, 'remaining': 0, 'reset': reset}, 'at': 78}
    known_tab(browser).respond('x.query', {'stopped': 'limit', 'explicit': 0, 'resources': 0, 'ours': 0,
                                           'statuses': [], 'signals': [signal], 'location': 'https://x.com/i/xskill',
                                           'moved': None})
    code, out, _ = run(browser, 'feed')
    assert code == 10 and json.loads(out)['limit']['reset'] == reset
    assert limits()['HomeTimeline']['blocked_until'] == reset and not state_of()['blocked']


# --- a lock or a challenge: a person block ------------------------------------------------------------------------------

def test_a_lock_code_in_the_tab_is_a_person_block_for_the_tabs_account_and_closes_the_tab(browser):
    known_tab(browser, signals=[LOCK_SIGNAL])
    code, out, _ = run(browser, 'feed')
    assert code == 5 and json.loads(out)['error'] == 'blocked'
    person = state_of()['person']
    assert person['reason'] == 'account_locked' and person['viewer'] == ACCOUNT
    assert 'x.close' in browser.ops() and queries(browser) == []
    assert Session('x', ASIDE).ack == LOCK_SIGNAL['at']


def test_a_challenge_page_as_the_answer_is_a_person_block_and_the_read_keeps_what_it_had(browser):
    known_tab(browser).respond('x.query', query_result(timeline(['1850000000000000001'])))
    browser.respond('x.query', query_result('<!DOCTYPE html><html class="cf">challenge</html>', status=403))
    code, out, _ = run(browser, 'feed', '--limit', '5')
    assert code == 5 and '1850000000000000001' in out and 'more:' not in out
    assert state_of()['person']['reason'] == 'challenge' and 'x.close' in browser.ops()


def test_a_block_stands_for_the_next_invocation_before_the_browser_is_touched(browser):
    stand_block('challenge')
    code, out, _ = run(browser, 'feed')
    assert code == 5 and json.loads(out)['error'] == 'blocked'
    assert [c for c in browser.calls() if c['op'] != 'account_status'] == []  # the browser is not touched


# --- request-log outcomes: what the contrast watch stops on ---------------------------------------------------------------

def logged_outcomes(data_dir):
    logs = ledger.request_logs(data_dir)
    return {entry['outcome'] for log in logs for entry in map(json.loads, log.read_text().splitlines())}


@pytest.mark.parametrize('answer, outcome', [
    (lambda: query_result('{"errors":[{"code":88}]}', status=429, headers=rate(500, 0, int(time.time()) + 600)),
     'rate_limited'),
    (lambda: query_result('<!DOCTYPE html><html class="cf"></html>', status=403), 'challenge'),
    (lambda: query_result('{"errors":[{"code":326}]}', status=403), 'account_locked'),
    (lambda: query_result('{"errors":[{"code":32}]}', status=401), 'login_required'),
])
def test_the_request_log_names_what_stopped_a_read_so_the_contrast_watch_can_stop_the_run(browser, data_dir, answer,
                                                                                          outcome):
    known_tab(browser).respond('x.query', answer())
    started = time.time() - 1
    run(browser, 'feed')
    logs = ledger.request_logs(data_dir)
    assert logs and ledger.block_signal(logs, started) == outcome, logged_outcomes(data_dir)


def test_an_ordinary_read_logs_no_block_signal(browser, data_dir):
    known_tab(browser).respond('x.query', query_result(timeline(['1850000000000000001']), headers=rate(500, 499, 1)))
    started = time.time() - 1
    run(browser, 'feed')
    logs = ledger.request_logs(data_dir)
    assert ledger.logged(logs, started) == 1 and ledger.block_signal(logs, started) is None


# --- diagnostics ----------------------------------------------------------------------------------------------------------

def test_verbose_diagnostics_are_scrubbed(browser):
    """--verbose writes request metadata to stderr; a secret in what the page reports never reaches it
    (fixtures/scrub.json itself is run over sns.redact.scrub by tests/sns/core/test_redact.py)."""
    answer = query_result(timeline(['1850000000000000001']), headers=rate(500, 499, 1))
    answer['used'] = {'source': 'live ct0=SYNTHSECRET', 'query_id': 'SYNTHq', 'features': []}
    known_tab(browser).respond('x.query', answer)
    browser.write()
    from tests.sns.support.cli import run_cli
    done = run_cli('--verbose', 'x', 'feed', browser=browser, env={'TZ': 'UTC', 'SNS_IDLE_SECONDS': 'off'})
    assert done.returncode == 0, done.stdout
    diagnostics = [json.loads(line) for line in done.stderr.splitlines() if line.startswith('{')]
    assert diagnostics and 'SYNTHSECRET' not in done.stderr
    assert diagnostics[0]['stage'] == 'request' and diagnostics[0]['operation'] == 'HomeTimeline'
    assert '[REDACTED]' in diagnostics[0]['source']


# --- X's state files read as the core reads them (the old guard tests the core suite does not repeat) ----------------------
# Corrupt state can only be made by writing the files, so these reach the protection directory of X on purpose.

def protection_dir(data_dir):
    return data_dir / 'x' / ASIDE / 'protection'


def seed(data_dir, name, value):
    protection_dir(data_dir).mkdir(parents=True, exist_ok=True)
    (protection_dir(data_dir) / name).write_text(value if isinstance(value, str) else json.dumps(value))


@pytest.mark.parametrize('name, value', [
    ('blocks.json', 'not json'),
    ('blocks.json', {'person': {'reason': 'other', 'at': 1, 'viewer': None}, 'hold': None}),
    ('blocks.json', {'person': {'reason': 'checkpoint', 'at': 1, 'viewer': None}, 'hold': None}),  # Meta's, not X's
    ('blocks.json', {'person': {'reason': 'challenge', 'at': 1, 'viewer': 7}, 'hold': None}),
    ('scopes.json', 'not json'),
    ('scopes.json', {'TweetDetail': {'status': 'known', 'limit': 'x', 'remaining': 1, 'reset_at': 2}}),
    ('pace.json', {'next_allowed_at': 'soon'}),
])
def test_unreadable_state_fails_closed_for_x_too(data_dir, name, value):
    seed(data_dir, name, value)
    with pytest.raises(SnsError) as caught:
        with guard_at(FakeClock()).request(scope='TweetDetail'):
            pytest.fail('no request may be sent')
    assert caught.value.kind == 'blocked' and caught.value.reason == 'unreadable'


def test_a_dangling_block_link_is_unreadable_not_absent(data_dir):
    protection_dir(data_dir).mkdir(parents=True, exist_ok=True)
    (protection_dir(data_dir) / 'blocks.json').symlink_to(data_dir / 'nowhere.json')
    with pytest.raises(SnsError) as caught:
        guard_at(FakeClock()).check()
    assert caught.value.reason == 'unreadable'


def test_a_state_file_that_cannot_be_set_aside_is_named_for_a_person(data_dir):
    protection_dir(data_dir).mkdir(parents=True, exist_ok=True)
    (protection_dir(data_dir) / 'scopes.json').mkdir()
    with pytest.raises(SnsError) as caught:
        with guard_at(FakeClock()).verify_unblock(scope='Viewer'):
            pytest.fail('no check may be sent')
    assert caught.value.kind == 'blocked' and 'scopes.json' in caught.value.message and 'person' in caught.value.fix


def test_evidence_set_aside_by_an_earlier_check_is_not_overwritten(data_dir):
    for moment in (1000, 2000):
        seed(data_dir, 'scopes.json', f'broken at {moment}')
        with guard_at(FakeClock(start=moment)).verify_unblock(scope='Viewer'):
            pass
    kept = sorted(p.read_text() for p in protection_dir(data_dir).glob('scopes.json.unreadable-*'))
    assert kept == ['broken at 1000', 'broken at 2000']


def test_a_readable_block_is_kept_as_it_is_when_only_other_state_is_unreadable(data_dir):
    """Its account decides who may lift it; replacing it with an unknown-account block would let any account do so."""
    stand_block('challenge', viewer='1000000098')
    seed(data_dir, 'pace.json', 'broken')
    with guard_at(FakeClock(start=1000)).verify_unblock(scope='Viewer') as check:
        assert check.person['reason'] == 'challenge' and check.person['viewer'] == '1000000098'
    assert (protection_dir(data_dir) / 'pace.json.unreadable-1000').read_text() == 'broken'
    assert state_of()['person']['viewer'] == '1000000098'  # not cleared: the check did not call clear()


def test_unreadable_state_with_no_block_gets_a_standing_one_that_only_a_clean_check_lifts(data_dir):
    seed(data_dir, 'scopes.json', 'broken')
    with guard_at(FakeClock(start=1000)).verify_unblock(scope='Viewer') as check:
        assert check.person['reason'] == 'unreadable'
    assert state_of()['block_reason'] == 'unreadable'


def test_a_failed_replacement_leaves_the_unreadable_block_in_place(data_dir):
    """There is never a moment without a block: setting state aside must not fail open."""
    seed(data_dir, 'blocks.json', 'not json')
    directory = protection_dir(data_dir)
    directory.chmod(0o500)
    try:
        with pytest.raises(SnsError):
            with guard_at(FakeClock(start=1000)).verify_unblock(scope='Viewer'):
                pytest.fail('no check may be sent')
    finally:
        directory.chmod(0o700)
    assert (directory / 'blocks.json').read_text() == 'not json'
    with pytest.raises(SnsError) as caught:
        guard_at(FakeClock()).check()
    assert caught.value.kind == 'blocked'


def test_one_operations_slowdown_is_waited_out_without_holding_the_lock(data_dir):
    """Another operation's command must not queue behind a stretched limit (plan X4): while the slowed request sleeps,
    a request of another operation goes through the same lock."""
    clock = FakeClock()
    with guard_at(clock).request(scope='SearchTimeline') as slot:
        slot.classify('ok')
        slot.fact('SearchTimeline', window_from(rate(50, 5, int(clock.now) + 300)))  # 60 s apart
    free = []

    class Watching(FakeClock):
        def sleep(self, seconds):
            if seconds > 5:
                other = FakeClock(start=self.now)
                try:
                    with guard_at(other, 100).request(scope='Viewer') as slot:
                        slot.classify('ok')
                    free.append(seconds)
                except SnsError:
                    pass  # the lock was held: the other request could not start
            super().sleep(seconds)

    waiting = Watching(start=clock.now)
    with guard_at(waiting).request(scope='SearchTimeline') as slot:
        slot.classify('ok')
    assert free and free[0] == pytest.approx(60, abs=1)


# --- X's decisions around the tab the core cannot see -----------------------------------------------------------------

def test_a_person_block_is_not_replaced_or_lifted_by_a_limit_recorded_while_it_stands(data_dir):
    stand_block('account_locked')
    with guard_at(FakeClock()).observe(allow_blocked=True) as slot:  # the idle cleanup's look
        slot.hold(until=time.time() + 600, scope='SearchTimeline')
    assert state_of()['person']['reason'] == 'account_locked'
    assert limits()['SearchTimeline']['blocked_until'] > time.time()


def test_the_idle_cleanup_empties_the_tab_even_while_a_block_stands(browser):
    known_tab(browser)
    stand_block('account_locked')
    browser.respond('x.state', state())  # what the cleanup's look reads before it empties the tab
    code, out, _ = run(browser, 'idle', '--account', ASIDE, '--token', 'any', '--after', '0')
    assert code == 0 and json.loads(out)['outcome'] == 'emptied', out
    assert 'x.close' in browser.ops() and state_of()['person']['reason'] == 'account_locked'


def test_requests_the_tab_made_between_commands_are_logged_and_reported_not_charged(browser):
    known_tab(browser, resources=7, statuses=[200] * 7).respond('x.query', query_result(
        timeline(['1850000000000000001']), headers=rate(500, 499, int(time.time()) + 900)))
    before = protection.open('x', ASIDE, PLATFORM.policy, Deadline(100), title='X', site='x.com').recent()['last_hour']
    code, out, _ = run(browser, 'feed', '--json')
    envelope = json.loads(out)
    assert code == 0 and envelope['unwatched_requests'] == 7 and envelope['request_count'] == 1
    after = protection.open('x', ASIDE, PLATFORM.policy, Deadline(100), title='X', site='x.com').recent()['last_hour']
    assert after - before == 1 + 7  # the day's log holds both: the read and what the tab did on its own
