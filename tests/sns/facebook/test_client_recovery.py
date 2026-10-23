"""What the client does when Facebook refuses a read or the tab is not what it was: a refused query id is relearned by
visiting the screen that loads it (once per query, a few screens per command), a temporary rejection is retried once,
a lost tab is replaced once, and the opening and the screen moves are counted as the page makes them."""
import json

from sns.session import Session
from tests.sns.facebook.scenes import (ACCOUNT, ASIDE, HOME, graphql_body, known_tab, look, opening, queries,
                                       query_result, run, sent, state_of, story)

FEED = ['viewer', 'news_feed']
NAME = 'CometNewsFeedPaginationQuery'
REJECTED = json.dumps({'errors': [{'message': 'PersistedQueryNotFound', 'code': 1675002}]})
TAB_GONE = {'__raw_stdout': json.dumps({'kind': 'error', 'error': 'tab_missing', 'message': 'no such tab'}) + '\n'}


def page(ids, has_next=False, cursor='C1', **kwargs):
    return query_result(graphql_body(FEED, [story(i) for i in ids], has_next, cursor), **kwargs)


def route_result(doc_id='222', name=NAME, resources=4, **extra):
    live = {name: {'doc_id': doc_id, 'flags': {'__relay_internal__pv__Arelayprovider': False}}} if doc_id else {}
    return {'location': HOME, 'user_id': ACCOUNT, 'live': live, 'explicit': 0, 'resources': resources,
            'statuses': [200] * resources, 'unwatched': [], 'limited': False, **extra}


def test_a_refused_stored_id_is_healed_by_visiting_the_screen_once_and_remembered(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(REJECTED, source='stored', doc_id='999'))
    browser.respond('facebook.route', route_result('222'))
    browser.respond('facebook.query', page(['A'], source='live', doc_id='222'))
    code, out, _ = run(browser, 'feed', '--json')
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == ['A']
    assert result['request_count'] == 1 + 10 + 1 and result['setup_requests'] == 10  # a screen move costs its reservation
    [route] = [c for c in browser.calls() if c['op'] == 'facebook.route']
    assert route['args']['path'] == '/' and route['args']['names'] == [NAME]
    learned = Session('facebook', ASIDE).query(NAME)
    assert learned['doc_id'] == '222'
    # the next run sends the learned id as its fallback
    look(browser).respond('facebook.query', page(['B']))
    run(browser, 'feed')
    assert queries(browser)[-1]['args']['fallback']['doc_id'] == '222'


def test_a_refused_live_id_is_relearned_once_not_failed_at_once(browser):
    """Appendix C: a live id the server refused used to be exit 6 with no recovery; the screen is visited once for it."""
    known_tab(browser)
    browser.respond('facebook.query', query_result(REJECTED, source='live', doc_id='111'))
    browser.respond('facebook.route', route_result('333'))
    browser.respond('facebook.query', page(['A'], source='live', doc_id='333'))
    code, out, _ = run(browser, 'feed', '--json')
    assert code == 0 and json.loads(out)['results'][0]['id'] == 'A'
    assert sent(browser) == [NAME, NAME] and len([c for c in browser.calls() if c['op'] == 'facebook.route']) == 1


def test_a_query_refused_again_after_the_screen_is_exit_6_and_not_a_loop(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(REJECTED, source='live', doc_id='111'))
    browser.respond('facebook.route', route_result('333'))
    browser.respond('facebook.query', query_result(REJECTED, source='live', doc_id='333'))
    code, out, _ = run(browser, 'feed')
    result = json.loads(out)
    assert code == 6 and result['error'] == 'failed' and 'needs an update' in result['fix']
    assert len([c for c in browser.calls() if c['op'] == 'facebook.route']) == 1 and len(queries(browser)) == 2


def test_a_screen_that_gives_the_id_just_refused_is_not_asked_again(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(REJECTED, source='live', doc_id='111'))
    browser.respond('facebook.route', route_result('111'))
    code, out, _ = run(browser, 'feed')
    assert code == 6 and len(queries(browser)) == 1  # the same id would only be refused again


def test_a_screen_that_loads_no_id_is_exit_6(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(REJECTED, source='stored', doc_id='999'))
    browser.respond('facebook.route', route_result(None))
    code, out, _ = run(browser, 'feed')
    assert code == 6 and 'did not provide a current one' in json.loads(out)['message']


