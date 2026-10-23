"""doctor through the real CLI and a scripted Aside: opening the dedicated tab, request counting, account
protection and the --unblock check (fixtures: stores.json unblock, tab_protection, session). The shared doctor (fields
common to every platform, a saved block reported without touching the browser, the unblock check's one request) is the
core's: core/test_reading.py (doctor), core/test_protection.py (unblock). Here: what X adds."""
import json
import os
import signal
import subprocess
import sys
import time

from sns.session import Session
from tests.sns.support.cli import CLI, run_cli
from tests.sns.x.scenes import (ACCOUNT, ASIDE, ENVIRONMENT, MODULES, START, guard, known_tab, limits, opening,
                                queries, query_result, run, stand_block, stand_limit, state, state_of)

OTHER = '1000000098'
VIEWER = {'data': {'viewer': {'user_results': {'result': {'__typename': 'User', 'rest_id': ACCOUNT,
                                                          'core': {'screen_name': 'example_viewer'}}}}}}
RATE = {'x-rate-limit-limit': '100', 'x-rate-limit-remaining': '99', 'x-rate-limit-reset': str(int(time.time()) + 600)}
LOCK_SIGNAL = {'path': '/i/api/graphql/abc/HomeTimeline', 'status': 200, 'codes': [326], 'html': False, 'rate': None,
               'at': 5}


def doctor(browser, *args, env=None):
    code, out, err = run(browser, 'doctor', *args, env=env)
    return code, json.loads(out), err


def requests_logged():
    """Every request of the account the log holds (the log itself is the core's: core/test_protection.py)."""
    return guard().recent()['last_day']


