"""Failure paths through the real CLI and a scripted Aside: background limits by bucket, a lock with a limit, a lost
tab, recovery and its cap, an account change mid-command, a resume state that cannot be saved, concurrent starts, and
the help's shape (plan: stop table, account protection semantics, operation rotation recovery, P3 completion)."""
import json
import os
import stat
import subprocess
import sys
import time

from conftest import CLI, MODULES, environment, known_tab, opening, query_result, run_cli, state

RATE = {'x-rate-limit-limit': '500', 'x-rate-limit-remaining': '499', 'x-rate-limit-reset': str(int(time.time()) + 900)}
A = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'author_a', 'name': 'A'}}


def home(ids, bottom='CUR1'):
    entries = [{'entryId': f'tweet-{i}', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {
        'result': {'__typename': 'Tweet', 'rest_id': i, 'core': {'user_results': {'result': A}},
                   'legacy': {'full_text': f'post {i}', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026'}}}}}} for i in ids]
    if bottom:
        entries.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}})
    return {'data': {'home': {'home_timeline_urt': {'instructions': [{'type': 'TimelineAddEntries', 'entries': entries}]}}}}


def signal(op, status=429, codes=(88,), at=101):
    return {'path': f'/i/api/graphql/abc/{op}', 'status': status, 'codes': list(codes), 'html': False,
            'rate': {'limit': 50, 'remaining': 0, 'reset': int(time.time()) + 600}, 'at': at}


def queries(browser):
    return [c['args']['name'] for c in browser.calls() if c['op'] == 'query']


# --- background limits are each operation's own (plan review ②) --------------------------------------------------

def test_another_operations_background_limit_does_not_stop_this_read(browser, data_dir):
    known_tab(browser, data_dir, signals=[signal('ViewerBadgeCounts')]).respond('query', query_result(home(['1']), headers=RATE))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 0, out
    assert json.loads((data_dir / 'protection/buckets.json').read_text())['ViewerBadgeCounts']['remaining'] == 0


def test_this_operations_background_limit_stops_it_with_exit_10_before_any_request(browser, data_dir):
    known_tab(browser, data_dir, signals=[signal('HomeTimeline')])
    code, out, _ = run_cli(browser, 'feed')
    assert code == 10 and queries(browser) == []
    assert not (data_dir / 'protection/blocked.json').exists()


def test_this_operations_limit_seen_after_records_is_a_resumable_stop(browser, data_dir):
    spent = {**RATE, 'x-rate-limit-remaining': '0'}
    for result in (query_result(home(['1']), headers=spent),  # our own response's headers
                   query_result(home(['1']), signals=[signal('HomeTimeline')])):  # the app's own request, in the background
        known_tab(browser, data_dir).respond('query', result)
        before = len(queries(browser))
        code, out, _ = run_cli(browser, 'feed', '--limit', '40')
        assert code == 0, out
        assert 'stopped=rate_limited' in out.splitlines()[0] and out.splitlines()[-1].startswith('more: ')
        assert len(queries(browser)) == before + 1  # the second page is not asked for
        (data_dir / 'protection/buckets.json').unlink()


def test_a_lock_seen_with_a_limit_is_a_block(browser, data_dir):
    known_tab(browser, data_dir, signals=[signal('ViewerBadgeCounts', at=1), signal('HomeTimeline', 200, (326,), at=2)])
    code, out, _ = run_cli(browser, 'feed')
    assert code == 5 and json.loads((data_dir / 'protection/blocked.json').read_text())['reason'] == 'account_locked'


# --- the tab ----------------------------------------------------------------------------------------------------

def test_a_tab_lost_mid_call_is_reopened_once_and_the_read_goes_on(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', {'__raw_stdout': json.dumps({'kind': 'error', 'error': 'tab_missing', 'message': 'gone'}) + '\n'})
    opening(browser, target='NEW2')
    browser.respond('query', query_result(home(['1']), headers=RATE))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 0, out
    assert 'tab opened (+14 requests)' in out.splitlines()[0] and 'requests=1/25' in out.splitlines()[0]


def test_two_commands_starting_together_open_one_tab(browser, data_dir):
    browser.respond('opener', {'tabs': ['NEW1'], '__sleep': 1.5})
    browser.respond('load:arm', {'installed_at': 300, 'location': 'https://x.com/i/xskill', 'ready_at_install': 'loading',
                                 'app_at_install': False})
    browser.respond('state', state(resources=13)).respond('state', state()).respond('state', state())
    browser.respond('modules', MODULES)
    browser.respond('state', state()).respond('modules', MODULES)  # the second command's look at the same tab
    browser.write()
    env = environment(browser)
    first = subprocess.Popen([sys.executable, str(CLI), 'doctor'], env=env, stdout=subprocess.PIPE, text=True)
    time.sleep(0.3)
    second = subprocess.Popen([sys.executable, str(CLI), 'doctor'], env=env, stdout=subprocess.PIPE, text=True)
    results = [json.loads(p.communicate(timeout=60)[0]) for p in (first, second)]
    assert all(r['ok'] for r in results), results
    assert browser.ops().count('opener') == 1
    assert {r['results'][0]['tab']['target_id'] for r in results} == {'NEW1'}


# --- recovery ---------------------------------------------------------------------------------------------------

def test_a_live_id_x_refuses_reloads_the_tab_once_then_reads(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result('{"errors":[{"message":"Query: Unspecified"}]}'))
    browser.respond('load:arm', {'installed_at': 300, 'location': 'https://x.com/i/xskill', 'ready_at_install': 'loading',
                                 'app_at_install': False})
    browser.respond('state', state(resources=12)).respond('state', state()).respond('state', state())
    browser.respond('query', query_result(home(['1']), headers=RATE))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 0, out
    assert 'load:arm' in browser.ops() and queries(browser) == ['HomeTimeline', 'HomeTimeline']
    assert 'tab opened (+13 requests)' in out.splitlines()[0]  # the reload is setup, outside the budget


def test_recovery_is_capped_at_one_reload_a_command(browser, data_dir):
    rotated = query_result('{"errors":[{"message":"Query: Unspecified"}]}')
    known_tab(browser, data_dir).respond('query', rotated)
    browser.respond('load:arm', {'installed_at': 300, 'location': 'https://x.com/i/xskill', 'ready_at_install': 'loading',
                                 'app_at_install': False})
    browser.respond('state', state(resources=12)).respond('state', state()).respond('state', state())
    browser.respond('query', rotated)
    code, out, _ = run_cli(browser, 'feed')
    assert code == 6 and 'update' in json.loads(out)['fix']
    assert browser.ops().count('load:arm') == 1


def test_a_stored_id_x_refuses_needs_an_update_without_guessing(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result('{"errors":[{"message":"Query: Unspecified"}]}',
                                                               used={'source': 'stored', 'query_id': 'OLD', 'features': []}))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 6 and 'load:arm' not in browser.ops()


# --- the account, the resume state ----------------------------------------------------------------------------------

def test_an_account_change_mid_command_stops_with_exit_4(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(home(['1']), headers=RATE))
    browser.respond('query', {**query_result(home(['2'], bottom='C2'), headers=RATE), 'login': True, 'explicit': 0,
                              'missing': 'a logged-in session'})
    code, out, _ = run_cli(browser, 'feed', '--limit', '40')
    assert code == 4 and 'post 1' in out


def test_a_resume_state_that_cannot_be_saved_is_partial_exit_8_without_a_more_line(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(home(['1']), headers=RATE))
    handles = data_dir / 'handles'
    handles.mkdir(parents=True)
    handles.chmod(stat.S_IRUSR | stat.S_IXUSR)  # read-only: the handle file cannot be written
    try:
        code, out, _ = run_cli(browser, 'feed')
    finally:
        handles.chmod(0o700)
    assert code == 8 and 'post 1' in out and 'more:' not in out


# --- the help -------------------------------------------------------------------------------------------------------

def test_the_command_map_fits_one_screen_and_every_command_explains_its_exits():
    root = subprocess.run([sys.executable, str(CLI), '--help'], capture_output=True, text=True, env=os.environ.copy())
    assert root.returncode == 0 and len(root.stdout.splitlines()) <= 40, len(root.stdout.splitlines())
    names = [line.split()[0] for line in root.stdout.splitlines() if line.startswith('    ') and line.split()]
    for name in names:
        page = subprocess.run([sys.executable, str(CLI), name, '--help'], capture_output=True, text=True)
        assert page.returncode == 0 and 'exit codes:' in page.stdout, name
        assert 'request' in page.stdout, name  # each says what it costs (schema: no request)


# --- the deadline, recorded buckets, a reopened tab (P3 review 1, 6, 7) ------------------------------------------------

def test_a_browser_call_cut_by_the_deadline_before_any_result_is_a_time_limit(browser, data_dir):
    known_tab(browser, data_dir).respond('query', {**query_result(home(['1']), headers=RATE), '__sleep': 10})
    started = time.monotonic()
    code, out, _ = run_cli(browser, 'feed', env={'TWITTER_DEADLINE_SECONDS': '5'})
    envelope = json.loads(out)
    assert code == 6 and envelope['stop_reason'] == 'time_limit', envelope
    assert time.monotonic() - started < 9


def test_a_browser_call_cut_by_the_deadline_after_results_is_a_resumable_stop(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(home(['1']), headers=RATE))
    browser.respond('query', {**query_result(home(['2'], bottom='C2'), headers=RATE), '__sleep': 12})
    code, out, _ = run_cli(browser, 'feed', '--limit', '40', env={'TWITTER_DEADLINE_SECONDS': '8'})
    assert code == 0, out
    assert 'stopped=time_limit' in out.splitlines()[0] and out.splitlines()[-1].startswith('more: ')


def test_the_own_responses_limit_is_recorded_even_when_a_lock_stops_the_command(browser, data_dir):
    lock = signal('ViewerBadgeCounts', 200, (326,))
    spent = {**RATE, 'x-rate-limit-remaining': '0'}
    known_tab(browser, data_dir).respond('query', query_result('{"errors":[{"code":88}]}', status=429, headers=spent,
                                                               signals=[lock]))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 5
    assert json.loads((data_dir / 'protection/buckets.json').read_text())['HomeTimeline']['remaining'] == 0


def test_a_tab_lost_mid_command_is_replaced_by_the_one_another_command_already_opened(browser, data_dir):
    known_tab(browser, data_dir)
    browser.tab('T2')
    session = data_dir / 'session/default.json'
    lost = json.dumps({'kind': 'error', 'error': 'tab_missing', 'message': 'gone'}) + '\n'
    browser.respond('query', {'__raw_stdout': lost, '__write': {str(session): json.dumps({'tab': 'T2'})}})
    browser.respond('state', state()).respond('query', query_result(home(['1']), headers=RATE))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 0, out
    assert 'opener' not in browser.ops()
    assert [c['tab'] for c in browser.calls() if c['op'] == 'query'] == ['T1', 'T2']
    assert json.loads(session.read_text())['tab'] == 'T2'


def test_a_resume_state_that_cannot_be_saved_is_named_even_after_a_resumable_stop(browser, data_dir):
    spent = {**RATE, 'x-rate-limit-remaining': '0'}
    known_tab(browser, data_dir).respond('query', query_result(home(['1']), headers=spent))
    handles = data_dir / 'handles'
    handles.mkdir(parents=True)
    handles.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        code, out, _ = run_cli(browser, 'feed', '--limit', '40', '--json')
    finally:
        handles.chmod(0o700)
    envelope = json.loads(out)
    assert code == 8 and 'save a handle' in envelope['message'] and 'next' not in envelope


def test_a_lock_in_the_same_report_is_acted_on_even_when_the_own_limit_cannot_be_recorded(browser, data_dir):
    """The bucket write comes first; if protection state turns unreadable under it, the lock must still close the tab."""
    lock = signal('ViewerBadgeCounts', 200, (326,))
    buckets = data_dir / 'protection/buckets.json'
    known_tab(browser, data_dir).respond('query', {**query_result(home(['1']), headers=RATE, signals=[lock]),
                                                   '__write': {str(buckets): 'not json'}})
    code, out, _ = run_cli(browser, 'feed')
    assert code == 5 and 'close' in browser.ops()


def test_an_aside_failure_near_the_deadline_is_still_an_aside_failure(browser, data_dir):
    browser.tab('T1')
    (data_dir / 'session').mkdir(parents=True)
    (data_dir / 'session/default.json').write_text(json.dumps({'tab': 'T1'}))
    browser.respond('state', {'__sleep': 1.9, '__raw_stdout': 'Error: other side closed\n', '__exit': 1})
    code, out, _ = run_cli(browser, 'feed', env={'TWITTER_DEADLINE_SECONDS': '2.5'})
    assert code == 3 and json.loads(out)['error'] == 'aside'


def test_a_lock_in_the_own_response_is_acted_on_even_when_its_limit_cannot_be_recorded(browser, data_dir):
    buckets = data_dir / 'protection/buckets.json'
    known_tab(browser, data_dir).respond('query', {**query_result('{"errors":[{"code":326}]}', headers=RATE),
                                                   '__write': {str(buckets): 'not json'}})
    code, out, _ = run_cli(browser, 'feed')
    assert code == 5 and 'close' in browser.ops()
    assert json.loads((data_dir / 'protection/blocked.json').read_text())['reason'] == 'account_locked'


def test_a_limit_that_cannot_be_recorded_does_not_hide_a_lock_seen_after_it(browser, data_dir):
    (data_dir / 'protection').mkdir(parents=True)
    (data_dir / 'protection/buckets.json').write_text('not json')
    known_tab(browser, data_dir, signals=[signal('NotificationsTimeline', at=1), signal('ViewerBadgeCounts', 200, (326,), at=2)])
    code, out, _ = run_cli(browser, 'feed')
    assert code == 5 and 'close' in browser.ops()
    assert json.loads((data_dir / 'protection/blocked.json').read_text())['account_id'] == '1000000099'
