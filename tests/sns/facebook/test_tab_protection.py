"""The dedicated tab is watched for what Facebook does to the account while no command runs: a 429 on any of its
requests (even one that finished between commands or on a reload), a checkpoint, a login wall. The tab's own ledger is
test_snippets.py; here the client reads it, records it in protection before anything is sent, and the idle cleanup
empties the tab (Facebook's tab does not close, so it is blanked) after taking in what it saw."""
import json
import os
import subprocess
import sys
import time

from sns.session import Session
from tests.sns.facebook.scenes import (ACCOUNT, ASIDE, ENVIRONMENT, HOME, graphql_body, guard, known_tab, opening,
                                       page_result, queries, query_result, run, state_of, story)
from tests.sns.support.cli import CLI, run_cli

FEED = ['viewer', 'news_feed']


def page(ids):
    return query_result(graphql_body(FEED, [story(i) for i in ids], False))


def test_a_429_seen_while_no_command_ran_holds_the_account_before_any_query(browser):
    known_tab(browser, statuses=[200, 429], resources=2)
    code, out, _ = run(browser, 'feed')
    assert code == 5 and queries(browser) == []
    assert state_of()['hold'] and not state_of()['person']


def test_a_429_in_the_history_the_ledger_first_met_is_seen_too(browser):
    known_tab(browser, unwatched=[200, 429])
    code, out, _ = run(browser, 'feed')
    assert code == 5 and queries(browser) == [] and state_of()['hold']


def test_the_tabs_memory_of_a_429_alone_holds_the_account(browser):
    known_tab(browser, limited=True)
    code, out, _ = run(browser, 'feed')
    assert code == 5 and queries(browser) == [] and state_of()['hold']


def test_a_known_rate_limit_is_not_followed_by_a_request(browser):
    """The page function itself refused to send (it had already seen the 429): the request is given back, not counted,
    and the hold is recorded."""
    known_tab(browser)
    browser.respond('facebook.query', {'stopped': 'rate_limit', 'statuses': [429], 'unwatched': [], 'limited': True,
                                       'explicit': 0, 'resources': 0})
    code, out, _ = run(browser, 'feed', '--json')
    result = json.loads(out)
    assert code == 5 and state_of()['hold'] and result['request_count'] == 0


def test_a_stopped_call_gives_its_request_back_but_keeps_the_pages_own(browser):
    known_tab(browser)
    browser.respond('facebook.query', {'stopped': 'rate_limit', 'statuses': [200] * 4 + [429], 'unwatched': [],
                                       'limited': True, 'explicit': 0, 'resources': 5})
    code, out, _ = run(browser, 'feed', '--json')
    result = json.loads(out)
    assert code == 5 and result['request_count'] == 5 and guard().recent()['last_day'] == 5  # none of them is the skill's


def test_a_route_the_tab_refused_because_of_a_rate_limit_is_a_rate_limit_not_a_login(browser):
    known_tab(browser)
    rejected = json.dumps({'errors': [{'message': 'PersistedQueryNotFound', 'code': 1675002}]})
    browser.respond('facebook.query', query_result(rejected, source='stored', doc_id='9'))
    browser.respond('facebook.route', {'stopped': 'rate_limit', 'statuses': [429], 'unwatched': [], 'limited': True,
                                       'explicit': 0, 'resources': 1})
    code, out, _ = run(browser, 'feed')
    assert code == 5 and json.loads(out)['error'] == 'blocked' and state_of()['hold']


def test_a_hold_the_tab_only_remembers_is_not_renewed_by_every_look(browser):
    """The tab remembers a 429 for 30 minutes; a look five minutes after it ends the hold where the 429 would have, not
    thirty minutes after the look."""
    seen = (time.time() - 300) * 1000
    known_tab(browser, limited=True, limited_at=seen)
    code, out, _ = run(browser, 'feed')
    assert code == 5
    assert abs(state_of()['hold']['until'] - (seen / 1000 + 1800)) < 2


def test_a_checkpoint_the_tab_met_by_itself_is_recorded_before_the_idle_cleanup_blanks_it(browser):
    known_tab(browser, location='https://www.facebook.com/checkpoint/1/', user_id=None)
    code, result = idle(browser)
    assert result['outcome'] == 'emptied' and state_of()['person']['reason'] == 'checkpoint'


def test_a_page_that_went_to_the_checkpoint_screen_while_it_answered_is_a_block(browser):
    known_tab(browser)
    browser.respond('facebook.query', {**page(['A']), 'location': 'https://www.facebook.com/checkpoint/1/'})
    code, out, _ = run(browser, 'feed')
    assert code == 5 and state_of()['person']['reason'] == 'checkpoint' and 'facebook.blank' in browser.ops()


def test_a_page_that_went_to_the_login_screen_while_it_answered_is_a_login_wall(browser):
    known_tab(browser)
    browser.respond('facebook.query', {**page(['A']), 'location': 'https://www.facebook.com/login/'})
    code, out, _ = run(browser, 'feed')
    assert code == 4 and not state_of()['blocked']


def test_a_profile_whose_name_starts_like_the_checkpoint_screen_is_read_like_any_other(browser):
    known_tab(browser)
    browser.respond('facebook.page', {**page_result('https://www.facebook.com/checkpointsoftware',
                                                    '<script>{"userID":"1000777"}</script>'),
                                      'location': 'https://www.facebook.com/checkpointsoftware'})
    browser.respond('facebook.query', {**query_result(graphql_body(['node', 'timeline_list_feed_units'], [story('A')],
                                                                   False)),
                                       'location': 'https://www.facebook.com/checkpointsoftware'})
    code, out, _ = run(browser, 'profile', 'CheckPointSoftware')
    assert code == 0 and not state_of()['blocked']


