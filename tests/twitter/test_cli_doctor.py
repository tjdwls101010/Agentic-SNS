"""doctor through the real CLI and a scripted Aside: opening the dedicated tab, request counting, account
protection and the --unblock check (fixtures: stores.json unblock, tab_protection, session)."""
import json
import os
import signal
import subprocess
import sys
import time

from conftest import ACCOUNT, CLI, MODULES, START, environment, known_tab, opening, query_result, run_cli, state
from twitter.session import Session

LOCK = {'reason': 'account_locked', 'blocked_at': 1, 'account_id': ACCOUNT}
VIEWER = {'data': {'viewer': {'user_results': {'result': {'__typename': 'User', 'rest_id': ACCOUNT,
                                                          'core': {'screen_name': 'example_viewer'}}}}}}
RATE = {'x-rate-limit-limit': '100', 'x-rate-limit-remaining': '99', 'x-rate-limit-reset': str(int(time.time()) + 600)}


def doctor(browser, *args, env=None):
    code, out, err = run_cli(browser, 'doctor', *args, env=env)
    return code, json.loads(out), err


def block_file(data_dir, value=None):
    path = data_dir / 'protection/blocked.json'
    if value is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    return json.loads(path.read_text()) if path.exists() else None


def buckets(data_dir, value=None):
    path = data_dir / 'protection/buckets.json'
    if value is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    return json.loads(path.read_text()) if path.exists() else None


