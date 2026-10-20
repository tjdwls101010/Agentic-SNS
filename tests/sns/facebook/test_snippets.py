"""The browser snippets, run as composed for the browser under Node with a fake facebook.com page (the shared snippet
harness with the Facebook page model): what leaves the browser, what is refused, what the tab's ledger of its own
requests reports, and that every composed function compiles inside the Aside program (fixtures: requests).

Not run here: the route function's wait for the page to go quiet after at least one request of its own (the harness
cannot release a page request on a history move), so only its path checks, its ids and its deadline are; the quiet
interval is checked in the client tests through the scripted route answers and live.
"""
import json
import shutil
import subprocess
from urllib.parse import parse_qsl

import pytest

from sns.aside import PROGRAM
from sns.facebook import web
from tests.sns.facebook.data import fixture
from tests.sns.facebook.node_runner import needs_node, run as run_harness

pytestmark = needs_node
REQUESTS = fixture('requests.json')
HOST = 'https://www.facebook.com/ajax/'
ASYNC_PARAMS = {'__user': '1000123', '__a': '1', '__req': '1f', '__comet_req': '15', 'fb_dtsg': 'AB:cd',
                'jazoest': '2388', 'lsd': 'lsdTok', '__spin_r': '1027000000', '__rev': '1027000000', '__hs': 'x'}
LIVE = {'params': {'id': '555', 'name': 'CometNewsFeedPaginationQuery',
                   'providedVariables': {'__relay_internal__pv__Arelayprovider': True}}}
ALLOWED = web.READ_NAMES
USER = {'CurrentUserInitialData': {'USER_ID': 1000123}}


def entry(status, name='x'):
    return {'url': HOST + name, 'status': status}


def run(tmp_path, calls, **page):
    sources = {name: web.snippet(name) for name in web.SNIPPET_NAMES}
    return run_harness(tmp_path, calls, {'location': 'https://www.facebook.com/', **page}, sources)


def query_call(**extra):
    return {'snippet': 'query', 'args': {'name': 'CometNewsFeedPaginationQuery', 'allowed': ALLOWED,
                                         'variables': {'count': 3, 'cursor': None}, 'fallback': {}, **extra}}


def query_case(tmp_path, modules, **extra):
    return run(tmp_path, [query_call(**extra)], modules=modules, fetch=[{'status': 200, 'body': '{"data":{}}'}])


def test_query_uses_the_live_module_and_the_pages_own_parameters(tmp_path):
    out = query_case(tmp_path, {'CometNewsFeedPaginationQuery.graphql': LIVE,
                                'getAsyncParams': {'__function': ASYNC_PARAMS}, 'LSD': {'token': 'lsdTok'}, **USER})
    [sent] = out['fetches']
    spec = REQUESTS['graphql_request']
    assert sent['url'] == spec['url'] and sent['method'] == spec['method'] and sent['credentials'] == 'include'
    assert sent['headers']['content-type'] == spec['headers']['content-type']
    assert sent['headers']['x-fb-friendly-name'] == 'CometNewsFeedPaginationQuery'
    assert sent['headers']['x-fb-lsd'] == 'lsdTok'
    fields = form_of(out)
    assert {k: fields[k] for k in ASYNC_PARAMS} == ASYNC_PARAMS
    assert fields['doc_id'] == '555' and fields['fb_api_req_friendly_name'] == 'CometNewsFeedPaginationQuery'
    assert fields['fb_api_caller_class'] == 'RelayModern' and fields['server_timestamps'] == 'true'
    assert json.loads(fields['variables']) == {'count': 3, 'cursor': None, '__relay_internal__pv__Arelayprovider': True}
    [result] = out['results']
    assert result['used'] == {'source': 'live', 'doc_id': '555', 'flags': {'__relay_internal__pv__Arelayprovider': True}}
    assert result['explicit'] == 1 and result['resources'] == 1 and result['statuses'] == [200]
    assert result['status'] == 200 and result['user_id'] == '1000123'  # the account the page shows, for the client


def form_of(out):
    """The form the page function's one POST sent (the harness records the body as a string)."""
    return dict(parse_qsl(out['fetches'][0]['body'], keep_blank_values=True))


