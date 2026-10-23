"""What the X client does with signals and losses around its own request (review of the port): the order in which an
answer and the page's background signals are judged, how often a lost tab is replaced, a stale limit, and the account
the page shows on an ordinary read."""
import json
import time

from tests.sns.x.scenes import ACCOUNT, known_tab, opening, query_result, run, state_of, limits

USER = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'example_author', 'name': 'Example'}}
RATE = {'x-rate-limit-limit': '500', 'x-rate-limit-remaining': '499', 'x-rate-limit-reset': str(int(time.time()) + 900)}
CHALLENGE = '<!doctype html><html class="cf"></html>'
TAB_GONE = {'__raw_stdout': json.dumps({'kind': 'error', 'error': 'tab_missing', 'message': 'no such tab'}) + '\n'}


def home(ident, bottom='CUR1'):
    node = {'__typename': 'Tweet', 'rest_id': ident, 'core': {'user_results': {'result': USER}},
            'legacy': {'full_text': f'post {ident}', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026'}}
    items = [{'entryId': f'tweet-{ident}', 'content': {'itemContent': {'itemType': 'TimelineTweet',
                                                                     'tweet_results': {'result': node}}}}]
    if bottom:
        items.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}})
    return {'data': {'home': {'home_timeline_urt': {'instructions': [{'type': 'TimelineAddEntries', 'entries': items}]}}}}


def background(**fields):
    return {'path': '/i/api/2/x.json', 'status': 200, 'codes': [], 'html': False, 'rate': None, 'at': 55, **fields}


def test_the_own_answer_is_judged_before_a_background_login_signal_is_raised(browser):
    """A challenge the skill's own request met is a person block, even when the page also saw a logout in the meantime."""
    known_tab(browser).respond('x.query', query_result(CHALLENGE, status=403, signals=[background(status=401)]))
    code, out, _ = run(browser, 'feed')
    assert code == 5, out
    assert state_of()['block_reason'] == 'challenge'


def test_a_tab_lost_again_after_it_was_replaced_stops_the_command(browser):
    """A lost tab is replaced once per command; a tab that keeps vanishing is Aside's problem, not a loop to feed."""
    known_tab(browser).respond('x.query', TAB_GONE)
    opening(browser, 'NEW1').respond('x.query', query_result(home('1'), headers=RATE))
    browser.respond('x.query', TAB_GONE)
    opening(browser, 'NEW2').respond('x.query', query_result(home('2', None), headers=RATE))
    code, out, _ = run(browser, 'feed', '--limit', '40')
    assert code == 8 and 'post 1' in out and 'post 2' not in out, out
    assert browser.ops().count('opener') == 1


def test_a_background_limit_whose_reset_has_passed_is_not_held_again(browser):
    stale = background(path='/i/api/graphql/abc/HomeTimeline', rate={'limit': 50, 'remaining': 0, 'reset': int(time.time()) - 120}, at=101)
    known_tab(browser, signals=[stale]).respond('x.query', query_result(home('1'), headers=RATE))
    code, out, _ = run(browser, 'feed')
    assert code == 0, out
    assert 'HomeTimeline' not in limits() or 'blocked_until' not in limits()['HomeTimeline']


def test_the_account_the_page_shows_on_an_ordinary_read_is_the_commands_account(browser):
    """The tab's logged-in account switched between the start of the command and a read: records of two accounts never
    mix (exit 4), although no tab is reopened."""
    known_tab(browser).respond('x.query', query_result(home('1'), headers=RATE, user_id=ACCOUNT))
    browser.respond('x.query', query_result(home('2', None), headers=RATE, user_id='1000000098'))
    code, out, _ = run(browser, 'feed', '--limit', '40')
    assert code == 4 and 'post 1' in out and 'changed' in out, out
