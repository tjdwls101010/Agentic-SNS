"""doctor through the real CLI and a scripted Aside: opening the dedicated tab, request counting, account protection and
the --unblock check (fixtures: stores, aside_output). The shared doctor (fields common to every platform, a saved block
reported without touching the browser, the unblock check's one request) is the core's: core/test_reading.py,
core/test_protection.py. Here: what Threads adds — a prepaid opening, the page's own signals, the hold a 429 makes and
the idle emptying of the tab."""
import json
import os
import subprocess
import sys
import time

from sns.paths import scope
from sns.session import Session
from tests.sns.support.cli import CLI
from tests.sns.threads.scenes import (ACCOUNT, ASIDE, ENVIRONMENT, LOGGED_IN_DOCUMENT, START, guard, known_tab, opening,
                                      query_result, run, stand_block, stand_hold, state, state_of)

CHECKPOINT_BODY = json.dumps({'message': 'checkpoint_required', 'checkpoint_url': 'https://www.threads.com/challenge/x/',
                              'status': 'fail'})
MODULES = {'live': {'BarcelonaFeedDirectQuery': {'doc_id': '1', 'kind': None}}, 'resources': 0, 'statuses': [],
           'signals': [], 'location': START}
RATE_BODY = json.dumps({'error': {'code': 4, 'message': 'Please wait a few minutes before you try again later.'}})
LOGIN_BODY = json.dumps({'errors': [{'message': 'login_required'}]})


def doctor(browser, *args, env=None):
    code, out, err = run(browser, 'doctor', *args, env=env)
    return code, json.loads(out), err


def log():
    path = scope('threads', ASIDE, 'protection') / 'requests.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def kinds():
    return [(line['kind'], line['n']) for line in log() if 'kind' in line]


def page_result(body, url=START, status=200, **extra):
    return {'status': status, 'url': url, 'body': body, 'explicit': 1, 'resources': 1, 'statuses': [200],
            'signals': [], 'location': START, **extra}


# --- opening the tab ----------------------------------------------------------------------------------------------------