def test_a_checkpoint_outranks_a_background_rate_limit_and_both_are_recorded(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(json.dumps({'checkpoint_url': 'https://www.facebook.com/checkpoint/1/'}),
                                                   resources=2, statuses=[200, 429]))
    code, out, _ = run(browser, 'feed')
    state = state_of()
    assert code == 5 and state['person']['reason'] == 'checkpoint' and state['hold']
    assert json.loads(out)['message'].startswith('Facebook showed') or 'checkpoint' in json.loads(out)['message']


def test_a_rate_limit_beside_a_failed_request_still_holds(browser):
    known_tab(browser)
    browser.respond('facebook.query', {'network_error': 'aborted', 'used': {'source': 'live'}, 'explicit': 1,
                                       'resources': 2, 'statuses': [429, 0], 'unwatched': [], 'limited': False,
                                       'user_id': ACCOUNT})
    code, out, _ = run(browser, 'feed')
    result = json.loads(out)
    assert code == 5 and state_of()['hold'] and not state_of()['person']
    assert result['stop_reason'] == 'rate_limited' and result['limit']['reset'] > time.time()
    assert 'next' in result  # a hold passes by itself: the same read can be run again after it


def test_a_rate_limit_status_beside_a_good_answer_holds_and_the_answer_is_not_used(browser):
    known_tab(browser)
    browser.respond('facebook.query', {**page(['A']), 'statuses': [200, 429]})
    code, out, _ = run(browser, 'feed', '--json')
    assert code == 5 and state_of()['hold'] and 'results' in json.loads(out) and json.loads(out)['results'] == []


def test_a_hold_lasts_thirty_minutes_and_is_the_accounts(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result('', status=429))
    run(browser, 'feed')
    hold = state_of()['hold']
    assert 1790 < hold['until'] - hold['at'] < 1810
    code, out, _ = run(browser, 'profile', 'some.person')
    assert code == 5 and 'rate-limited' in json.loads(out)['message']  # every command of the account waits


def test_every_request_and_every_look_is_in_the_request_log(browser):
    """Appendix C: Facebook had no request record. Now the core's log holds the sent request, the tab opening and the
    requests the open tab made between commands."""
    known_tab(browser, resources=3, statuses=[200] * 3)
    browser.respond('facebook.query', page(['A']))
    run(browser, 'feed')
    lines = [json.loads(line) for line in (guard().directory / 'requests.jsonl').read_text().splitlines()]
    kinds = [(line.get('kind'), line.get('outcome')) for line in lines]
    assert ('query', 'sent') in kinds and any(kind == 'unwatched' for kind, _ in kinds)
    assert any(line.get('outcome') == 'ok' for line in lines)  # the answer's classification is appended to the line


def idle(browser, *extra):
    browser.write()
    done = run_cli('facebook', 'idle', '--account', ASIDE, '--token', 'any', '--after', '0', *extra, browser=browser,
                   env=ENVIRONMENT)
    return done.returncode, json.loads(done.stdout)


def test_the_idle_cleanup_empties_the_tab_to_about_blank_and_never_tries_to_close_it(browser):
    known_tab(browser)  # the cleanup's own look at the tab
    code, result = idle(browser)
    assert code == 0 and result['outcome'] == 'emptied'
    assert 'facebook.blank' in browser.ops() and 'facebook.close' not in browser.ops()
    assert next(t['url'] for t in json.loads(browser.path.read_text())['tabs'] if t['id'] == 'T1') == 'about:blank'


def test_the_idle_cleanup_takes_in_a_429_the_tab_saw_before_it_empties_it(browser):
    known_tab(browser, statuses=[429], resources=1)
    code, result = idle(browser)
    assert result['outcome'] == 'emptied' and state_of()['hold']


def test_the_next_command_after_the_cleanup_opens_a_fresh_tab_and_leaves_the_old_alone(browser):
    known_tab(browser)
    idle(browser)
    opening(browser, 'T2').respond('facebook.query', page(['A']))
    code, out, _ = run(browser, 'feed')
    assert code == 0 and Session('facebook', ASIDE).tab == 'T2'
    assert 'tab opened (+30 requests)' in out.splitlines()[0]


def test_two_commands_starting_together_open_one_tab(browser):
    """The tab is found, re-checked, opened and recorded under the session lock."""
    browser.flag(open_ids=['TA', 'TB'])
    for _ in range(2):
        browser.respond('facebook.state', {**{'location': HOME, 'user_id': ACCOUNT, 'runtime': True, 'resources': 3,
                                              'statuses': [200] * 3, 'unwatched': [], 'limited': False}})
        browser.respond('facebook.modules', {'CometNewsFeedPaginationQuery': '1'})
    browser.write()
    environment = {**os.environ, **browser.env(), **ENVIRONMENT}
    children = [subprocess.Popen([sys.executable, str(CLI), 'facebook', 'doctor'], env=environment,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    results = [json.loads(child.communicate(timeout=60)[0]) for child in children]
    assert all(r['ok'] for r in results)
    assert browser.ops().count('open') == 1