def test_query_without_the_pages_parameters_builds_the_documented_form(tmp_path):
    modules = {'CurrentUserInitialData': {'USER_ID': '1000123'}, 'DTSGInitialData': {'token': 'AB:cd'},
               'LSD': {'token': 'lsdTok'}, 'SiteData': {'__spin_r': 1027000000}}
    out = query_case(tmp_path, modules, fallback={'doc_id': '777',
                                                  'flags': {'__relay_internal__pv__Brelayprovider': False}})
    fields = form_of(out)
    spec, tokens = REQUESTS['graphql_request'], REQUESTS['tokens']['expected']
    assert list(fields) == spec['form_fields_in_order'][:9] + ['fb_api_caller_class', 'fb_api_req_friendly_name',
                                                               'variables', 'server_timestamps', 'doc_id']
    assert set(fields) == set(spec['form_fields_in_order'])
    assert {k: fields[k] for k in spec['fixed_values']} == spec['fixed_values']
    assert {k: fields[k] for k in spec['from_tokens']} == {k: tokens[v] for k, v in spec['from_tokens'].items()}
    assert fields['doc_id'] == '777' and out['results'][0]['used']['source'] == 'stored'
    assert json.loads(fields['variables'])['__relay_internal__pv__Brelayprovider'] is False


def test_live_provider_values_override_the_callers_variables(tmp_path):
    case = REQUESTS['relay_provider_flags']
    out = query_case(tmp_path, {'CometNewsFeedPaginationQuery.graphql': case['modules']['CometNewsFeedPaginationQuery.graphql'],
                                'getAsyncParams': {'__function': ASYNC_PARAMS}},
                     variables=case['variables'])
    assert json.loads(form_of(out)['variables']) == case['expected']


def test_query_takes_a_loaded_operation_id_with_stored_flags(tmp_path):
    out = query_case(tmp_path, {'CometNewsFeedPaginationQuery_facebookRelayOperation': '888',
                                'getAsyncParams': {'__function': ASYNC_PARAMS}},
                     fallback={'doc_id': '1', 'flags': {'f': 1}})
    fields = form_of(out)
    assert fields['doc_id'] == '888' and json.loads(fields['variables'])['f'] == 1
    assert out['results'][0]['used']['source'] == 'live_id'


def test_ids_come_live_before_loaded_before_stored(tmp_path):
    case = REQUESTS['doc_id_discovery']
    out = run(tmp_path, [{'snippet': 'modules', 'args': {'names': list(case['expected'])}}], modules=case['modules'])
    assert out['results'][0] == case['expected']


@pytest.mark.parametrize('name', ['useCometUFICreateCommentMutation', 'CometUFIDeleteCommentSubscription',
                                  'SomeUnknownQuery'])
def test_only_the_queries_the_skill_names_can_be_sent(tmp_path, name):
    out = run(tmp_path, [{'snippet': 'query', 'args': {'name': name, 'allowed': ALLOWED, 'variables': {},
                                                       'fallback': {'doc_id': '1'}}}],
              modules={f'{name}.graphql': LIVE, 'getAsyncParams': {'__function': ASYNC_PARAMS}})
    assert out['fetches'] == [] and out['results'][0]['refused']


def test_a_query_with_no_allowed_list_is_refused(tmp_path):
    out = run(tmp_path, [{'snippet': 'query', 'args': {'name': 'CometNewsFeedPaginationQuery', 'variables': {},
                                                       'fallback': {'doc_id': '1'}}}])
    assert out['fetches'] == [] and out['results'][0]['refused']


def test_the_queries_the_client_may_send_are_exactly_the_ones_queries_json_names():
    """The allowlist is the client's, built from queries.json: no second list in the page function to drift from it."""
    named = sorted(spec['name'] for spec in web.QUERIES.values())
    assert web.READ_NAMES == named and len(named) == 12
    assert named == sorted(spec['name'] for spec in REQUESTS['query_names']['queries'].values())
    assert 'CometNewsFeedPaginationQuery' not in web.snippet('query')  # no name is spelled in the page function


