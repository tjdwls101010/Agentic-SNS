"""doctor through the real CLI and a scripted Aside: the dedicated tab, request counting, and account protection."""
import json
import os
import subprocess
import sys
import time

from conftest import (ACCOUNT, CLI, LOGGED_IN_DOCUMENT, START, environment, known_tab, opening, run_cli, state)

CHECKPOINT_BODY = json.dumps({'message': 'checkpoint_required', 'checkpoint_url': 'https://www.threads.com/challenge/x/',
                              'status': 'fail'})
CHECKPOINT = {'reason': 'checkpoint', 'blocked_at': 1, 'expires_at': None}
MODULES = {'live': {'BarcelonaFeedDirectQuery': {'doc_id': '1', 'kind': None}}, 'resources': 0, 'statuses': [],
           'signals': [], 'location': START}


def doctor(browser, *args, env=None):
    code, out, err = run_cli(browser, 'doctor', *args, env=env)
    return code, json.loads(out), err


def block_file(data_dir, value=None):
    path = data_dir / 'protection/blocked.json'
    if value is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    return json.loads(path.read_text()) if path.exists() else None


def log(data_dir):
    path = data_dir / 'protection/requests.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_opens_a_tab_on_the_start_screen_and_prepays_it(browser, data_dir):
    opening(browser).respond('modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    check = result['results'][0]
    assert check['tab'] == {'target_id': 'NEW1', 'opened_now': True, 'reopened': False}
    assert check['account_id'] == ACCOUNT and check['login'] == 'ready'
    assert result['request_count'] == 40 and result['tab_opened_requests'] == 40  # 34 seen, 40 prepaid
    assert [c['url'] for c in browser.calls() if c['op'] == 'open'] == [START]
    assert json.loads((data_dir / 'session/default.json').read_text())['tab'] == 'NEW1'
    assert [(line['kind'], line['n']) for line in log(data_dir)] == [('tab_open', 40)]


def test_reuses_the_known_tab_and_reports_what_it_did_between_commands(browser, data_dir):
    known_tab(browser, data_dir, resources=7, statuses=[200] * 7).respond('modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert 'open' not in browser.ops() and result['request_count'] == 0
    assert result['unwatched_requests'] == 7
    assert [(line['kind'], line['n']) for line in log(data_dir)] == [('unwatched', 7)]


def test_a_tab_emptied_earlier_is_loaded_again_and_counted_like_opening(browser, data_dir):
    browser.tab('T1', url='about:blank')
    (data_dir / 'session').mkdir(parents=True)
    (data_dir / 'session/default.json').write_text(json.dumps({'tab': 'T1', 'queries': {}}))
    browser.respond('navigate', {'navigating': True, 'explicit': 0, 'resources': 0, 'statuses': [], 'signals': [],
                                 'location': 'about:blank'})
    browser.respond('state', state(resources=30, document=LOGGED_IN_DOCUMENT)).respond('modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert result['results'][0]['tab'] == {'target_id': 'T1', 'opened_now': True, 'reopened': True}
    assert result['tab_opened_requests'] == 40 and 'open' not in browser.ops()
    assert [c['args']['url'] for c in browser.calls() if c['op'] == 'navigate'] == [START]


def test_a_saved_block_stops_before_the_browser_is_touched(browser, data_dir):
    block_file(data_dir, CHECKPOINT)
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked'
    assert browser.calls() == []


def test_a_checkpoint_body_the_tab_kept_blocks_and_empties_the_tab(browser, data_dir):
    signal = {'url': 'https://www.threads.com/graphql/query', 'status': 200, 'summary': CHECKPOINT_BODY, 'at': 1792148826874}
    known_tab(browser, data_dir, signals=[signal])
    code, result, _ = doctor(browser)
    assert code == 5 and result['error'] == 'blocked' and 'checkpoint' in result['message']
    assert block_file(data_dir)['reason'] == 'checkpoint'
    assert 'blank' in browser.ops() and 'modules' not in browser.ops()
    assert json.loads((data_dir / 'session/default.json').read_text())['ack'] == 1792148826874


def test_an_ordinary_signal_is_acknowledged_without_a_block(browser, data_dir):
    signal = {'url': 'https://www.threads.com/graphql/query', 'status': 200, 'at': 55,
              'summary': '{"errors": [{"message": "A field could not be resolved", "severity": "WARNING"}]}'}
    known_tab(browser, data_dir, signals=[signal]).respond('modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert block_file(data_dir) is None
    assert json.loads((data_dir / 'session/default.json').read_text())['ack'] == 55


def test_a_tab_on_the_challenge_page_is_a_checkpoint(browser, data_dir):
    known_tab(browser, data_dir, location='https://www.threads.com/challenge/?next=%2F', runtime=False, user_id=None)
    code, result, _ = doctor(browser)
    assert code == 5 and block_file(data_dir)['reason'] == 'checkpoint'


def test_a_tab_on_the_login_page_needs_login_and_records_no_block(browser, data_dir):
    known_tab(browser, data_dir, location='https://www.threads.com/accounts/login/?next=%2F', user_id=None)
    code, result, _ = doctor(browser)
    assert code == 4 and result['error'] == 'login'
    assert block_file(data_dir) is None


def test_a_new_tab_showing_checkpoint_markers_blocks_before_any_query(browser, data_dir):
    browser.respond('open', {'tab': {'id': 'NEW1', 'url': START}})
    browser.respond('state', state(resources=20, document='<html><form action="/challenge/action/"></form></html>'))
    code, result, _ = doctor(browser)
    assert code == 5 and block_file(data_dir)['reason'] == 'checkpoint'
    assert 'modules' not in browser.ops() and 'query' not in browser.ops()


def test_a_429_while_the_new_tab_loaded_is_a_rate_limit(browser, data_dir):
    opening(browser, statuses=[200, 429, 200])
    code, result, _ = doctor(browser)
    assert code == 5 and block_file(data_dir)['reason'] == 'rate_limit'


def test_unblock_lifts_the_block_only_after_a_clean_check(browser, data_dir):
    block_file(data_dir, CHECKPOINT)
    known_tab(browser, data_dir)
    browser.respond('page', {'status': 200, 'url': START, 'body': LOGGED_IN_DOCUMENT, 'explicit': 1, 'resources': 1,
                             'statuses': [200], 'signals': [], 'location': START})
    browser.respond('modules', MODULES)
    code, result, _ = doctor(browser, '--unblock')
    assert code == 0, result
    assert block_file(data_dir) is None and result['results'][0]['unblocked'] is True
    assert browser.ops().index('page') < browser.ops().index('modules')
    assert ('unblock_check', 1) in [(line['kind'], line['n']) for line in log(data_dir)]


def test_unblock_keeps_the_block_when_the_check_sees_a_checkpoint(browser, data_dir):
    block_file(data_dir, CHECKPOINT)
    known_tab(browser, data_dir)
    browser.respond('page', {'status': 200, 'url': 'https://www.threads.com/challenge/x/', 'body': '', 'explicit': 1,
                             'resources': 1, 'statuses': [200], 'signals': [], 'location': START})
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and block_file(data_dir)['reason'] == 'checkpoint'


def test_unblock_keeps_the_block_when_the_tab_cannot_be_opened(browser, data_dir):
    block_file(data_dir, CHECKPOINT)
    browser.respond('open', {'__fail': True})
    code, result, _ = doctor(browser, '--unblock')
    assert code == 3 and block_file(data_dir)['reason'] == 'checkpoint'


def test_two_commands_starting_together_open_one_tab(browser, data_dir):
    browser.respond('open', {'tab': {'id': 'NEW1', 'url': START}, '__sleep': 1.5})
    browser.respond('state', state(resources=30, document=LOGGED_IN_DOCUMENT)).respond('modules', MODULES)
    browser.respond('state', state()).respond('modules', MODULES)
    browser.write()
    first = subprocess.Popen([sys.executable, str(CLI), 'doctor'], env=environment(browser), stdout=subprocess.PIPE,
                             text=True)
    time.sleep(0.5)
    second = subprocess.Popen([sys.executable, str(CLI), 'doctor'], env=environment(browser), stdout=subprocess.PIPE,
                              text=True)
    results = [json.loads(p.communicate(timeout=60)[0]) for p in (first, second)]
    assert [r['ok'] for r in results] == [True, True], results
    assert browser.ops().count('open') == 1
    assert {r['results'][0]['tab']['target_id'] for r in results} == {'NEW1'}


def test_an_unreadable_session_opens_one_tab_and_says_so(browser, data_dir):
    (data_dir / 'session').mkdir(parents=True)
    (data_dir / 'session/default.json').write_text('not json')
    browser.tab('OLD', url=START)  # a Threads tab the skill cannot vouch for is not adopted
    opening(browser).respond('modules', MODULES)
    code, result, _ = doctor(browser)
    assert code == 0, result
    assert result['session_reset'] is True and result['results'][0]['tab']['target_id'] == 'NEW1'


def test_the_idle_blanker_empties_the_tab_after_the_last_command(browser, data_dir):
    known_tab(browser, data_dir).respond('modules', MODULES)
    browser.respond('blank', {'blanked': True, 'resources': 2, 'statuses': [200, 200], 'signals': [], 'location': START})
    code, result, _ = doctor(browser, env={'THREADS_IDLE_SECONDS': '1'})
    assert code == 0
    deadline = time.time() + 20
    while 'blank' not in browser.ops() and time.time() < deadline:
        time.sleep(0.3)
    assert 'blank' in browser.ops()
    assert ('unwatched', 2) in [(line['kind'], line['n']) for line in log(data_dir)]


def test_the_idle_blanker_leaves_a_tab_a_newer_command_uses(browser, data_dir):
    known_tab(browser, data_dir).respond('modules', MODULES)
    code, _, _ = doctor(browser)
    assert code == 0
    code, out, _ = run_cli(browser, 'idle', '--token', 'an-older-token', '--after', '0')
    assert code == 0 and json.loads(out)['outcome'] == 'newer command'
    assert 'blank' not in browser.ops()


# --- review findings (shared contracts) ---

RATE_BODY = json.dumps({'error': {'code': 4, 'message': 'Please wait a few minutes before you try again later.'}})
LOGIN_BODY = json.dumps({'errors': [{'message': 'login_required'}]})


def page_result(body, url=START, status=200, **extra):
    return {'status': status, 'url': url, 'body': body, 'explicit': 1, 'resources': 1, 'statuses': [200],
            'signals': [], 'location': START, **extra}


def test_unblock_keeps_a_checkpoint_when_the_check_returns_a_rate_limit_body(browser, data_dir):
    block_file(data_dir, CHECKPOINT)
    known_tab(browser, data_dir).respond('page', page_result(RATE_BODY))
    code, result, _ = doctor(browser, '--unblock')
    assert code == 5 and block_file(data_dir)['reason'] == 'checkpoint'


def test_unblock_keeps_the_block_when_the_check_proves_nothing(browser, data_dir):
    block_file(data_dir, CHECKPOINT)
    known_tab(browser, data_dir).respond('page', page_result(''))
    code, result, _ = doctor(browser, '--unblock')
    assert code != 0 and block_file(data_dir)['reason'] == 'checkpoint'


def test_the_strongest_signal_wins_and_is_recorded_before_acknowledging(browser, data_dir):
    signals = [{'url': 'https://www.threads.com/graphql/query', 'status': 200, 'summary': LOGIN_BODY, 'at': 10},
               {'url': 'https://www.threads.com/graphql/query', 'status': 200, 'summary': RATE_BODY, 'at': 11}]
    known_tab(browser, data_dir, signals=signals)
    code, result, _ = doctor(browser)
    assert code == 5 and block_file(data_dir)['reason'] == 'rate_limit'
    assert 'blank' in browser.ops()
    assert json.loads((data_dir / 'session/default.json').read_text())['ack'] == 11


def test_a_429_seen_while_the_tab_was_still_loading_is_recorded(browser, data_dir):
    browser.respond('open', {'tab': {'id': 'NEW1', 'url': START}})
    browser.respond('state', state(resources=25, statuses=[200, 429], runtime=False, user_id=None))
    browser.respond('state', state(resources=8, document=LOGGED_IN_DOCUMENT))
    code, result, _ = doctor(browser)
    assert code == 5 and block_file(data_dir)['reason'] == 'rate_limit'
    assert result['tab_opened_requests'] == 40  # 34 seen over two looks, within the reservation


def test_a_429_in_any_report_is_recorded(browser, data_dir):
    known_tab(browser, data_dir).respond('modules', {**MODULES, 'resources': 1, 'statuses': [429]})
    code, result, _ = doctor(browser)
    assert code == 5 and block_file(data_dir)['reason'] == 'rate_limit'


def test_a_reused_tab_showing_a_checkpoint_form_is_a_checkpoint(browser, data_dir):
    known_tab(browser, data_dir, markers=['<form method="post" action="/challenge/'])
    code, result, _ = doctor(browser)
    assert code == 5 and block_file(data_dir)['reason'] == 'checkpoint'


def test_the_idle_blanker_empties_the_tab_even_while_a_block_stands(browser, data_dir):
    known_tab(browser, data_dir).respond('modules', MODULES)
    code, _, _ = doctor(browser)
    block_file(data_dir, CHECKPOINT)
    token = json.loads((data_dir / 'session/default.json').read_text())['token']
    browser.respond('blank', {'blanked': True, 'resources': 0, 'statuses': [], 'signals': [], 'location': START})
    code, out, _ = run_cli(browser, 'idle', '--token', token, '--after', '0')
    assert json.loads(out)['outcome'] == 'blanked' and 'blank' in browser.ops()


def test_the_idle_blanker_waits_while_another_command_is_still_running(browser, data_dir):
    known_tab(browser, data_dir).respond('modules', MODULES)
    code, _, _ = doctor(browser)
    session = json.loads((data_dir / 'session/default.json').read_text())
    session['active'] = {'a-long-command': os.getpid()}  # this test process stands for a command still running
    (data_dir / 'session/default.json').write_text(json.dumps(session))
    code, out, _ = run_cli(browser, 'idle', '--token', session['token'], '--after', '0')
    assert json.loads(out)['outcome'] == 'busy' and 'blank' not in browser.ops()


def test_a_blank_that_fails_once_is_retried_and_confirmed(browser, data_dir):
    signal = {'url': 'https://www.threads.com/graphql/query', 'status': 200, 'summary': RATE_BODY, 'at': 5}
    known_tab(browser, data_dir, signals=[signal])
    browser.respond('blank', {'__raw_stdout': '{"kind": "error", "error": "evaluate_failed", "message": "x"}\n'})
    browser.respond('blank', {'blanked': True, 'resources': 0, 'statuses': [], 'signals': [], 'location': START})
    code, result, _ = doctor(browser)
    assert code == 5 and browser.ops().count('blank') == 2


def test_unblock_and_a_starting_command_take_the_locks_in_one_order(browser, data_dir):
    block_file(data_dir, CHECKPOINT)
    known_tab(browser, data_dir).respond('page', page_result(LOGGED_IN_DOCUMENT)).respond('modules', MODULES)
    browser.write()
    holder = subprocess.Popen([sys.executable, '-c', (
        'import time\nfrom threads.session import Session\nfrom threads import guard\ns = Session("default")\n'
        'with s.opening():\n    print("in", flush=True)\n    time.sleep(1.5)\n'
        '    try:\n        with guard.Guard(1).observe():\n            pass\n    except Exception:\n        pass\n'
        'print("done", flush=True)\n')], env={**environment(browser), 'PYTHONPATH': str(CLI.parent)},
        stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == 'in'
    unblock = subprocess.Popen([sys.executable, str(CLI), 'doctor', '--unblock'], env=environment(browser),
                               stdout=subprocess.PIPE, text=True)
    out, _ = unblock.communicate(timeout=30)  # a deadlock would time out here
    assert holder.communicate(timeout=30)[0].strip() == 'done'
    assert json.loads(out)['ok'] is True and block_file(data_dir) is None
