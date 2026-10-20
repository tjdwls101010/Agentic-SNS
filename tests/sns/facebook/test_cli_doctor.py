"""doctor through the real CLI and a scripted Aside: opening the dedicated tab, request counting, account protection and
the --unblock check. The shared doctor (fields common to every platform, a saved block reported without touching the
browser, the unblock check's one request) is the core's: core/test_reading.py, core/test_protection.py. Here: what
Facebook adds, and that its check really asks Facebook (the old skill cleared a block with no check at all)."""
import json
import os
import signal
import subprocess
import sys
import time

from sns.session import Session
from tests.sns.facebook.scenes import (ACCOUNT, ASIDE, ENVIRONMENT, HOME, graphql_body, guard, known_tab,
                                       look, opening, queries, query_result, run, stand_block, stand_block_and_hold,
                                       state_of, story)
from tests.sns.support.cli import CLI, run_cli

OTHER = '1000000098'
MODULES = {'CometNewsFeedPaginationQuery': '123', 'SearchCometResultsPaginatedResultsQuery': None}
FEED = ['viewer', 'news_feed']


def doctor(browser, *args, env=None):
    browser.respond('facebook.modules', MODULES)
    code, out, err = run(browser, 'doctor', *args, env=env)
    return code, json.loads(out), err


def clean_feed(**extra):
    return query_result(graphql_body(FEED, [story('A')], False), **extra)


def test_opens_the_dedicated_tab_when_none_is_known(browser):
    opening(browser, 'T9', resources=29)
    code, result, _ = doctor(browser)
    assert code == 0 and result['ok'] is True and result['stop_reason'] == 'ready'
    check = result['results'][0]
    assert check['viewer'] == ACCOUNT and check['login'] == 'ready' and check['aside_account'] == ASIDE
    assert check['tab'] == {'target_id': 'T9', 'opened_now': True}
    assert result['request_count'] == 30 and result['setup_requests'] == 30  # its document and 29 the page made
    assert [c['op'] for c in browser.calls() if c['op'] != 'account_status'] == [
        'tabs', 'open', 'tabs', 'facebook.state', 'facebook.modules']
    assert check['queries']['CometNewsFeedPaginationQuery'] == 'live in the tab'
    assert check['queries']['SearchCometResultsPaginatedResultsQuery'] == 'stored'
    assert Session('facebook', ASIDE).tab == 'T9'


def test_the_open_goes_to_the_home_screen_with_the_account_the_state_names(browser):
    opening(browser, 'T9')
    doctor(browser)
    [opened] = [c for c in browser.calls() if c['op'] == 'open']
    assert opened['url'] == HOME and opened['account'] == ASIDE


def test_reuses_the_known_tab_and_reports_what_it_did_between_commands(browser):
    known_tab(browser, resources=7, statuses=[200] * 7)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert 'open' not in browser.ops() and result['request_count'] == 0
    assert result['unwatched_requests'] == 7
    assert guard().recent()['last_day'] == 7  # logged as seen, never charged to the command


def test_a_users_own_facebook_tab_is_never_used(browser):
    browser.tab('USER_TAB', 'https://www.facebook.com/someone')
    opening(browser, 'T2')
    code, result, _ = doctor(browser)
    assert code == 0 and result['results'][0]['tab']['target_id'] == 'T2'
    assert all(c.get('tab') != 'USER_TAB' for c in browser.calls())


def test_an_emptied_tab_is_replaced_by_a_new_one(browser):
    """The idle cleanup empties the tab to about:blank; the next command finds it blank and opens a fresh one."""
    browser.tab('T1', url='about:blank')
    Session('facebook', ASIDE).set_tab('T1')
    opening(browser, 'NEW1')
    code, result, _ = doctor(browser)
    assert code == 0 and result['results'][0]['tab'] == {'target_id': 'NEW1', 'opened_now': True}


def test_logged_out_tab_is_exit_4_and_records_no_block(browser):
    opening(browser, 'T3', location='https://www.facebook.com/login/', user_id=None)
    code, result, _ = doctor(browser)
    assert code == 4 and result['ok'] is False and result['error'] == 'login' and 'Log in' in result['fix']
    assert not state_of()['blocked']


def test_checkpoint_in_the_tab_blocks_the_account_and_empties_the_tab(browser):
    opening(browser, 'T4', location='https://www.facebook.com/checkpoint/123/', user_id=None)
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked'
    person = state_of()['person']
    assert person['reason'] == 'checkpoint' and 'facebook.blank' in browser.ops()


def test_a_rate_limit_among_the_tabs_requests_holds_the_account_until_it_passes(browser):
    known_tab(browser, resources=3, statuses=[200, 429, 200])
    code, result, _ = doctor(browser)
    assert code == 5 and 'rate-limited' in result['message']
    assert state_of()['hold'] and not state_of()['person'] and 'facebook.modules' not in browser.ops()