def test_query_with_no_id_anywhere_sends_nothing(tmp_path):
    out = query_case(tmp_path, {'getAsyncParams': {'__function': ASYNC_PARAMS}})
    assert out['fetches'] == [] and out['results'][0]['missing'] and out['results'][0]['used']['source'] == 'none'


def test_page_fetch_is_same_origin_only(tmp_path):
    ok = run(tmp_path, [{'snippet': 'page', 'args': {'url': 'https://www.facebook.com/x'}}],
             fetch=[{'status': 200, 'body': '<html>'}], modules=USER)
    assert [f['method'] for f in ok['fetches']] == ['GET'] and ok['results'][0]['body'] == '<html>'
    for url in ('https://m.facebook.com/x', 'https://evil.example/x', 'javascript:alert(1)', 'not a url'):
        refused = run(tmp_path, [{'snippet': 'page', 'args': {'url': url}}])
        assert refused['fetches'] == [] and refused['results'][0]['refused'], url


@pytest.mark.parametrize('path', ['https://evil.example/', '//evil.example/x', 'groups/x'])
def test_route_only_moves_within_the_site(tmp_path, path):
    out = run(tmp_path, [{'snippet': 'route', 'args': {'path': path, 'names': []}}])
    assert out['results'][0]['refused'] and out['fetches'] == [] and out['pushes'] == []


def test_route_moves_the_page_and_reports_the_queries_the_screen_loaded(tmp_path):
    name = 'SearchCometResultsPaginatedResultsQuery'
    out = run(tmp_path, [{'snippet': 'route', 'args': {'path': '/search/top/?q=x', 'names': [name, 'Other']}}],
              virtual_time=True, modules={f'{name}.graphql': {'params': {'id': '999', 'providedVariables': {'p': 1}}},
                                          **USER})
    [result] = out['results']
    assert out['pushes'] == ['/search/top/?q=x'] and out['popstates'] == 1 and out['fetches'] == []
    assert out['locations'] == ['https://www.facebook.com/search/top/?q=x']
    assert result['location'] == 'https://www.facebook.com/search/top/?q=x' and result['user_id'] == '1000123'
    assert result['live'] == {name: {'doc_id': '999', 'flags': {'p': 1}}}  # the id of a query that did not load is absent
    assert result['explicit'] == 0


def test_a_route_over_a_known_rate_limit_does_not_move(tmp_path):
    out = run(tmp_path, [{'snippet': 'route', 'args': {'path': '/', 'names': []}, 'before': [entry(429)]}], modules=USER)
    assert out['results'][0]['stopped'] == 'rate_limit' and out['pushes'] == []


def test_state_reads_the_logged_in_user_without_a_request(tmp_path):
    out = run(tmp_path, [{'snippet': 'state', 'args': {'fresh': True}}], modules=USER, buffered=[entry(200)] * 29)
    assert out['results'][0] == {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'runtime': True,
                                 'resources': 29, 'statuses': [200] * 29, 'unwatched': [], 'limited': False,
                                 'limited_at': None}
    assert out['fetches'] == []
    # a tab the skill did not just open: what it did before the skill watched it is not counted
    known = run(tmp_path, [{'snippet': 'state', 'args': {'fresh': False}}], modules=USER,
                buffered=[entry(200), entry(429)])
    result = known['results'][0]
    assert result['resources'] == 0 and result['statuses'] == []
    assert result['unwatched'] == [200, 429]  # not counted, but a rate limit there is still seen


def test_a_page_that_is_not_logged_in_has_no_user(tmp_path):
    out = run(tmp_path, [{'snippet': 'state', 'args': {'fresh': False}}], modules={})
    assert out['results'][0]['user_id'] is None and out['results'][0]['runtime'] is True


def test_requests_finishing_after_a_call_are_counted_by_the_next(tmp_path):
    """The tab keeps one ledger of its facebook.com requests; nothing finished is lost."""
    out = run(tmp_path, [{'snippet': 'page', 'args': {'url': 'https://www.facebook.com/x'}, 'during': [entry(200)]},
                         {'snippet': 'state', 'args': {}, 'before': [entry(429)]}],
              fetch=[{'status': 200, 'body': '<html>'}], modules=USER)
    first, second = out['results']
    assert first['resources'] == 2 and first['statuses'] == [200, 200]  # its own request and the one finished meanwhile
    assert second['statuses'] == [429]  # the late one is reported at the next look, never dropped