def test_late_requests_of_a_screen_are_counted_against_its_reservation(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(REJECTED, source='stored', doc_id='999'))
    browser.respond('facebook.route', route_result('222', resources=5))
    # the next query's ledger delta carries the screen's five late requests and its own one
    browser.respond('facebook.query', page(['A'], source='live', doc_id='222', resources=6))
    code, out, _ = run(browser, 'feed', '--json')
    assert code == 0 and json.loads(out)['request_count'] == 1 + 10 + 1


def test_a_screen_that_loads_more_than_reserved_is_charged_in_full(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(REJECTED, source='stored', doc_id='999'))
    browser.respond('facebook.route', route_result('222', resources=12))
    browser.respond('facebook.query', page(['A'], source='live', doc_id='222'))
    code, out, _ = run(browser, 'feed', '--json')
    assert code == 0 and json.loads(out)['request_count'] == 1 + 12 + 1


def test_a_rate_limit_among_the_screens_own_requests_holds_the_account(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(REJECTED, source='stored', doc_id='999'))
    browser.respond('facebook.route', route_result('222', resources=3, statuses=[200, 429, 200]))
    code, out, _ = run(browser, 'feed', '--json')
    result = json.loads(out)
    assert code == 5 and result['error'] == 'blocked' and 'rate-limited' in result['message']
    assert state_of()['hold'] and not state_of()['person']
    assert len(queries(browser)) == 1  # nothing more was sent


def test_a_screen_that_times_out_stays_counted_at_its_reservation(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(REJECTED, source='stored', doc_id='999'))
    browser.respond('facebook.route', {'__raw_stdout': 'Error: other side closed\n', '__exit': 1})
    code, out, _ = run(browser, 'feed', '--json')
    result = json.loads(out)
    assert code == 3 and result['request_count'] >= 1 + 10


def test_a_temporary_rejection_is_retried_once_then_it_is_a_rate_limit(browser):
    known_tab(browser)
    temporary = 'for (;;);' + json.dumps({'error': 1357054})
    browser.respond('facebook.query', query_result(temporary))
    browser.respond('facebook.query', page(['A']))
    code, out, _ = run(browser, 'feed')
    assert code == 0 and 'requests=2' in out.splitlines()[0]
    look(browser).respond('facebook.query', query_result(temporary)).respond('facebook.query', query_result(temporary))
    code, out, _ = run(browser, 'feed')
    assert code == 5 and state_of()['hold']


def test_a_vanished_tab_is_reopened_once_and_the_opening_is_counted(browser):
    known_tab(browser, 'GONE')
    browser.respond('facebook.query', TAB_GONE)
    opening(browser, 'NEW', resources=20)
    browser.respond('facebook.query', page(['A']))
    code, out, _ = run(browser, 'feed')
    assert code == 0, out
    assert out.splitlines()[0] == 'facebook feed · sort=top · 1 shown · stopped=exhausted · requests=1 · tab opened (+30 requests)'
    assert Session('facebook', ASIDE).tab == 'NEW'


def test_a_tab_that_keeps_vanishing_is_asides_problem_not_a_loop(browser):
    known_tab(browser, 'GONE')
    browser.respond('facebook.query', TAB_GONE)
    opening(browser, 'NEW')
    browser.respond('facebook.query', TAB_GONE)
    code, out, _ = run(browser, 'feed')
    assert code == 3 and json.loads(out)['error'] == 'aside' and len(queries(browser)) == 2


def test_a_tab_reopened_under_another_account_stops_the_command(browser):
    known_tab(browser, 'GONE')
    browser.respond('facebook.query', TAB_GONE)
    opening(browser, 'NEW', resources=20, user_id='222')
    code, out, _ = run(browser, 'feed')
    result = json.loads(out)
    assert code == 4 and 'changed' in result['message']
    assert len(queries(browser)) == 1 and not (browser.root / 'data' / 'handles').exists()


def test_late_opening_requests_stay_in_the_openings_reservation(browser):
    opening(browser, 'T9', resources=1, statuses=[200])
    browser.respond('facebook.query', page(['A'], resources=2, statuses=[200, 200]))
    code, out, _ = run(browser, 'feed', '--json')
    result = json.loads(out)
    assert code == 0 and result['results'] and result['setup_requests'] == 30
    assert result['request_count'] - result['setup_requests'] == 1  # the page's late requests used up the reservation


def test_requests_made_before_a_startup_failure_are_still_reported(browser):
    opening(browser, 'T9', resources=20, location='https://www.facebook.com/checkpoint/1/', user_id=None)
    code, out, _ = run(browser, 'feed')
    result = json.loads(out)
    assert code == 5 and result['request_count'] == 30 and result['setup_requests'] == 30  # its reservation