def test_a_saved_block_is_reported_without_touching_the_browser(browser):
    stand_block()
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked' and result['fix'].startswith('Stop requests')
    assert [c for c in browser.calls() if c['op'] != 'account_status'] == []


def test_doctor_reports_what_is_specific_to_facebook(browser):
    known_tab(browser)
    code, result, _ = doctor(browser)
    check = result['results'][0]
    for key in ('aside', 'tab', 'login', 'viewer', 'blocked', 'queries', 'idle_seconds', 'data_dir', 'protection_state',
                'holds_personal_data', 'requests_last_hour', 'requests_last_day'):
        assert key in check, key
    assert 'blocks' in check['protection_state'] and 'facebook' in check['protection_state']


def test_schema_doctor_describes_the_fields_facebook_adds(browser):
    done = run_cli('facebook', 'schema', 'doctor')
    document = json.loads(done.stdout)['results'][0]
    assert done.returncode == 0 and document['object'] == 'doctor'
    assert 'doctor' in [item['object'] for item in json.loads(run_cli('facebook', 'schema').stdout)['results']]
    known_tab(browser)
    code, result, _ = doctor(browser)
    assert set(document['fields']) <= set(result['results'][0])  # what is described is what doctor reports


def test_missing_aside_is_exit_3(browser, data_dir):
    code, result, _ = doctor(browser, env={'SNS_ASIDE_BIN': str(data_dir / 'no-such-aside')})
    assert code == 3 and result['error'] == 'aside'


def test_aside_failure_is_exit_3_without_raw_output(browser):
    browser.tab('T6')
    Session('facebook', ASIDE).set_tab('T6')
    browser.respond('facebook.state', {'__raw_stdout': 'Error: other side closed SECRET-COOKIE-VALUE\n', '__exit': 1})
    code, result, err = doctor(browser)
    assert code == 3 and 'connection' in result['message']
    assert 'SECRET' not in json.dumps(result) and 'SECRET' not in err


def test_the_aside_account_comes_from_the_environment_and_owns_its_state(browser, data_dir):
    opening(browser, 'T7')
    code, _, _ = doctor(browser, env={'SNS_ASIDE_ACCOUNT': 'u1'})
    assert code == 0
    assert {c['account'] for c in browser.calls() if c['op'] != 'account_status'} == {'u1'}
    assert (data_dir / 'facebook' / 'u1' / 'session' / 'tab.json').exists()
    assert not (data_dir / 'facebook' / 'u0').exists()


# --- doctor --unblock -------------------------------------------------------------------------------------------------

def test_unblock_lifts_the_block_only_after_one_clean_read_for_the_same_account(browser):
    """Intended change: the old --unblock deleted the block without asking Facebook anything."""
    stand_block()
    known_tab(browser).respond('facebook.query', clean_feed())
    code, result, _ = doctor(browser, '--unblock')
    assert code == 0, result
    assert not state_of()['blocked'] and result['results'][0]['unblocked']
    assert [q['args']['name'] for q in queries(browser)] == ['CometNewsFeedPaginationQuery']
    assert queries(browser)[0]['args']['variables']['count'] == 1


def test_unblock_asks_facebook_even_when_the_block_was_recorded_for_no_known_account(browser):
    stand_block(viewer=None)
    known_tab(browser).respond('facebook.query', clean_feed())
    code, result, _ = doctor(browser, '--unblock')
    assert code == 0 and not state_of()['blocked'] and len(queries(browser)) == 1


def test_unblock_makes_one_request_even_when_facebook_asks_for_more(browser):
    """A temporary rejection or a refused query id would be retried or relearned by a normal read; the check's answer
    decides, so the block stays and nothing more is sent."""
    stand_block()
    known_tab(browser).respond('facebook.query', query_result('for (;;);' + json.dumps({'error': 1357054})))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and state_of()['person']['reason'] == 'checkpoint' and len(queries(browser)) == 1
    look(browser).respond('facebook.query', query_result(json.dumps({'errors': [{'message': 'PersistedQueryNotFound'}]}),
                                                         source='stored'))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and len(queries(browser)) == 2 and 'facebook.route' not in browser.ops()


def test_unblock_answered_with_a_checkpoint_keeps_the_block(browser):
    stand_block()
    known_tab(browser).respond('facebook.query', query_result(json.dumps(
        {'checkpoint_url': 'https://www.facebook.com/checkpoint/1/'})))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'moved' and state_of()['person']['reason'] == 'checkpoint'


def test_unblock_with_the_tab_on_the_checkpoint_screen_keeps_the_block(browser):
    stand_block()
    known_tab(browser, location='https://www.facebook.com/checkpoint/1/', user_id=None)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'moved' and queries(browser) == []