def test_a_reloaded_pages_rate_limit_is_reported_not_charged(tmp_path):
    """A reload the skill did not cause is not counted, but its 429 is still seen and stops the next request."""
    out = run(tmp_path, [{'snippet': 'page', 'args': {'url': 'https://www.facebook.com/x'}},
                         {'snippet': 'page', 'args': {'url': 'https://www.facebook.com/y'}, 'reload': True,
                          'before': [entry(200), entry(429)]}],
              fetch=[{'status': 200, 'body': 'a'}, {'status': 200, 'body': 'b'}], modules=USER)
    first, second = out['results']
    assert first['resources'] == 1
    assert second['stopped'] == 'rate_limit' and second['explicit'] == 0 and 429 in second['statuses'] + second['unwatched']
    assert len(out['fetches']) == 1  # the second call sent nothing


def test_a_rate_limit_already_in_the_ledger_stops_the_next_request_before_it_is_sent(tmp_path):
    out = run(tmp_path, [{'snippet': 'page', 'args': {'url': 'https://www.facebook.com/x'}},
                         {'snippet': 'page', 'args': {'url': 'https://www.facebook.com/y'}, 'before': [entry(429)]}],
              fetch=[{'status': 200, 'body': 'a'}, {'status': 200, 'body': 'b'}], modules=USER)
    assert out['results'][1]['stopped'] == 'rate_limit' and out['results'][1]['statuses'] == [429]
    assert len(out['fetches']) == 1


def test_a_seen_rate_limit_is_remembered_by_the_tab_and_says_when_it_was_seen(tmp_path):
    """If the result that carried a 429 is lost, the next calls still stop and report it, with the time the limited request
    finished (the entries carry no timing here, so the page's own clock stands in)."""
    out = run(tmp_path, [{'snippet': 'state', 'args': {}}, {'snippet': 'state', 'args': {}},
                         {'snippet': 'page', 'args': {'url': 'https://www.facebook.com/x'}}],
              buffered=[entry(200), entry(429)], modules=USER, fetch=[{'status': 200, 'body': 'a'}])
    first, second, third = out['results']
    assert 429 in first['unwatched'] and first['limited'] is True and first['limited_at'] > 0
    assert second['limited'] is True and second['limited_at'] == first['limited_at']
    assert third['stopped'] == 'rate_limit' and out['fetches'] == []


def test_a_network_failure_is_reported_with_the_requests_seen(tmp_path):
    out = run(tmp_path, [query_call()], fetch=[{'throw': 'aborted'}], modules={
        'CometNewsFeedPaginationQuery.graphql': LIVE, 'getAsyncParams': {'__function': ASYNC_PARAMS}, **USER})
    [result] = out['results']
    assert result['network_error'] == 'Error: aborted' and result['explicit'] == 1 and result['used']['doc_id'] == '555'


def test_no_snippet_spells_a_module_require():
    """The live Aside REPL refuses any program containing `require(` ("External modules are not available in the
    REPL"); the page's module loader is reached through an alias."""
    for name in web.SNIPPET_NAMES:
        assert 'require(' not in web.snippet(name), name


@pytest.mark.skipif(not shutil.which('node'), reason='node is not installed')
@pytest.mark.parametrize('header', [{'op': 'evaluate', 'tab': 'T'}, {'op': 'load', 'tab': 'T', 'url': 'u', 'seconds': 5}])
def test_every_composed_page_function_compiles_inside_the_aside_program(header, tmp_path):
    """The fake Aside never runs JavaScript, so a page function that breaks the program (a trailing // comment
    swallowing the rest of the call) passes every other test; node checks the real text."""
    for name in web.SNIPPET_NAMES:
        text = ('const ASIDE = ' + json.dumps(header) + ';\nconst ARGS = {};\n'
                + PROGRAM.replace('PAGE_FUNCTION', web.snippet(name)))
        path = tmp_path / f'{name}.mjs'
        path.write_text(text)
        done = subprocess.run(['node', '--check', str(path)], capture_output=True, text=True)
        assert done.returncode == 0, (name, done.stderr[-500:])