def log(data_dir):
    path = data_dir / 'protection/requests.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_opens_a_tab_without_an_agent_and_measures_what_the_load_cost(browser, data_dir):
    opening(browser, resources=13).respond('modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    check = result['results'][0]
    assert check['tab'] == {'target_id': 'NEW1', 'opened_now': True, 'reopened': False, 'opening_measured': True}
    assert check['account_id'] == ACCOUNT and check['login'] == 'ready'
    assert result['request_count'] == 14 and result['setup_requests'] == 14  # 13 seen + the document
    ops = [op for op in browser.ops() if op != 'tabs']
    assert ops[:2] == ['opener', 'load:arm'] and ops.index('opener_end') > ops.index('load:arm')
    assert [c['url'] for c in browser.calls() if c['op'] == 'load:arm'] == [START]
    assert json.loads((data_dir / 'session/default.json').read_text())['tab'] == 'NEW1'
    assert [(line['kind'], line['n']) for line in log(data_dir)] == [('tab_open', 14)]


def test_what_the_page_requests_after_the_load_settles_is_charged_in_the_same_command(browser, data_dir):
    opening(browser, resources=6).respond('modules', {**MODULES, 'resources': 4, 'statuses': [200] * 4})
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert result['request_count'] == 11 and result['setup_requests'] == 11  # 6 + the document + 4 seen later


def test_an_opening_the_kit_saw_too_late_is_charged_the_reserve(browser, data_dir):
    opening(browser, resources=3, early=False).respond('modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert result['setup_requests'] == 20 and result['results'][0]['tab']['opening_measured'] is False


def test_an_opening_whose_timing_buffer_was_still_whole_is_measured_even_after_the_app_started(browser, data_dir):
    browser.respond('opener', {'tabs': ['NEW1']})
    browser.respond('load:arm', {'installed_at': 478, 'location': START, 'ready_at_install': 'interactive',
                                 'app_at_install': True, 'buffer_intact': True})
    browser.respond('state', state(resources=13)).respond('modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert result['setup_requests'] == 14 and result['results'][0]['tab']['opening_measured'] is True


def test_a_tab_that_closes_with_its_opener_is_reported_not_reopened_again_and_again(browser, data_dir):
    opening(browser).flag(opener_end_closes_tab=True)
    code, result, _ = doctor(browser)
    assert code == 3 and 'behaviour has changed' in result['message']
    assert browser.ops().count('opener') == 1


def test_reuses_the_known_tab_and_reports_what_it_did_between_commands(browser, data_dir):
    known_tab(browser, data_dir, resources=7, statuses=[200] * 7).respond('modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert 'opener' not in browser.ops() and result['request_count'] == 0
    assert result['unwatched_requests'] == 7
    assert [(line['kind'], line['n']) for line in log(data_dir)] == [('unwatched', 7)]


def test_an_emptied_tab_is_replaced_by_a_new_one(browser, data_dir):
    browser.tab('T1', url='about:blank')
    (data_dir / 'session').mkdir(parents=True)
    (data_dir / 'session/default.json').write_text(json.dumps({'tab': 'T1'}))
    opening(browser).respond('modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert result['results'][0]['tab'] == {'target_id': 'NEW1', 'opened_now': True, 'reopened': True,
                                           'opening_measured': True}


def test_a_saved_block_stops_before_the_browser_is_touched(browser, data_dir):
    block_file(data_dir, LOCK)
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked'
    assert browser.calls() == []


def test_a_lock_code_the_tab_kept_blocks_for_this_account_and_closes_the_tab(browser, data_dir):
    lock = {'path': '/i/api/graphql/abc/HomeTimeline', 'status': 200, 'codes': [326], 'html': False, 'rate': None,
            'at': 1792148826874}
    known_tab(browser, data_dir, signals=[lock])
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked'
    record = block_file(data_dir)
    assert record['reason'] == 'account_locked' and record['account_id'] is None  # seen before the account was known
    assert 'close' in browser.ops() and 'modules' not in browser.ops()
    assert Session('default').ack == 1792148826874


def test_another_operations_limit_seen_in_the_tab_is_recorded_and_doctor_goes_on(browser, data_dir):
    reset = int(time.time()) + 600
    limit = {'path': '/i/api/graphql/abc/ViewerBadgeCounts', 'status': 429, 'codes': [88], 'html': False,
             'rate': {'limit': 50, 'remaining': 0, 'reset': reset}, 'at': 55}
    known_tab(browser, data_dir, signals=[limit]).respond('modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert block_file(data_dir) is None
    assert result['results'][0]['limits']['ViewerBadgeCounts'] == {'limit': 50, 'remaining': 0, 'reset': reset}
    assert Session('default').ack == 55


def test_a_tab_moved_to_the_access_page_is_a_lock(browser, data_dir):
    known_tab(browser, data_dir, location='https://x.com/account/access', moved='/account/access', app=False)
    code, result, _ = doctor(browser)
    assert code == 5 and block_file(data_dir)['reason'] == 'account_locked'


def test_a_tab_on_the_login_flow_needs_login_and_records_no_block(browser, data_dir):
    known_tab(browser, data_dir, location='https://x.com/i/flow/login', moved='/i/flow/login', user_id=None)
    code, result, _ = doctor(browser)
    assert code == 4 and result['error'] == 'login'
    assert block_file(data_dir) is None


def test_a_logged_out_app_needs_login(browser, data_dir):
    opening(browser, user_id=None, ct0=False)
    browser.respond('state', state(user_id=None, ct0=False))
    code, result, _ = doctor(browser)
    assert code == 4 and result['error'] == 'login'


# --- --unblock -----------------------------------------------------------------------------------------------------

def test_unblock_lifts_the_block_after_one_clean_viewer_read(browser, data_dir):
    block_file(data_dir, LOCK)
    known_tab(browser, data_dir).respond('query', query_result(VIEWER, headers=RATE)).respond('modules', MODULES)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 0, result
    assert block_file(data_dir) is None and result['results'][0]['unblocked']
    assert browser.ops().count('query') == 1
    assert [c['args']['name'] for c in browser.calls() if c['op'] == 'query'] == ['Viewer']
    assert buckets(data_dir)['Viewer']['remaining'] == 99  # its own bucket kept, as from any response


def test_unblock_without_room_in_the_viewer_limit_sends_nothing_and_keeps_the_block(browser, data_dir):
    block_file(data_dir, LOCK)
    buckets(data_dir, {'Viewer': {'limit': 100, 'remaining': 0, 'reset': int(time.time()) + 300}})
    known_tab(browser, data_dir)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'rate_limited'
    assert 'other commands' not in result['fix']
    assert block_file(data_dir) == LOCK and browser.calls() == []


def test_unblock_answered_with_429_keeps_the_block(browser, data_dir):
    block_file(data_dir, LOCK)
    known_tab(browser, data_dir).respond('query', query_result('{"errors":[{"code":88}]}', status=429, headers={
        'x-rate-limit-limit': '100', 'x-rate-limit-remaining': '0', 'x-rate-limit-reset': str(int(time.time()) + 600)}))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'rate_limited'
    assert block_file(data_dir) == LOCK and buckets(data_dir)['Viewer']['remaining'] == 0


def test_unblock_logged_out_keeps_the_block(browser, data_dir):
    block_file(data_dir, LOCK)
    known_tab(browser, data_dir, user_id=None, ct0=False)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'logged_out'
    assert block_file(data_dir) == LOCK


def test_unblock_for_a_block_of_another_account_keeps_it_and_names_it(browser, data_dir):
    block_file(data_dir, {**LOCK, 'account_id': '1000000098'})
    known_tab(browser, data_dir)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'account_mismatch' and '1000000098' in result['message']
    assert 'query' not in browser.ops()


def test_unblock_answered_for_another_account_keeps_the_block(browser, data_dir):
    block_file(data_dir, {**LOCK, 'account_id': None})
    other = {'data': {'viewer': {'user_results': {'result': {'__typename': 'User', 'rest_id': '1000000098'}}}}}
    known_tab(browser, data_dir).respond('query', query_result(other, headers=RATE))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'account_mismatch'
    assert block_file(data_dir)['reason'] == 'account_locked'


def test_unblock_with_a_lock_seen_in_the_same_call_keeps_the_block(browser, data_dir):
    block_file(data_dir, LOCK)
    lock = {'path': '/i/api/graphql/abc/HomeTimeline', 'status': 200, 'codes': [326], 'html': False, 'rate': None,
            'at': 77}
    known_tab(browser, data_dir).respond('query', query_result(VIEWER, headers=RATE, signals=[lock]))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5
    assert block_file(data_dir)['reason'] == 'account_locked'


def test_unblock_on_the_access_page_keeps_the_block(browser, data_dir):
    block_file(data_dir, LOCK)
    known_tab(browser, data_dir, location='https://x.com/account/access', moved='/account/access')
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'moved'


def test_unblock_out_of_time_keeps_the_block(browser, data_dir):
    block_file(data_dir, LOCK)
    known_tab(browser, data_dir)
    code, result, _ = doctor(browser, '--unblock', env={'TWITTER_DEADLINE_SECONDS': '0.5'})
    assert code == 5 and result['verification_reason'] == 'time_limit'
    assert block_file(data_dir) == LOCK


def test_unblock_killed_during_the_check_keeps_the_block(browser, data_dir):
    block_file(data_dir, LOCK)
    known_tab(browser, data_dir).respond('query', {'__sleep': 30, **query_result(VIEWER, headers=RATE)})
    browser.write()
    child = subprocess.Popen([sys.executable, str(CLI), 'doctor', '--unblock'], env=environment(browser),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    deadline = time.time() + 20
    while time.time() < deadline and 'query' not in browser.ops():
        time.sleep(0.1)
    os.killpg(child.pid, signal.SIGKILL)
    child.wait(timeout=10)
    assert block_file(data_dir) == LOCK


def test_help_explains_doctor_on_its_own():
    done = subprocess.run([sys.executable, str(CLI), 'doctor', '--help'], capture_output=True, text=True)
    assert done.returncode == 0
    for word in ('--unblock', 'verification_reason', 'own_request_matching', 'exit codes', '  5  '):
        assert word in done.stdout, word