def test_unblock_answered_with_429_keeps_the_block_and_holds_the_account(browser):
    stand_block()
    known_tab(browser).respond('facebook.query', query_result('', status=429))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'rate_limited'
    assert state_of()['person'] and state_of()['hold']


def test_unblock_during_a_hold_sends_nothing_and_keeps_both(browser):
    stand_block_and_hold()
    known_tab(browser)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'rate_limited' and queries(browser) == []
    assert state_of()['person'] and state_of()['hold']


def test_unblock_logged_out_keeps_the_block(browser):
    stand_block()
    known_tab(browser, location='https://www.facebook.com/login/', user_id=None)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'logged_out' and state_of()['person']


def test_unblock_for_a_block_of_another_account_keeps_it_and_names_it(browser):
    stand_block(viewer=OTHER)
    known_tab(browser)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'account_mismatch'
    assert state_of()['person']['viewer'] == OTHER and queries(browser) == []


def test_unblock_answered_for_another_account_keeps_the_block(browser):
    stand_block()
    known_tab(browser).respond('facebook.query', clean_feed(user_id=OTHER))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'account_mismatch' and state_of()['person']


def test_unblock_without_a_fresh_answer_keeps_the_block(browser):
    """The tab's state is evidence of who is logged in, not of Facebook accepting the account: only an answer clears."""
    stand_block()
    known_tab(browser).respond('facebook.query', {'__raw_stdout': 'Error: other side closed\n', '__exit': 1})
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and result['verification_reason'] == 'aside' and state_of()['person']


def test_unblock_out_of_time_keeps_the_block(browser):
    stand_block()
    known_tab(browser)
    code, result, _ = doctor(browser, '--unblock', env={'SNS_DEADLINE_SECONDS': '0.5'})
    assert code == 5 and result['verification_reason'] == 'time_limit' and state_of()['person']


def test_unblock_killed_during_the_check_keeps_the_block(browser):
    stand_block()
    known_tab(browser).respond('facebook.query', {'__sleep': 30, **clean_feed()})
    browser.write()
    child = subprocess.Popen([sys.executable, str(CLI), 'facebook', 'doctor', '--unblock'],
                             env={**os.environ, **browser.env(), **ENVIRONMENT}, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True)
    deadline = time.time() + 20
    while time.time() < deadline and 'facebook.query' not in browser.ops():
        time.sleep(0.1)
    os.killpg(child.pid, signal.SIGKILL)
    child.wait(timeout=10)
    assert state_of()['person']['reason'] == 'checkpoint'


def test_unblock_recovers_from_unreadable_protection_state_after_a_clean_check(browser, data_dir):
    path = data_dir / 'facebook' / ASIDE / 'protection'
    path.mkdir(parents=True)
    (path / 'blocks.json').write_text('{broken')
    known_tab(browser).respond('facebook.query', clean_feed())
    code, result, _ = doctor(browser, '--unblock')
    assert code == 0, result
    assert not state_of()['blocked'] and [p.read_text() for p in path.glob('blocks.json.unreadable-*')] == ['{broken']


def test_unblock_records_the_check_in_the_request_log(browser):
    """A request log now exists for Facebook (appendix C): the check is a request like any other."""
    stand_block()
    known_tab(browser).respond('facebook.query', clean_feed())
    before = guard().recent()['last_day']
    doctor(browser, '--unblock')
    assert guard().recent()['last_day'] - before >= 1
    lines = (guard().directory / 'requests.jsonl').read_text().splitlines()
    assert any(json.loads(line).get('kind') == 'unblock_check' for line in lines)


def test_help_explains_doctor_on_its_own():
    done = subprocess.run([sys.executable, str(CLI), 'facebook', 'doctor', '--help'], capture_output=True, text=True)
    assert done.returncode == 0
    for word in ('--unblock', 'verification_reason', 'exit codes', '  5  '):
        assert word in done.stdout, word


def test_unblock_without_a_tab_takes_the_opening_as_its_one_check(browser):
    """Found by review: with no tab to reuse, --unblock opened one (the page's own ~30 requests) and then sent a feed
    query as well, while the block stood. Opening the tab loads the site the way a person does and its first look is
    judged (checkpoint, login, account): that is the check, and nothing more is sent."""
    stand_block()
    opening(browser).respond('facebook.modules', MODULES)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 0, result
    assert not state_of()['blocked'] and result['results'][0]['unblocked']
    assert queries(browser) == []


def test_unblock_without_a_tab_keeps_the_block_when_the_opened_page_is_a_checkpoint(browser):
    stand_block()
    opening(browser, location='https://www.facebook.com/checkpoint/123/', user_id=None)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and state_of()['person'] is not None and queries(browser) == []