def test_opens_a_tab_on_the_start_screen_and_prepays_it(browser):
    opening(browser).respond('threads.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    check = result['results'][0]
    assert check['tab'] == {'target_id': 'NEW1', 'opened_now': True, 'reopened': False}
    assert check['viewer'] == ACCOUNT and check['login'] == 'ready' and check['aside_account'] == ASIDE
    assert result['request_count'] == 40 and result['setup_requests'] == 40  # 34 seen, 40 prepaid
    assert [c['url'] for c in browser.calls() if c['op'] == 'open'] == [START]
    assert Session('threads', ASIDE).tab == 'NEW1'
    assert ('tab_open', 40) in kinds()


def test_reuses_the_known_tab_and_reports_what_it_did_between_commands(browser):
    known_tab(browser, resources=7, statuses=[200] * 7).respond('threads.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert 'open' not in browser.ops() and result['request_count'] == 0
    assert result['unwatched_requests'] == 7
    assert kinds() == [('unwatched', 7)]


def test_a_tab_emptied_earlier_is_replaced_by_a_new_one_counted_like_opening(browser):
    # Aside drops an emptied tab once nothing holds it, even while it is being sent back to Threads: open a new one
    browser.tab('T1', url='about:blank')
    Session('threads', ASIDE).set_tab('T1')
    opening(browser).respond('threads.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert result['results'][0]['tab'] == {'target_id': 'NEW1', 'opened_now': True, 'reopened': True}
    assert result['setup_requests'] == 40 and 'threads.navigate' not in browser.ops()
    assert [c['url'] for c in browser.calls() if c['op'] == 'open'] == [START]


def test_opening_waits_until_the_page_is_quiet_so_its_load_is_not_charged_to_the_next_read(browser):
    browser.flag(open_ids=['NEW1'])
    browser.respond('threads.state', state(resources=20, document=LOGGED_IN_DOCUMENT))
    browser.respond('threads.state', state(resources=12)).respond('threads.state', state(resources=0))
    browser.respond('threads.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert browser.ops().count('threads.state') == 3
    assert result['request_count'] == 40 and kinds() == [('tab_open', 40)]


def test_a_load_bigger_than_the_prepaid_reservation_is_charged_in_full(browser):
    opening(browser, resources=55).respond('threads.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0 and result['setup_requests'] == 56, result  # 55 seen + the document


def test_an_unreadable_session_opens_one_tab_and_says_so(browser):
    directory = scope('threads', ASIDE, 'session')
    (directory / 'tab.json').write_text('not json')
    browser.tab('OLD', url=START)  # a Threads tab the skill cannot vouch for is not adopted
    opening(browser).respond('threads.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert result['session_reset'] is True and result['results'][0]['tab']['target_id'] == 'NEW1'


def test_two_commands_starting_together_open_one_tab(browser):
    browser.flag(open_ids=['NEW1'])
    browser.respond('threads.state', state(resources=30, document=LOGGED_IN_DOCUMENT)).respond('threads.state', state())
    browser.respond('threads.modules', MODULES).respond('threads.state', state()).respond('threads.modules', MODULES)
    browser.write()
    environment = {**os.environ, **browser.env(), **ENVIRONMENT}
    first = subprocess.Popen([sys.executable, str(CLI), 'threads', 'doctor'], env=environment, stdout=subprocess.PIPE,
                             text=True)
    time.sleep(0.5)
    second = subprocess.Popen([sys.executable, str(CLI), 'threads', 'doctor'], env=environment,
                              stdout=subprocess.PIPE, text=True)
    results = [json.loads(p.communicate(timeout=60)[0]) for p in (first, second)]
    assert [r['ok'] for r in results] == [True, True], results
    assert browser.ops().count('open') == 1
    assert {r['results'][0]['tab']['target_id'] for r in results} == {'NEW1'}


def test_an_account_switch_seen_while_the_page_loads_is_a_changed_login(browser):
    browser.flag(open_ids=['NEW1'])
    browser.respond('threads.state', state(resources=20, document=LOGGED_IN_DOCUMENT))
    browser.respond('threads.state', state(resources=0, user_id='1000000077')).respond('threads.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 4 and 'changed' in result['message'], result


def test_what_the_page_finishes_after_the_reservation_is_set_off_against_it(browser):
    """The opening reserved 40 and saw 34: the 6 the page finishes while the first read runs are part of the opening,
    not new requests, so the read is charged its own request only."""
    opening(browser, resources=33).respond('threads.query', query_result(
        {'data': {'feedData': {'edges': [], 'page_info': {'has_next_page': False, 'end_cursor': None}}}}, resources=7))
    code, out, _ = run(browser, 'feed', '--json')
    result = json.loads(out)
    assert result['setup_requests'] == 40 and result['request_count'] == 41, result


def test_a_logout_seen_while_waiting_for_the_page_to_go_quiet_is_a_login_failure(browser):
    browser.flag(open_ids=['NEW1'])
    browser.respond('threads.state', state(resources=20, document=LOGGED_IN_DOCUMENT))
    browser.respond('threads.state', state(resources=0, user_id='0')).respond('threads.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 4, result


# --- what the tab shows or kept -----------------------------------------------------------------------------------------

def test_a_saved_block_stops_before_the_browser_is_touched(browser):
    stand_block('checkpoint')
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked' and 'checkpoint' in result['message']
    assert browser.calls() == [] or set(browser.ops()) <= {'account_status'}


def test_a_checkpoint_body_the_tab_kept_blocks_and_empties_the_tab(browser):
    signal = {'url': 'https://www.threads.com/graphql/query', 'status': 200, 'summary': CHECKPOINT_BODY, 'at': 1792148826874}
    known_tab(browser, signals=[signal])
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked' and 'checkpoint' in result['message']
    assert state_of()['person']['reason'] == 'checkpoint' and state_of()['hold'] is None
    assert 'threads.blank' in browser.ops() and 'threads.modules' not in browser.ops()
    assert Session('threads', ASIDE).ack == 1792148826874
    assert guard().state()['blocked'] is True


def test_an_ordinary_signal_is_acknowledged_without_a_block(browser):
    signal = {'url': 'https://www.threads.com/graphql/query', 'status': 200, 'at': 55,
              'summary': '{"errors": [{"message": "A field could not be resolved", "severity": "WARNING"}]}'}
    known_tab(browser, signals=[signal]).respond('threads.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert state_of()['blocked'] is False
    assert Session('threads', ASIDE).ack == 55


def test_a_tab_on_the_challenge_page_is_a_checkpoint(browser):
    known_tab(browser, location='https://www.threads.com/challenge/?next=%2F', runtime=False, user_id=None)
    code, result, _ = doctor(browser)
    assert code == 5 and state_of()['person']['reason'] == 'checkpoint'


def test_a_tab_on_the_login_page_needs_login_and_records_no_block(browser):
    known_tab(browser, location='https://www.threads.com/accounts/login/?next=%2F', user_id=None)
    code, result, _ = doctor(browser)
    assert code == 4 and result['error'] == 'login'
    assert state_of()['blocked'] is False


def test_a_new_tab_showing_checkpoint_markers_blocks_before_any_query(browser):
    browser.flag(open_ids=['NEW1'])
    browser.respond('threads.state', state(resources=20, document='<html><form action="/challenge/action/"></form></html>'))
    code, result, _ = doctor(browser)
    assert code == 5 and state_of()['person']['reason'] == 'checkpoint'
    assert 'threads.modules' not in browser.ops() and 'threads.query' not in browser.ops()


def test_a_reused_tab_showing_a_checkpoint_form_is_a_checkpoint(browser):
    known_tab(browser, markers=['<form method="post" action="/challenge/'])
    code, result, _ = doctor(browser)
    assert code == 5 and state_of()['person']['reason'] == 'checkpoint'


# --- a 429 is a hold of the account, not a person block -------------------------------------------------------------------

def test_a_429_while_the_new_tab_loaded_is_an_account_hold_and_the_tab_is_emptied(browser):
    opening(browser, statuses=[200, 429, 200])
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked', result
    state = state_of()
    assert state['hold'] is not None and state['person'] is None, state  # a hold, which passes by itself
    assert 1700 < state['hold']['until'] - time.time() <= 1800  # the 30 minutes of the policy
    assert 'threads.blank' in browser.ops()


def test_a_429_seen_while_the_tab_was_still_loading_is_recorded(browser):
    browser.flag(open_ids=['NEW1'])
    browser.respond('threads.state', state(resources=25, statuses=[200, 429], runtime=False, user_id=None))
    browser.respond('threads.state', state(resources=8, document=LOGGED_IN_DOCUMENT))
    code, result, _ = doctor(browser)
    assert code == 5 and state_of()['hold'] is not None
    assert result['setup_requests'] == 40  # 34 seen over two looks, within the reservation


def test_a_429_in_any_report_is_recorded(browser):
    known_tab(browser).respond('threads.modules', {**MODULES, 'resources': 1, 'statuses': [429]})
    code, result, _ = doctor(browser)
    assert code == 5 and state_of()['hold'] is not None


def test_a_hold_stops_the_next_command_before_the_browser_and_passes_by_itself(browser):
    stand_hold(1800)
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked' and result['limit']['reset'] and 'resume by themselves' in result['message']
    assert set(browser.ops()) <= {'account_status'}


def test_the_strongest_signal_wins_and_is_recorded_before_acknowledging(browser):
    signals = [{'url': 'https://www.threads.com/graphql/query', 'status': 200, 'summary': LOGIN_BODY, 'at': 10},
               {'url': 'https://www.threads.com/graphql/query', 'status': 200, 'summary': RATE_BODY, 'at': 11}]
    known_tab(browser, signals=signals)
    code, result, _ = doctor(browser)
    assert code == 5 and state_of()['hold'] is not None
    assert 'threads.blank' in browser.ops()
    assert Session('threads', ASIDE).ack == 11


# --- doctor --unblock ---------------------------------------------------------------------------------------------------

def test_unblock_lifts_the_block_only_after_a_clean_check(browser):
    stand_block('checkpoint')
    known_tab(browser).respond('threads.page', page_result(LOGGED_IN_DOCUMENT)).respond('threads.modules', MODULES)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 0, result
    assert state_of()['person'] is None and result['results'][0]['unblocked'] is True
    assert browser.ops().index('threads.page') < browser.ops().index('threads.modules')
    assert ('unblock_check', 1) in kinds()
    [call] = [c for c in browser.calls() if c['op'] == 'threads.page']
    assert call['args']['path'] == '/search'


def test_unblock_keeps_the_block_when_the_check_sees_a_checkpoint(browser):
    stand_block('checkpoint')
    known_tab(browser).respond('threads.page', page_result('', url='https://www.threads.com/challenge/x/'))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and state_of()['person']['reason'] == 'checkpoint'


def test_unblock_keeps_the_block_when_the_tab_cannot_be_opened(browser):
    stand_block('checkpoint')
    browser.flag(open_fails=True)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'aside' and state_of()['person']['reason'] == 'checkpoint'


def test_unblock_keeps_a_checkpoint_when_the_check_returns_a_rate_limit_body(browser):
    stand_block('checkpoint')
    known_tab(browser).respond('threads.page', page_result(RATE_BODY))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and state_of()['person']['reason'] == 'checkpoint' and result['verification_reason'] == 'rate_limited'


def test_unblock_keeps_the_block_when_the_check_proves_nothing(browser):
    stand_block('checkpoint')
    known_tab(browser).respond('threads.page', page_result(''))
    code, result, _ = doctor(browser, '--unblock')
    assert code != 0 and state_of()['person']['reason'] == 'checkpoint'


def test_unblock_keeps_the_block_when_the_tab_is_logged_in_as_someone_else(browser):
    stand_block('checkpoint', viewer='1000000077')
    known_tab(browser)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'account_mismatch' and state_of()['person']['reason'] == 'checkpoint'
    assert 'threads.page' not in browser.ops()  # the check stopped before its request


def test_unblock_makes_one_request_even_when_threads_redirects_the_check(browser):
    stand_block('checkpoint')
    known_tab(browser).respond('threads.page', {**page_result('', status=302), 'location_header': '/following'})
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and state_of()['person']['reason'] == 'checkpoint'
    assert browser.ops().count('threads.page') == 1


def test_unblock_does_not_lift_a_hold(browser):
    stand_hold(1800)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and state_of()['hold'] is not None
    assert 'threads.page' not in browser.ops()


# --- the idle emptying of the tab ---------------------------------------------------------------------------------------

def idle(browser, *words, env=None):
    code, out, err = run(browser, 'idle', '--account', ASIDE, *words, env=env)
    return code, json.loads(out), err


def test_the_idle_cleanup_empties_the_tab_after_the_last_command(browser):
    known_tab(browser).respond('threads.modules', MODULES)
    browser.respond('threads.state', {'resources': 2, 'statuses': [200, 200], 'signals': [], 'location': START,
                                      'user_id': ACCOUNT, 'runtime': True})
    code, result, _ = doctor(browser, env={'SNS_IDLE_SECONDS': '1'})
    assert code == 0
    deadline = time.time() + 20
    while 'threads.blank' not in browser.ops() and time.time() < deadline:
        time.sleep(0.3)
    assert 'threads.blank' in browser.ops()
    assert ('unwatched', 2) in kinds()


def test_the_idle_cleanup_leaves_a_tab_a_newer_command_uses(browser):
    known_tab(browser).respond('threads.modules', MODULES)
    assert doctor(browser)[0] == 0
    code, out, _ = idle(browser, '--token', 'an-older-token', '--after', '0')
    assert code == 0 and out['outcome'] == 'newer command'
    assert 'threads.blank' not in browser.ops()


def test_any_token_empties_the_tab_whoever_released_it_last(browser):
    # what a maintainer job uses after stopping a run: the stopped command never released the tab
    known_tab(browser).respond('threads.modules', MODULES)
    assert doctor(browser)[0] == 0
    browser.respond('threads.state', state())
    code, out, _ = idle(browser, '--token', 'any', '--after', '0')
    assert code == 0 and out['outcome'] == 'emptied' and 'threads.blank' in browser.ops()


def test_the_idle_cleanup_empties_the_tab_even_while_a_block_stands(browser):
    known_tab(browser).respond('threads.modules', MODULES)
    assert doctor(browser)[0] == 0
    stand_block('checkpoint')
    browser.respond('threads.state', state())
    code, out, _ = idle(browser, '--token', 'any', '--after', '0')
    assert out['outcome'] == 'emptied' and 'threads.blank' in browser.ops()


def test_unblock_without_a_tab_takes_the_opening_as_its_one_check(browser):
    """Found by review: with no tab to reuse, --unblock opened one (the page's own ~33 requests) and then read /search
    as well while the block stood. The opening, judged as it loads, is the check; nothing more is sent."""
    stand_block('checkpoint')
    opening(browser).respond('threads.modules', MODULES)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 0, result
    assert state_of()['person'] is None and result['results'][0]['unblocked'] is True
    assert not [c for c in browser.calls() if c['op'] in ('threads.page', 'threads.query')]