def test_opens_a_tab_without_an_agent_and_measures_what_the_load_cost(browser):
    opening(browser, resources=13).respond('x.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    check = result['results'][0]
    assert check['tab'] == {'target_id': 'NEW1', 'opened_now': True, 'reopened': False, 'opening_measured': True}
    assert check['viewer'] == ACCOUNT and check['login'] == 'ready' and check['aside_account'] == ASIDE
    assert result['request_count'] == 14 and result['setup_requests'] == 14  # 13 seen + the document
    ops = [op for op in browser.ops() if op not in ('tabs', 'account_status')]
    assert ops[:2] == ['opener', 'load:x.arm'] and ops.index('opener_end') > ops.index('load:x.arm')
    assert [c['url'] for c in browser.calls() if c['op'] == 'load:x.arm'] == [START]
    assert Session('x', ASIDE).tab == 'NEW1'
    assert requests_logged() == 14


def test_what_the_page_requests_after_the_load_settles_is_charged_in_the_same_command(browser):
    opening(browser, resources=6).respond('x.modules', {**MODULES, 'resources': 4, 'statuses': [200] * 4})
    code, result, _ = doctor(browser)
    assert code == 0, result
    # the opening (6 + the document) is setup; the 4 the page made while doctor looked at it are the command's own
    assert result['request_count'] == 11 and result['setup_requests'] == 7


def test_what_the_load_requests_after_the_app_is_ready_is_part_of_the_opening(browser):
    """The app keeps loading after it first answers; that tail is setup, not the first read's (live: a fresh tab's tail
    of 10 landed in a tiny request budget; now it shows as 'tab opened')."""
    opening(browser, resources=13, quiet=False)
    browser.respond('x.state', state(resources=4)).respond('x.state', state()).respond('x.state', state())
    browser.respond('x.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert result['setup_requests'] == 18 and result['request_count'] == 18  # 13 + 4 + the document


def test_an_opening_the_kit_saw_too_late_is_charged_the_reserve(browser):
    opening(browser, resources=3, early=False).respond('x.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    # the reserve stands for what the kit could not see; the 3 it saw after installing come on top, never set off
    assert result['setup_requests'] == 23 and result['results'][0]['tab']['opening_measured'] is False


def test_an_opening_whose_timing_buffer_was_still_whole_is_measured_even_after_the_app_started(browser):
    browser.respond('opener', {'tabs': ['NEW1']})
    browser.respond('load:x.arm', {'installed_at': 478, 'location': START, 'ready_at_install': 'interactive',
                                   'app_at_install': True, 'buffer_intact': True})
    browser.respond('x.state', state(resources=13)).respond('x.state', state()).respond('x.state', state())
    browser.respond('x.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert result['setup_requests'] == 14 and result['results'][0]['tab']['opening_measured'] is True


def test_a_tab_that_closes_with_its_opener_is_reported_not_reopened_again_and_again(browser):
    opening(browser).flag(opener_end_closes_tab=True)
    code, result, _ = doctor(browser)
    assert code == 3 and 'behaviour has changed' in result['message']
    assert browser.ops().count('opener') == 1
    assert result['setup_requests'] == 20  # the page loaded x.com before it closed: charged the reserve, not 1


def test_a_load_that_does_not_finish_is_charged_the_reserve(browser):
    browser.respond('opener', {'tabs': ['NEW1']})
    browser.respond('load:x.arm', {'__raw_stdout': json.dumps({'kind': 'error', 'error': 'load_timeout',
                                                                'message': 'x'}) + '\n'})
    code, result, _ = doctor(browser)
    assert code == 3 and result['setup_requests'] == 20  # the tab was sent to x.com: its load went unmeasured


def test_an_opening_that_fails_after_the_load_is_charged_the_reserve(browser):
    opening(browser).flag(tabs_fail_after_load=True)
    code, result, _ = doctor(browser)
    assert code == 3 and result['setup_requests'] == 20


def test_an_opening_stopped_by_a_lock_is_charged_what_it_loaded(browser):
    lock = {'path': '/i/api/graphql/abc/HomeTimeline', 'status': 200, 'codes': [326], 'html': False, 'rate': None,
            'at': 5}
    opening(browser, resources=13, signals=[lock])
    code, result, _ = doctor(browser)
    assert code == 5 and result['request_count'] == 14 and result['setup_requests'] == 14


def test_an_opening_that_ends_logged_out_still_leaves_the_tab_to_the_idle_cleanup(browser):
    opening(browser, user_id=None, ct0=False)
    browser.respond('x.state', state(user_id=None, ct0=False))
    code, result, _ = doctor(browser, env={'SNS_IDLE_SECONDS': '1'})
    assert code == 4
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not {'x.close', 'x.blank'} & set(browser.ops()):
        time.sleep(0.3)
    assert {'x.close', 'x.blank'} & set(browser.ops()), browser.ops()


def test_unblock_makes_one_request_even_when_x_asks_for_more(browser):
    stand_block('account_locked')
    spent = {**RATE, 'x-rate-limit-remaining': '0'}
    asked = query_result('{"errors":[{"message":"The following features cannot be null: some_flag"}]}', status=400,
                         headers=spent)
    known_tab(browser).respond('x.query', asked).respond('x.query', query_result(VIEWER, headers=RATE))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and state_of()['block_reason'] == 'account_locked'
    assert browser.ops().count('x.query') == 1


def test_reuses_the_known_tab_and_reports_what_it_did_between_commands(browser):
    known_tab(browser, resources=7, statuses=[200] * 7).respond('x.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert 'opener' not in browser.ops() and result['request_count'] == 0
    assert result['unwatched_requests'] == 7
    assert requests_logged() == 7  # logged as seen, never charged to the command


def test_an_emptied_tab_is_replaced_by_a_new_one(browser):
    browser.tab('T1', url='about:blank')
    Session('x', ASIDE).set_tab('T1')
    opening(browser).respond('x.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert result['results'][0]['tab'] == {'target_id': 'NEW1', 'opened_now': True, 'reopened': True,
                                           'opening_measured': True}


def test_a_saved_block_stops_before_the_browser_is_touched(browser):
    stand_block('account_locked')
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked'
    assert [c for c in browser.calls() if c['op'] != 'account_status'] == []


def test_a_lock_code_the_tab_kept_blocks_for_this_account_and_closes_the_tab(browser):
    lock = {'path': '/i/api/graphql/abc/HomeTimeline', 'status': 200, 'codes': [326], 'html': False, 'rate': None,
            'at': 1792148826874}
    known_tab(browser, signals=[lock])
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked'
    person = state_of()['person']
    assert person['reason'] == 'account_locked' and person['viewer'] == ACCOUNT  # the tab's own report names it
    assert 'x.close' in browser.ops() and 'x.modules' not in browser.ops()
    assert Session('x', ASIDE).ack == 1792148826874


def test_another_operations_limit_seen_in_the_tab_is_recorded_and_doctor_goes_on(browser):
    reset = int(time.time()) + 600
    limit = {'path': '/i/api/graphql/abc/ViewerBadgeCounts', 'status': 429, 'codes': [88], 'html': False,
             'rate': {'limit': 50, 'remaining': 0, 'reset': reset}, 'at': 55}
    known_tab(browser, signals=[limit]).respond('x.modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert not state_of()['blocked']
    assert result['results'][0]['limits']['ViewerBadgeCounts']['blocked_until'] == reset
    assert Session('x', ASIDE).ack == 55


def test_a_tab_moved_to_the_access_page_is_a_lock(browser):
    known_tab(browser, location='https://x.com/account/access', moved='/account/access', app=False)
    code, result, _ = doctor(browser)
    assert code == 5 and state_of()['block_reason'] == 'account_locked'


def test_a_tab_on_the_login_flow_needs_login_and_records_no_block(browser):
    known_tab(browser, location='https://x.com/i/flow/login', moved='/i/flow/login', user_id=None)
    code, result, _ = doctor(browser)
    assert code == 4 and result['error'] == 'login'
    assert not state_of()['blocked']


def test_a_logged_out_app_needs_login(browser):
    opening(browser, user_id=None, ct0=False)
    browser.respond('x.state', state(user_id=None, ct0=False))
    code, result, _ = doctor(browser)
    assert code == 4 and result['error'] == 'login'


def test_doctor_reports_what_is_specific_to_x(browser):
    opening(browser).respond('x.modules', {**MODULES, 'generator': True, 'bearer': False})
    code, result, _ = doctor(browser)
    check = result['results'][0]
    assert code == 0 and check['operations'] == {'Viewer': 'query'}  # the page defines what the snapshot lists
    assert check['signature_generator'] is True and check['bearer'] is False
    assert check['own_request_matching'] == 'not tried yet'
    for common in ('aside', 'aside_account', 'login', 'viewer', 'blocked', 'limits', 'requests_last_hour',
                   'idle_seconds', 'data_dir', 'protection_state'):
        assert common in check, common


def test_schema_doctor_describes_the_fields_x_adds(browser):
    done = run_cli('x', 'schema', 'doctor')
    document = json.loads(done.stdout)['results'][0]
    assert done.returncode == 0 and document['object'] == 'doctor'
    listed = json.loads(run_cli('x', 'schema').stdout)['results']
    assert 'doctor' in [item['object'] for item in listed]
    opening(browser).respond('x.modules', MODULES)
    code, result, _ = doctor(browser)
    assert set(document['fields']) <= set(result['results'][0])  # what is described is what doctor reports


# --- --unblock -----------------------------------------------------------------------------------------------------

def test_unblock_lifts_the_block_after_one_clean_viewer_read(browser):
    stand_block('account_locked')
    known_tab(browser).respond('x.query', query_result(VIEWER, headers=RATE)).respond('x.modules', MODULES)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 0, result
    assert not state_of()['blocked'] and result['results'][0]['unblocked']
    assert browser.ops().count('x.query') == 1
    assert [c['args']['name'] for c in browser.calls() if c['op'] == 'x.query'] == ['Viewer']
    assert limits()['Viewer']['remaining'] == 99  # its own window kept, as from any response


def test_unblock_recovers_from_unreadable_protection_state_after_a_clean_check(browser, data_dir):
    path = data_dir / 'x' / ASIDE / 'protection'
    path.mkdir(parents=True)
    (path / 'blocks.json').write_text('{broken')
    known_tab(browser).respond('x.query', query_result(VIEWER, headers=RATE)).respond('x.modules', MODULES)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 0, result
    assert not state_of()['blocked'] and [p.read_text() for p in path.glob('blocks.json.unreadable-*')] == ['{broken']


def test_unblock_with_broken_limits_still_refuses_a_block_of_another_account(browser, data_dir):
    stand_block('account_locked', viewer=OTHER)
    (data_dir / 'x' / ASIDE / 'protection' / 'scopes.json').write_text('{broken')
    known_tab(browser).respond('x.query', query_result(VIEWER, headers=RATE))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'account_mismatch'
    assert state_of()['person']['viewer'] == OTHER


def test_requests_the_tab_made_between_commands_are_logged_even_when_it_shows_a_block(browser):
    known_tab(browser, resources=7, signals=[LOCK_SIGNAL])
    code, result, _ = doctor(browser)
    assert code == 5
    assert requests_logged() == 7


def test_unblock_without_room_in_the_viewer_limit_sends_nothing_and_keeps_the_block(browser):
    stand_limit('Viewer', remaining=0, limit=100)  # a window first: a standing block refuses every request
    stand_block('account_locked')
    known_tab(browser)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'rate_limited'
    assert 'other commands' not in result['fix']
    assert state_of()['block_reason'] == 'account_locked' and 'x.query' not in browser.ops()


def test_unblock_answered_with_429_keeps_the_block(browser):
    stand_block('account_locked')
    reset = int(time.time()) + 600
    known_tab(browser).respond('x.query', query_result('{"errors":[{"code":88}]}', status=429, headers={
        'x-rate-limit-limit': '100', 'x-rate-limit-remaining': '0', 'x-rate-limit-reset': str(reset)}))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'rate_limited'
    assert state_of()['block_reason'] == 'account_locked' and limits()['Viewer']['remaining'] == 0


def test_unblock_logged_out_keeps_the_block(browser):
    stand_block('account_locked')
    known_tab(browser, user_id=None, ct0=False)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'logged_out'
    assert state_of()['block_reason'] == 'account_locked'


def test_unblock_for_a_block_of_another_account_keeps_it_and_names_it(browser):
    stand_block('account_locked', viewer=OTHER)
    known_tab(browser)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'account_mismatch' and OTHER in result['message']
    assert 'x.query' not in browser.ops()


def test_unblock_answered_for_another_account_keeps_the_block(browser):
    stand_block('account_locked', viewer=None)
    other = {'data': {'viewer': {'user_results': {'result': {'__typename': 'User', 'rest_id': OTHER}}}}}
    known_tab(browser).respond('x.query', query_result(other, headers=RATE))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'account_mismatch'
    assert state_of()['block_reason'] == 'account_locked'


def test_unblock_with_a_lock_seen_in_the_same_call_keeps_the_block(browser):
    stand_block('account_locked')
    lock = {**LOCK_SIGNAL, 'at': 77}
    known_tab(browser).respond('x.query', query_result(VIEWER, headers=RATE, signals=[lock]))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5
    assert state_of()['block_reason'] == 'account_locked'


def test_unblock_on_the_access_page_keeps_the_block(browser):
    stand_block('account_locked')
    known_tab(browser, location='https://x.com/account/access', moved='/account/access')
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'moved'


def test_unblock_out_of_time_keeps_the_block(browser):
    stand_block('account_locked')
    known_tab(browser)
    code, result, _ = doctor(browser, '--unblock', env={'SNS_DEADLINE_SECONDS': '0.5'})
    assert code == 5 and result['verification_reason'] == 'time_limit'
    assert state_of()['block_reason'] == 'account_locked'


def test_unblock_killed_during_the_check_keeps_the_block(browser):
    stand_block('account_locked')
    known_tab(browser).respond('x.query', {'__sleep': 30, **query_result(VIEWER, headers=RATE)})
    browser.write()
    child = subprocess.Popen([sys.executable, str(CLI), 'x', 'doctor', '--unblock'],
                             env={**os.environ, **browser.env(), **ENVIRONMENT}, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True)
    deadline = time.time() + 20
    while time.time() < deadline and 'x.query' not in browser.ops():
        time.sleep(0.1)
    os.killpg(child.pid, signal.SIGKILL)
    child.wait(timeout=10)
    assert state_of()['block_reason'] == 'account_locked'


def test_unblock_records_an_unrelated_429_the_tab_saw_and_still_verifies(browser):
    """unrelated-background-429."""
    stand_block('account_locked')
    other = {'path': '/i/api/graphql/abc/ViewerBadgeCounts', 'status': 429, 'codes': [88], 'html': False,
             'rate': {'limit': 50, 'remaining': 0, 'reset': int(time.time()) + 600}, 'at': 9}
    known_tab(browser, signals=[other]).respond('x.query', query_result(VIEWER, headers=RATE))
    browser.respond('x.modules', MODULES)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 0 and not state_of()['blocked']
    assert limits()['ViewerBadgeCounts']['blocked_until'] == other['rate']['reset']


def test_unblock_without_a_fresh_viewer_answer_keeps_the_block(browser):
    """cached-store-is-not-evidence: the tab's store and module index are cached, but only X's answer clears."""
    stand_block('account_locked')
    known_tab(browser).respond('x.query', {'__raw_stdout': 'Error: other side closed\n', '__exit': 1})
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'aside'
    assert state_of()['block_reason'] == 'account_locked'


def test_unblock_of_a_block_recorded_for_no_known_account_is_lifted_by_a_clean_answer(browser):
    """verified-clean-unknown-account."""
    stand_block('challenge', viewer=None)
    known_tab(browser).respond('x.query', query_result(VIEWER, headers=RATE)).respond('x.modules', MODULES)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 0 and not state_of()['blocked']


def test_help_explains_doctor_on_its_own():
    done = subprocess.run([sys.executable, str(CLI), 'x', 'doctor', '--help'], capture_output=True, text=True)
    assert done.returncode == 0
    for word in ('--unblock', 'verification_reason', 'exit codes', '  5  '):
        assert word in done.stdout, word


def test_unblock_without_a_tab_takes_the_opening_as_its_one_check(browser):
    """Found by review (Threads and Facebook; X closes its idle tab, so this is X's usual case): with no tab to reuse,
    --unblock opened one and then sent a Viewer query as well while the block stood. The opening, judged as it loads,
    is the check; nothing more is sent."""
    stand_block('account_locked')
    opening(browser).respond('x.modules', MODULES)
    code, out, _ = run(browser, 'doctor', '--unblock')
    assert code == 0, out
    assert state_of()['person'] is None and json.loads(out)['results'][0]['unblocked'] is True
    assert queries(browser) == []


def test_an_unblock_by_opening_leaves_no_viewer_probe_behind(browser):
    """Found by the second review: the check slot reserved for the Viewer query stayed reserved when the opening was
    the check, so Viewer looked like a probe in flight and the next check was refused without a request."""
    stand_block('account_locked')
    opening(browser).respond('x.modules', MODULES)
    code, out, _ = run(browser, 'doctor', '--unblock')
    assert code == 0, out
    assert limits().get('Viewer', {}).get('status') != 'probe'
    stand_block('account_locked')
    browser.respond('x.state', state()).respond('x.query', query_result(VIEWER, headers=RATE))
    browser.respond('x.modules', MODULES)
    code, out, _ = run(browser, 'doctor', '--unblock')
    assert code == 0, out
