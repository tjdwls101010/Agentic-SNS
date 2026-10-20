"""How requests to Facebook are named and sorted (fixtures/requests.json): the 14 read queries of queries.json, the
tokens of each sort, the search verticals, and the one query that has no stored id."""
import json

from sns.facebook import web
from sns.session import Session
from tests.sns.facebook.data import fixture
from tests.sns.facebook.scenes import ASIDE, known_tab, look, queries, query_result, run
from tests.sns.facebook.test_cli_replies import handle_of, replies_body
from tests.sns.facebook.test_cli_thread import URL, comment, script_post

REQUESTS = fixture('requests.json')
DEEP = 'Depth2CommentsListPaginationQuery'


def test_the_fourteen_read_queries_are_the_bundled_snapshot_the_fixture_describes():
    described = REQUESTS['query_names']['queries']
    assert set(web.QUERIES) == set(described)
    for key, spec in described.items():
        mine = web.QUERIES[key]
        assert {'name': mine['name'], 'expected_key': mine['expected_key'], 'kind': mine['kind'],
                'cursor_var': mine['cursor_var']} == spec, key


def test_no_query_the_skill_may_send_is_a_mutation_and_none_marks_notifications_seen():
    """Reading the notifications list sends no seen or read change: the allow-list is built from queries.json, which
    names read queries only, so these three requests (the app's own seen-state writes) can never go out."""
    seen_state = {'CometNotificationsUpdateSeenStateMutation', 'CometFeedsNotificationsUpdateSeenStateMutation',
                  'CometHomepageBadgeCountClearingMutation'}
    assert not [name for name in web.READ_NAMES if 'Mutation' in name]
    assert not seen_state & set(web.READ_NAMES)


def test_the_depth_two_replies_query_has_no_stored_id_and_must_be_learned():
    missing = [key for key, spec in web.QUERIES.items() if not spec['doc_id']]
    assert missing == REQUESTS['query_names']['requires_live_learning'] == ['replies_deep']


def test_sort_tokens():
    tokens = REQUESTS['sort_tokens']
    assert web.FEED_SORTS == tokens['feed'] and web.GROUP_SORTS == tokens['group']
    assert web.COMMENT_SORTS == tokens['comments']


def test_search_verticals_share_one_query_and_differ_by_experience_type(browser):
    known_tab(browser)
    empty = json.dumps({'data': {'serpResponse': {'results': {
        'edges': [], 'page_info': {'has_next_page': False, 'end_cursor': None}}}}})
    for number, vertical in enumerate(REQUESTS['search_types']['map']):
        if number:
            look(browser)
        browser.respond('facebook.query', query_result(empty))
        run(browser, 'search', 'x', '--type', vertical)
    sent = [q['args'] for q in queries(browser)]
    assert [s['variables']['args']['experience']['type'] for s in sent] == list(REQUESTS['search_types']['map'].values())
    assert {s['name'] for s in sent} == {'SearchCometResultsPaginatedResultsQuery'}


def test_a_deep_replies_read_learns_its_id_from_the_screen_because_none_is_stored(browser):
    script_post(browser, [comment('C1', replies=2)], has_next=False)
    code, out, _ = run(browser, 'post', URL)
    first = handle_of(out, 'c1')
    look(browser).respond('facebook.query', query_result(replies_body(
        'C1', [comment('R1', replies=1, depth=1, parent='C1')], has_next=False)), name='Depth1CommentsListPaginationQuery')
    code, out, _ = run(browser, 'replies', first)
    deeper = handle_of(out, 'r1')
    look(browser).respond('facebook.query', {'missing': 'no query id', 'used': {'source': 'none'}, 'explicit': 0,
                                             'resources': 0, 'statuses': [], 'unwatched': [], 'limited': False},
                          name=DEEP)
    browser.respond('facebook.route', {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'explicit': 0,
                                       'resources': 3, 'statuses': [200] * 3, 'unwatched': [], 'limited': False,
                                       'live': {DEEP: {'doc_id': '777', 'flags': {}}}})
    browser.respond('facebook.query', query_result(replies_body(
        'R1', [comment('D1', replies=0, depth=2, parent='R1')], has_next=False), source='live', doc_id='777'), name=DEEP)
    code, out, _ = run(browser, 'replies', deeper)
    assert code == 0 and 'Person D1' in out
    assert Session('facebook', ASIDE).query(DEEP)['doc_id'] == '777'
    first_try = [q for q in queries(browser) if q['args']['name'] == DEEP][0]
    assert first_try['args']['fallback']['doc_id'] is None  # nothing was stored to send
