"""doctor through the real cli.py and a fake Aside."""
import json
import time

from conftest import run_cli

STATE = {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'runtime': True, 'resources': 0}


def doctor(browser, *args, env=None):
    browser.respond('modules', {'CometNewsFeedPaginationQuery': '123', 'SearchCometResultsPaginatedResultsQuery': None})
    code, out, err = run_cli(browser, 'doctor', *args, env=env)
    return code, json.loads(out), err


def test_opens_the_dedicated_tab_when_none_is_known(browser, data_dir):
    browser.respond('open', {'tab': {'id': 'T9', 'url': 'https://www.facebook.com/'}})
    browser.respond('state', {**STATE, 'resources': 29})
    code, result, _ = doctor(browser)
    assert code == 0 and result['ok'] is True and result['stop_reason'] == 'ready'
    check = result['results'][0]
    assert check['account_id'] == '1000123' and check['login'] == 'ready'
    assert check['tab'] == {'target_id': 'T9', 'opened_now': True}
    assert result['request_count'] == 30  # the tab's page load: its document and 29 requests the page made itself
    assert [c['op'] for c in browser.calls()] == ['tabs', 'open', 'tabs', 'state', 'modules']
    assert check['queries']['CometNewsFeedPaginationQuery'] == 'live in the tab'
    saved = json.loads((data_dir / 'session/default.json').read_text())
    assert saved['tab'] == 'T9'


def test_reuses_the_known_tab_without_requests(browser, data_dir):
    browser.tab('T1')
    (data_dir / 'session').mkdir(parents=True)
    (data_dir / 'session/default.json').write_text(json.dumps({'tab': 'T1', 'queries': {}}))
    browser.respond('state', STATE)
    code, result, _ = doctor(browser)
    assert code == 0 and result['request_count'] == 0
    assert result['results'][0]['tab'] == {'target_id': 'T1', 'opened_now': False}
    assert [c['op'] for c in browser.calls()] == ['tabs', 'state', 'modules']


def test_a_users_own_facebook_tab_is_never_used(browser, data_dir):
    browser.tab('USER_TAB', 'https://www.facebook.com/someone')
    browser.respond('open', {'tab': {'id': 'T2', 'url': 'https://www.facebook.com/'}})
    browser.respond('state', STATE)
    code, result, _ = doctor(browser)
    assert code == 0 and result['results'][0]['tab']['target_id'] == 'T2'
    assert all(c.get('tab') != 'USER_TAB' for c in browser.calls())


def test_logged_out_tab_is_exit_4(browser, data_dir):
    browser.respond('open', {'tab': {'id': 'T3', 'url': 'https://www.facebook.com/login/'}})
    browser.respond('state', {**STATE, 'location': 'https://www.facebook.com/login/', 'user_id': None})
    code, result, _ = doctor(browser)
    assert code == 4 and result['ok'] is False and result['error'] == 'login'
    assert 'Log in' in result['fix']


def test_checkpoint_in_the_tab_blocks_the_account(browser, data_dir):
    browser.respond('open', {'tab': {'id': 'T4', 'url': 'https://www.facebook.com/checkpoint/123/'}})
    browser.respond('state', {**STATE, 'location': 'https://www.facebook.com/checkpoint/123/', 'user_id': None})
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked'
    record = json.loads((data_dir / 'protection/blocked.json').read_text())
    assert record['reason'] == 'checkpoint' and record['expires_at'] is None


def test_a_saved_block_is_reported_without_touching_the_browser(browser, data_dir):
    (data_dir / 'protection').mkdir(parents=True)
    (data_dir / 'protection/blocked.json').write_text(json.dumps({'reason': 'rate_limit', 'blocked_at': time.time(),
                                                                  'expires_at': time.time() + 900}))
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked' and 'rate-limited' in result['message']
    assert browser.calls() == []


def test_unblock_clears_a_checkpoint_then_checks(browser, data_dir):
    (data_dir / 'protection').mkdir(parents=True)
    (data_dir / 'protection/blocked.json').write_text(json.dumps({'reason': 'checkpoint', 'blocked_at': 1,
                                                                  'expires_at': None}))
    browser.respond('open', {'tab': {'id': 'T5', 'url': 'https://www.facebook.com/'}})
    browser.respond('state', STATE)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 0 and result['results'][0]['blocked'] is False


def test_missing_aside_is_exit_3(browser, data_dir):
    code, result, _ = doctor(browser, env={'FACEBOOK_ASIDE_BIN': str(data_dir / 'no-such-aside')})
    assert code == 3 and result['error'] == 'aside'


def test_aside_failure_is_exit_3_without_raw_output(browser, data_dir):
    browser.tab('T6')
    (data_dir / 'session').mkdir(parents=True)
    (data_dir / 'session/default.json').write_text(json.dumps({'tab': 'T6', 'queries': {}}))
    browser.respond('state', {'__raw_stdout': 'Error: other side closed SECRET-COOKIE-VALUE\n', '__exit': 1})
    code, result, err = doctor(browser)
    assert code == 3 and 'connection' in result['message']
    assert 'SECRET' not in json.dumps(result) and 'SECRET' not in err


def test_the_aside_account_comes_from_the_environment(browser, data_dir):
    browser.respond('open', {'tab': {'id': 'T7', 'url': 'https://www.facebook.com/'}})
    browser.respond('state', STATE)
    code, _, _ = doctor(browser, env={'FACEBOOK_ASIDE_ACCOUNT': 'u1'})
    assert code == 0
    assert {c['account'] for c in browser.calls()} == {'u1'}
    assert (data_dir / 'session/u1.json').exists()
