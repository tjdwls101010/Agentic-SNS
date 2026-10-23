"""Failure paths through the real CLI and a scripted Aside: background limits by operation, a lock with a limit, a lost
tab, recovery and its cap, an account change mid-command, a resume state that cannot be saved, concurrent starts, and
the help's shape. The shared mechanics (holds, scope stops after records, the deadline, handles) are the core's:
core/test_reading.py, core/test_protection.py; here is what X's client does with them."""
import json
import os
import stat
import subprocess
import sys
import time

import pytest

from sns.session import Session
from tests.sns.support.cli import CLI
from tests.sns.x.scenes import (ASIDE, ENVIRONMENT, MODULES, START, known_tab, limits, opening, query_result,
                                queries, rerun, run, stand_block, state, state_of)

RATE = {'x-rate-limit-limit': '500', 'x-rate-limit-remaining': '499', 'x-rate-limit-reset': str(int(time.time()) + 900)}
A = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'author_a', 'name': 'A'}}
OTHER = '1000000098'
LOST = json.dumps({'kind': 'error', 'error': 'tab_missing', 'message': 'gone'}) + '\n'


def home(ids, bottom='CUR1'):
    entries = [{'entryId': f'tweet-{i}', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {
        'result': {'__typename': 'Tweet', 'rest_id': i, 'core': {'user_results': {'result': A}},
                   'legacy': {'full_text': f'post {i}', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026'}}}}}} for i in ids]
    if bottom:
        entries.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}})
    return {'data': {'home': {'home_timeline_urt': {'instructions': [{'type': 'TimelineAddEntries', 'entries': entries}]}}}}


def signal(op, status=429, codes=(88,), at=101, reset=None):
    return {'path': f'/i/api/graphql/abc/{op}', 'status': status, 'codes': list(codes), 'html': False,
            'rate': {'limit': 50, 'remaining': 0, 'reset': reset or int(time.time()) + 600}, 'at': at}


def names(browser):
    return [c['args']['name'] for c in queries(browser)]


# --- background limits are each operation's own (plan review ②) --------------------------------------------------

def test_another_operations_background_limit_does_not_stop_this_read(browser):
    other = signal('ViewerBadgeCounts')
    known_tab(browser, signals=[other]).respond('x.query', query_result(home(['1']), headers=RATE))
    code, out, _ = run(browser, 'feed')
    assert code == 0, out
    assert limits()['ViewerBadgeCounts']['blocked_until'] == other['rate']['reset']  # that operation only
    assert not state_of()['blocked']


def test_this_operations_background_limit_stops_it_with_exit_10_before_any_request(browser):
    own = signal('HomeTimeline')
    known_tab(browser, signals=[own])
    code, out, _ = run(browser, 'feed')
    envelope = json.loads(out)
    assert code == 10 and queries(browser) == []
    assert envelope['error'] == 'scope_limit' and envelope['limit']['scope'] == 'HomeTimeline'
    assert envelope['limit']['reset'] == own['rate']['reset']
    assert not state_of()['blocked']


@pytest.mark.parametrize('own_headers', [True, False], ids=['own response', 'background request of the app'])
def test_this_operations_limit_seen_after_records_is_a_resumable_stop(browser, own_headers):
    spent = {**RATE, 'x-rate-limit-remaining': '0'}
    result = query_result(home(['1']), headers=spent) if own_headers else \
        query_result(home(['1']), signals=[signal('HomeTimeline')])
    known_tab(browser).respond('x.query', result)
    code, out, _ = run(browser, 'feed', '--limit', '40')
    assert code == 0, out
    assert 'stopped=rate_limited' in out.splitlines()[0] and out.splitlines()[-1].startswith('more: ')
    assert len(queries(browser)) == 1  # the second page is not asked for


def test_a_lock_seen_with_a_limit_is_a_block(browser):
    known_tab(browser, signals=[signal('ViewerBadgeCounts', at=1), signal('HomeTimeline', 200, (326,), at=2)])
    code, out, _ = run(browser, 'feed')
    assert code == 5 and state_of()['block_reason'] == 'account_locked'


# --- the tab ----------------------------------------------------------------------------------------------------

def test_a_tab_lost_mid_call_is_reopened_once_and_the_read_goes_on(browser):
    known_tab(browser)
    browser.respond('x.query', {'__raw_stdout': LOST})
    opening(browser, target='NEW2')
    browser.respond('x.query', query_result(home(['1']), headers=RATE))
    code, out, _ = run(browser, 'feed')
    assert code == 0, out
    head = out.splitlines()[0]
    assert 'tab opened (+14 requests)' in head and 'requests=1' in head and 'requests=1 ' in head + ' '


def test_two_commands_starting_together_open_one_tab(browser):
    browser.respond('opener', {'tabs': ['NEW1'], '__sleep': 1.5})
    browser.respond('load:x.arm', {'installed_at': 300, 'location': START, 'ready_at_install': 'loading',
                                   'app_at_install': False})
    browser.respond('x.state', state(resources=13)).respond('x.state', state()).respond('x.state', state())
    browser.respond('x.modules', MODULES)
    browser.respond('x.state', state()).respond('x.modules', MODULES)  # the second command's look at the same tab
    browser.write()
    env = {**os.environ, **browser.env(), **ENVIRONMENT}
    first = subprocess.Popen([sys.executable, str(CLI), 'x', 'doctor'], env=env, stdout=subprocess.PIPE, text=True)
    time.sleep(0.3)
    second = subprocess.Popen([sys.executable, str(CLI), 'x', 'doctor'], env=env, stdout=subprocess.PIPE, text=True)
    results = [json.loads(p.communicate(timeout=60)[0]) for p in (first, second)]
    assert all(r['ok'] for r in results), results
    assert browser.ops().count('opener') == 1
    assert {r['results'][0]['tab']['target_id'] for r in results} == {'NEW1'}


# --- recovery ---------------------------------------------------------------------------------------------------

ROTATED = '{"errors":[{"message":"Query: Unspecified"}]}'


def reload_answers(browser):
    browser.respond('load:x.arm', {'installed_at': 300, 'location': START, 'ready_at_install': 'loading',
                                   'app_at_install': False})
    browser.respond('x.state', state(resources=12)).respond('x.state', state()).respond('x.state', state())


def test_a_live_id_x_refuses_reloads_the_tab_once_then_reads(browser):
    known_tab(browser).respond('x.query', query_result(ROTATED))
    reload_answers(browser)
    browser.respond('x.query', query_result(home(['1']), headers=RATE))
    code, out, _ = run(browser, 'feed')
    assert code == 0, out
    assert 'load:x.arm' in browser.ops() and names(browser) == ['HomeTimeline', 'HomeTimeline']
    assert 'tab opened (+13 requests)' in out.splitlines()[0]  # the reload is setup, counted apart


def test_recovery_is_capped_at_one_reload_a_command(browser):
    rotated = query_result(ROTATED)
    known_tab(browser).respond('x.query', rotated)
    reload_answers(browser)
    browser.respond('x.query', rotated)
    code, out, _ = run(browser, 'feed')
    assert code == 6 and 'update' in json.loads(out)['fix']
    assert browser.ops().count('load:x.arm') == 1


def test_a_stored_id_x_refuses_needs_an_update_without_guessing(browser):
    known_tab(browser).respond('x.query', query_result(ROTATED, used={'source': 'stored', 'query_id': 'OLD',
                                                                      'features': []}))
    code, out, _ = run(browser, 'feed')
    assert code == 6 and 'load:x.arm' not in browser.ops()


# --- the account, the resume state ----------------------------------------------------------------------------------

def test_a_login_lost_mid_command_stops_with_exit_4(browser):
    known_tab(browser).respond('x.query', query_result(home(['1']), headers=RATE))
    browser.respond('x.query', {**query_result(home(['2'], bottom='C2'), headers=RATE), 'login': True, 'explicit': 0,
                                'missing': 'a logged-in session'})
    code, out, _ = run(browser, 'feed', '--limit', '40')
    assert code == 4 and 'post 1' in out


def test_another_x_account_mid_command_is_exit_4_account_changed_and_keeps_the_records(browser):
    """The tab vanishes after the first page and the one opened meanwhile is logged in as someone else."""
    known_tab(browser).respond('x.query', query_result(home(['1']), headers=RATE))
    browser.respond('x.query', {'__raw_stdout': LOST})
    opening(browser, target='NEW2', user_id=OTHER)
    code, out, _ = run(browser, 'feed', '--limit', '40')
    assert code == 4 and 'post 1' in out and 'account changed' in out
    assert 'more:' not in out


def test_a_continued_reading_under_another_x_account_is_exit_4_not_2(browser):
    """The handle remembers the X account it was read with; the account is compared outside the handle's context."""
    known_tab(browser).respond('x.query', query_result(home(['1']), headers=RATE))
    code, out, _ = run(browser, 'feed')
    more = out.splitlines()[-1]
    known_tab(browser, user_id=OTHER)
    code, out, _ = rerun(browser, more)
    envelope = json.loads(out)
    assert code == 4 and envelope['error'] == 'login' and OTHER in envelope['message']
    assert len(queries(browser)) == 1  # no request for the new account


def test_a_resume_state_that_cannot_be_saved_is_partial_exit_8_without_a_more_line(browser, data_dir):
    known_tab(browser).respond('x.query', query_result(home(['1']), headers=RATE))
    handles = data_dir / 'handles'
    handles.mkdir(parents=True)
    handles.chmod(stat.S_IRUSR | stat.S_IXUSR)  # read-only: the handle file cannot be written
    try:
        code, out, _ = run(browser, 'feed')
    finally:
        handles.chmod(0o700)
    assert code == 8 and 'post 1' in out and 'more:' not in out


# --- the Aside account ----------------------------------------------------------------------------------------

def test_state_is_kept_under_the_resolved_aside_account_never_default(browser, data_dir):
    known_tab(browser).respond('x.query', query_result(home(['1']), headers=RATE))
    code, out, _ = run(browser, 'feed')
    assert code == 0, out
    assert (data_dir / 'x' / ASIDE / 'session' / 'tab.json').is_file()
    assert (data_dir / 'x' / ASIDE / 'protection').is_dir() and not (data_dir / 'x' / 'default').exists()


def test_naming_the_active_account_shares_the_state_of_not_naming_it(browser):
    stand_block('account_locked')  # recorded for the account Aside reports as active (u0)
    for env in (None, {'SNS_ASIDE_ACCOUNT': ASIDE}):
        code, out, _ = run(browser, 'doctor', env=env)
        assert code == 5 and json.loads(out)['error'] == 'blocked', env


# --- the help -------------------------------------------------------------------------------------------------------

def test_every_x_command_explains_its_exits_and_says_what_it_costs():
    root = subprocess.run([sys.executable, str(CLI), 'x', '--help'], capture_output=True, text=True,
                          env=os.environ.copy())
    assert root.returncode == 0
    commands = [line.split()[0] for line in root.stdout.rsplit('<command>', 1)[1].splitlines()
                if line.startswith('    ') and line.split()]
    assert {'feed', 'post', 'doctor', 'schema'} <= set(commands)
    for name in commands:
        page = subprocess.run([sys.executable, str(CLI), 'x', name, '--help'], capture_output=True, text=True)
        assert page.returncode == 0 and 'exit codes:' in page.stdout, name
        assert 'request' in page.stdout, name  # each says what it costs (schema: no request)


# --- the deadline, recorded limits, a reopened tab (P3 review 1, 6, 7) ------------------------------------------------

def test_a_browser_call_cut_by_the_deadline_before_any_result_is_a_time_limit(browser):
    known_tab(browser).respond('x.query', {**query_result(home(['1']), headers=RATE), '__sleep': 10})
    started = time.monotonic()
    code, out, _ = run(browser, 'feed', env={'SNS_DEADLINE_SECONDS': '5'})
    envelope = json.loads(out)
    assert code == 6 and envelope['stop_reason'] == 'time_limit', envelope
    assert time.monotonic() - started < 9


def test_a_browser_call_cut_by_the_deadline_after_results_is_a_resumable_stop(browser):
    known_tab(browser).respond('x.query', query_result(home(['1']), headers=RATE))
    browser.respond('x.query', {**query_result(home(['2'], bottom='C2'), headers=RATE), '__sleep': 12})
    code, out, _ = run(browser, 'feed', '--limit', '40', env={'SNS_DEADLINE_SECONDS': '8'})
    assert code == 0, out
    assert 'stopped=time_limit' in out.splitlines()[0] and out.splitlines()[-1].startswith('more: ')


def test_the_own_responses_limit_is_recorded_even_when_a_lock_stops_the_command(browser):
    lock = signal('ViewerBadgeCounts', 200, (326,))
    spent = {**RATE, 'x-rate-limit-remaining': '0'}
    known_tab(browser).respond('x.query', query_result('{"errors":[{"code":88}]}', status=429, headers=spent,
                                                       signals=[lock]))
    code, out, _ = run(browser, 'feed')
    assert code == 5
    assert limits()['HomeTimeline']['remaining'] == 0


def test_a_tab_lost_mid_command_is_replaced_by_the_one_another_command_already_opened(browser):
    known_tab(browser)
    browser.tab('T2', url=START)
    record = Session('x', ASIDE).directory / 'tab.json'
    browser.respond('x.query', {'__raw_stdout': LOST, '__write': {str(record): json.dumps({'tab': 'T2'})}})
    browser.respond('x.state', state()).respond('x.query', query_result(home(['1']), headers=RATE))
    code, out, _ = run(browser, 'feed')
    assert code == 0, out
    assert 'opener' not in browser.ops()
    assert [c['tab'] for c in queries(browser)] == ['T1', 'T2']
    assert Session('x', ASIDE).tab == 'T2'


def test_a_resume_state_that_cannot_be_saved_is_named_even_after_a_resumable_stop(browser, data_dir):
    spent = {**RATE, 'x-rate-limit-remaining': '0'}
    known_tab(browser).respond('x.query', query_result(home(['1']), headers=spent))
    handles = data_dir / 'handles'
    handles.mkdir(parents=True)
    handles.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        code, out, _ = run(browser, 'feed', '--limit', '40', '--json')
    finally:
        handles.chmod(0o700)
    envelope = json.loads(out)
    # partial (8): records were read and where to continue could not be saved. The pipeline keeps the first failure,
    # the limit's, as the message (the old skill named the unsaved handle instead).
    assert code == 8 and envelope['error'] == 'partial' and envelope['stop_reason'] == 'rate_limited'
    assert 'next' not in envelope


def test_a_lock_in_the_same_report_is_acted_on_even_when_the_own_limit_cannot_be_recorded(browser, data_dir):
    """The window write is deferred to the end of the slot: if protection state turns unreadable under it, the lock
    must still be recorded and the tab closed first."""
    lock = signal('ViewerBadgeCounts', 200, (326,))
    scopes = data_dir / 'x' / ASIDE / 'protection' / 'scopes.json'
    known_tab(browser).respond('x.query', {**query_result(home(['1']), headers=RATE, signals=[lock]),
                                           '__write': {str(scopes): 'not json'}})
    code, out, _ = run(browser, 'feed')
    assert code == 5 and 'x.close' in browser.ops()
    assert json.loads((data_dir / 'x' / ASIDE / 'protection' / 'blocks.json').read_text())['person']['reason'] == \
        'account_locked'


def test_an_aside_failure_near_the_deadline_is_still_an_aside_failure(browser):
    browser.tab('T1', url=START)
    Session('x', ASIDE).set_tab('T1')
    browser.respond('x.state', {'__sleep': 1.9, '__raw_stdout': 'Error: other side closed\n', '__exit': 1})
    code, out, _ = run(browser, 'feed', env={'SNS_DEADLINE_SECONDS': '2.5'})
    assert code == 3 and json.loads(out)['error'] == 'aside'


def test_a_lock_in_the_own_response_is_acted_on_even_when_its_limit_cannot_be_recorded(browser, data_dir):
    scopes = data_dir / 'x' / ASIDE / 'protection' / 'scopes.json'
    known_tab(browser).respond('x.query', {**query_result('{"errors":[{"code":326}]}', headers=RATE),
                                           '__write': {str(scopes): 'not json'}})
    code, out, _ = run(browser, 'feed')
    assert code == 5 and 'x.close' in browser.ops()
    assert json.loads((data_dir / 'x' / ASIDE / 'protection' / 'blocks.json').read_text())['person']['reason'] == \
        'account_locked'


def test_unreadable_limits_refuse_the_command_before_the_tab_is_looked_at(browser, data_dir):
    """Fail closed (core): state that cannot be read stops every request, so a lock the tab holds is not read first —
    the old skill recorded it from the tab in this case; now the person clears the state with doctor --unblock."""
    path = data_dir / 'x' / ASIDE / 'protection'
    path.mkdir(parents=True)
    (path / 'scopes.json').write_text('not json')
    known_tab(browser, signals=[signal('NotificationsTimeline', at=1), signal('ViewerBadgeCounts', 200, (326,), at=2)])
    code, out, _ = run(browser, 'feed')
    envelope = json.loads(out)
    assert code == 5 and envelope['error'] == 'blocked' and 'doctor' in envelope['fix']
    assert queries(browser) == [] and 'x.state' not in browser.ops()


def test_the_own_limit_in_an_answer_shown_to_another_account_is_still_recorded(browser):
    """Found by review of the same order in Threads: the account check ran before the answer was judged, so X's limit
    in an answer that came back under another account was never recorded."""
    spent = {**RATE, 'x-rate-limit-remaining': '0'}
    known_tab(browser).respond('x.query', query_result('{"errors":[{"code":88}]}', status=429, headers=spent,
                                                       user_id='1000000077'))
    code, out, _ = run(browser, 'feed')
    assert code == 4, out  # the changed account is what the command ends with (a login outranks a scope limit)
    assert limits()['HomeTimeline']['remaining'] == 0


def test_a_lock_in_an_answer_shown_to_another_account_is_still_recorded(browser):
    known_tab(browser).respond('x.query', query_result('{"errors":[{"code":326,"message":"locked"}]}', status=403,
                                                       user_id='1000000077'))
    code, out, _ = run(browser, 'feed')
    assert code == 5 and state_of()['person'] is not None, out


def test_a_lock_in_an_answer_is_recorded_for_the_account_that_answered(browser):
    known_tab(browser).respond('x.query', query_result('{"errors":[{"code":326,"message":"locked"}]}', status=403,
                                                       user_id='1000000077'))
    code, out, _ = run(browser, 'feed')
    assert code == 5 and state_of()['person']['viewer'] == '1000000077', out
