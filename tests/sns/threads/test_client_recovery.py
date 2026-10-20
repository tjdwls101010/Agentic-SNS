"""What the Threads client does with signals and losses around its own request: the order in which an answer and the
page's background signals are judged, how often a lost tab is replaced and how much recovery one command may spend."""
import json

from tests.sns.threads.scenes import (ACCOUNT, START, feed_body, known_tab, opening, post, query_result, run, state,
                                      state_of)

TAB_GONE = {'__raw_stdout': json.dumps({'kind': 'error', 'error': 'tab_missing', 'message': 'no such tab'}) + '\n'}
RATE_BODY = json.dumps({'error': {'code': 4, 'message': 'Please wait a few minutes before you try again later.'}})
REFUSED = {'errors': [{'message': 'Execution error', 'severity': 'CRITICAL'}]}


def page(ident, more=True):
    return query_result(feed_body([[post(ident, '2026-10-08T03:00:00Z')]], more, 'CUR' + ident if more else None))


def test_the_own_answer_is_judged_before_a_background_login_signal_is_raised(browser):
    """A 429 the skill's own request met is a hold to record, even when the page also saw a logout in the meantime."""
    login = {'url': 'https://www.threads.com/graphql/query', 'status': 200, 'at': 6,
             'summary': json.dumps({'errors': [{'message': 'login_required'}]})}
    known_tab(browser).respond('threads.query', query_result(RATE_BODY, signals=[login]))
    code, out, _ = run(browser, 'feed')
    assert code == 5, out
    assert state_of()['hold'] is not None


def test_a_tab_lost_again_after_it_was_replaced_stops_the_command(browser):
    """A lost tab is replaced once per command; a tab that keeps vanishing is Aside's problem, not a loop to feed."""
    known_tab(browser).respond('threads.query', TAB_GONE)
    opening(browser, 'NEW1').respond('threads.query', page('1'))
    browser.respond('threads.query', TAB_GONE)
    opening(browser, 'NEW2').respond('threads.query', page('2', more=False))
    code, out, _ = run(browser, 'feed', '--limit', '40')
    assert code == 8 and 'post 1' in out and 'post 2' not in out, out
    assert browser.ops().count('open') == 1


def test_a_stopped_call_still_charges_what_the_tab_finished(browser):
    benign = {'url': 'https://www.threads.com/graphql/query', 'status': 200, 'at': 7,
              'summary': '{"errors": [{"message": "A field could not be resolved", "severity": "WARNING"}]}'}
    known_tab(browser)
    browser.respond('threads.query', {'stopped': 'signal', 'explicit': 0, 'resources': 5, 'statuses': [200] * 5,
                                      'signals': [benign], 'location': START})
    browser.respond('threads.query', page('1', more=False))
    code, out, _ = run(browser, 'feed', '--json')
    result = json.loads(out)
    assert browser.ops().count('threads.query') == 2 and result['request_count'] >= 6


def test_a_tab_that_vanishes_before_a_query_is_reopened_once(browser):
    known_tab(browser).respond('threads.query', TAB_GONE)
    opening(browser).respond('threads.query', page('1', more=False))
    code, out, _ = run(browser, 'feed', '--json')
    assert code == 0 and browser.ops().count('open') == 1 and json.loads(out)['setup_requests'] == 40


def test_the_tab_another_command_opened_meanwhile_is_used_instead_of_a_second_one(browser):
    """The recorded tab vanishes while another command has already recorded its own: this command takes that one up
    rather than opening a third."""
    from sns.paths import scope
    from tests.sns.threads.scenes import ASIDE
    path = scope('threads', ASIDE, 'session') / 'tab.json'
    known_tab(browser)
    browser.tab('OTHER', url=START)
    browser.respond('threads.query', {**TAB_GONE, '__write': {str(path): json.dumps({'tab': 'OTHER'})}})
    browser.respond('threads.query', page('1', more=False))
    code, out, _ = run(browser, 'feed', '--json')
    assert code == 0, out
    assert 'open' not in browser.ops() and [c['tab'] for c in browser.calls() if c['op'] == 'threads.query'] == ['T1', 'OTHER']


def test_a_second_refusal_of_the_live_module_is_not_reloaded_again(browser):
    """One reload a command: a live module refused twice is the app being older than Threads, not something a loop mends."""
    def refused(source):
        return query_result(REFUSED, source=source)
    known_tab(browser).respond('threads.query', refused('live'))
    browser.respond('threads.navigate', {'navigating': True, 'explicit': 0, 'resources': 0, 'statuses': [], 'signals': [],
                                         'location': START})
    browser.respond('threads.state', state(resources=30, document='<script>{"csrf_token":"t","NON_FACEBOOK_USER_ID":"%s",'
                                                                  '"username":"v"}</script>' % ACCOUNT))
    browser.respond('threads.state', state()).respond('threads.query', page('1'))
    browser.respond('threads.query', refused('live'))
    code, out, _ = run(browser, 'feed', '--limit', '10', '--json')
    result = json.loads(out)
    assert code == 8 and len(result['results']) == 1 and 'recovery allowance' in result['message'], result
    assert browser.ops().count('threads.navigate') == 1
