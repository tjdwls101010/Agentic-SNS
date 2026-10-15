"""Snippet protocol: the skill's real browser JavaScript run under Node against a fake page (snippet_harness.mjs).

Checks what leaves the browser (host, path, method, headers, form fields) against requests.json, that only read
queries can be sent, and that large results survive the REPL's line limit.
"""
import json
import shutil
import subprocess
from urllib.parse import parse_qsl

import pytest

from conftest import SKILL, TESTS, fixture
from facebook import aside

SNIPPETS = SKILL / 'scripts/facebook/graphql/snippets'
PROGRAM = SKILL / 'scripts/facebook/aside/program.js'
REQUESTS = fixture('requests.json')
pytestmark = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')


def run(tmp_path, **spec):
    path = tmp_path / 'case.json'
    path.write_text(json.dumps(spec))
    done = subprocess.run(['node', str(TESTS / 'snippet_harness.mjs'), str(path)], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def form(fetch):
    return dict(parse_qsl(fetch['body'], keep_blank_values=True))


ASYNC_PARAMS = {'__user': '1000123', '__a': '1', '__req': '1f', '__comet_req': '15', 'fb_dtsg': 'AB:cd',
                'jazoest': '2388', 'lsd': 'lsdTok', '__spin_r': '1027000000', '__rev': '1027000000', '__hs': 'x'}
LIVE = {'params': {'id': '555', 'name': 'CometNewsFeedPaginationQuery',
                   'providedVariables': {'__relay_internal__pv__Arelayprovider': True}}}


def query_case(tmp_path, modules, name='CometNewsFeedPaginationQuery', fallback=None):
    return run(tmp_path, kind='page', source=str(SNIPPETS / 'query.js'),
               args={'name': name, 'variables': {'count': 3, 'cursor': None}, 'fallback': fallback or {}},
               page={'modules': modules, 'fetch': [{'status': 200, 'body': '{"data":{}}'}], 'resources': [10, 11]})


def test_query_uses_the_live_module_and_the_pages_own_parameters(tmp_path):
    out = query_case(tmp_path, {'CometNewsFeedPaginationQuery.graphql': LIVE,
                                'getAsyncParams': {'__function': ASYNC_PARAMS}, 'LSD': {'token': 'lsdTok'}})
    [sent] = out['fetches']
    spec = REQUESTS['graphql_request']
    assert sent['url'] == spec['url'] and sent['method'] == spec['method'] and sent['credentials'] == 'include'
    assert sent['headers']['content-type'] == spec['headers']['content-type']
    assert sent['headers']['x-fb-friendly-name'] == 'CometNewsFeedPaginationQuery'
    assert sent['headers']['x-fb-lsd'] == 'lsdTok'
    fields = form(sent)
    assert {k: fields[k] for k in ASYNC_PARAMS} == ASYNC_PARAMS
    assert fields['doc_id'] == '555' and fields['fb_api_req_friendly_name'] == 'CometNewsFeedPaginationQuery'
    assert fields['fb_api_caller_class'] == 'RelayModern' and fields['server_timestamps'] == 'true'
    assert json.loads(fields['variables']) == {'count': 3, 'cursor': None, '__relay_internal__pv__Arelayprovider': True}
    result = out['result']
    assert result['used'] == {'source': 'live', 'doc_id': '555', 'flags': {'__relay_internal__pv__Arelayprovider': True}}
    assert result['explicit'] == 1 and result['resources'] == 1 and result['status'] == 200


def test_query_without_the_pages_parameters_builds_the_documented_form(tmp_path):
    modules = {'CurrentUserInitialData': {'USER_ID': '1000123'}, 'DTSGInitialData': {'token': 'AB:cd'},
               'LSD': {'token': 'lsdTok'}, 'SiteData': {'__spin_r': 1027000000}}
    out = query_case(tmp_path, modules, fallback={'doc_id': '777', 'flags': {'__relay_internal__pv__Brelayprovider': False}})
    [sent] = out['fetches']
    fields = form(sent)
    spec, tokens = REQUESTS['graphql_request'], REQUESTS['tokens']['expected']
    assert list(fields) == spec['form_fields_in_order'][:9] + ['fb_api_caller_class', 'fb_api_req_friendly_name',
                                                               'variables', 'server_timestamps', 'doc_id']
    assert set(fields) == set(spec['form_fields_in_order'])
    assert {k: fields[k] for k in spec['fixed_values']} == spec['fixed_values']
    assert {k: fields[k] for k in spec['from_tokens']} == {k: tokens[v] for k, v in spec['from_tokens'].items()}
    assert fields['doc_id'] == '777' and out['result']['used']['source'] == 'stored'
    assert json.loads(fields['variables'])['__relay_internal__pv__Brelayprovider'] is False


def test_query_takes_a_loaded_operation_id_with_stored_flags(tmp_path):
    out = query_case(tmp_path, {'CometNewsFeedPaginationQuery_facebookRelayOperation': '888',
                                'getAsyncParams': {'__function': ASYNC_PARAMS}},
                     fallback={'doc_id': '1', 'flags': {'f': 1}})
    fields = form(out['fetches'][0])
    assert fields['doc_id'] == '888' and json.loads(fields['variables'])['f'] == 1
    assert out['result']['used']['source'] == 'live_id'


@pytest.mark.parametrize('name', ['useCometUFICreateCommentMutation', 'CometUFIDeleteCommentSubscription',
                                  'SomeUnknownQuery'])
def test_only_read_queries_can_be_sent(tmp_path, name):
    out = query_case(tmp_path, {f'{name}.graphql': LIVE, 'getAsyncParams': {'__function': ASYNC_PARAMS}}, name=name,
                     fallback={'doc_id': '1'})
    assert out['fetches'] == [] and out['result']['refused']


def test_query_with_no_id_anywhere_sends_nothing(tmp_path):
    out = query_case(tmp_path, {'getAsyncParams': {'__function': ASYNC_PARAMS}})
    assert out['fetches'] == [] and out['result']['missing'] and out['result']['used']['source'] == 'none'


def test_page_fetch_is_same_origin_only(tmp_path):
    ok = run(tmp_path, kind='page', source=str(SNIPPETS / 'page.js'), args={'url': 'https://www.facebook.com/x'},
             page={'fetch': [{'status': 200, 'body': '<html>'}]})
    assert [f['method'] for f in ok['fetches']] == ['GET'] and ok['result']['body'] == '<html>'
    for url in ('https://m.facebook.com/x', 'https://evil.example/x', 'javascript:alert(1)', 'not a url'):
        refused = run(tmp_path, kind='page', source=str(SNIPPETS / 'page.js'), args={'url': url})
        assert refused['fetches'] == [] and refused['result']['refused'], url


@pytest.mark.parametrize('path', ['https://evil.example/', '//evil.example/x', 'groups/x'])
def test_route_only_moves_within_the_site(tmp_path, path):
    out = run(tmp_path, kind='page', source=str(SNIPPETS / 'route.js'), args={'path': path, 'names': []})
    assert out['result']['refused'] and out['fetches'] == []


def test_route_reports_queries_the_screen_loaded_and_its_requests(tmp_path):
    out = run(tmp_path, kind='page', source=str(SNIPPETS / 'route.js'),
              args={'path': '/search/top/?q=x', 'names': ['SearchCometResultsPaginatedResultsQuery']},
              page={'modules': {'SearchCometResultsPaginatedResultsQuery.graphql': {
                  'params': {'id': '999', 'providedVariables': {'p': 1}}}, 'CurrentUserInitialData': {'USER_ID': '7'}},
                  'resources': [5, 9, 9]})
    result = out['result']
    assert result['location'] == 'https://www.facebook.com/search/top/?q=x' and result['user_id'] == '7'
    assert result['live'] == {'SearchCometResultsPaginatedResultsQuery': {'doc_id': '999', 'flags': {'p': 1}}}
    assert result['resources'] == 4 and out['fetches'] == []


def test_state_reads_the_logged_in_user_without_a_request(tmp_path):
    out = run(tmp_path, kind='page', source=str(SNIPPETS / 'state.js'), args={},
              page={'modules': {'CurrentUserInitialData': {'USER_ID': 1000123}}, 'resources': [29]})
    assert out['result'] == {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'runtime': True,
                             'resources': 29}
    assert out['fetches'] == []


def test_program_lists_tabs_without_touching_a_page(tmp_path):
    out = run(tmp_path, kind='program', source=str(PROGRAM), function=str(SNIPPETS / 'state.js'),
              aside={'op': 'tabs'}, args={}, page={'tabs': [{'targetId': 'T1', 'url': 'https://x/'}]})
    assert aside.parse('\n'.join(out['result'])) == [{'targetId': 'T1', 'url': 'https://x/'}]


def test_program_reports_a_missing_tab(tmp_path):
    out = run(tmp_path, kind='program', source=str(PROGRAM), function=str(SNIPPETS / 'state.js'),
              aside={'op': 'evaluate', 'tab': 'NOPE'}, args={})
    with pytest.raises(Exception) as error:
        aside.parse('\n'.join(out['result']))
    assert getattr(error.value, 'reason', None) == 'tab_missing'


def test_large_results_are_chunked_without_splitting_a_surrogate_pair(tmp_path):
    size = 512 * 1024
    # JSON.stringify adds a leading quote, so the emoji's high surrogate falls on the last unit of the first chunk.
    value = 'a' * (size - 2) + '\U0001F600' + 'b' * (4 * size)
    out = run(tmp_path, kind='program', source=str(PROGRAM), function=str(SNIPPETS / 'state.js'),
              aside={'op': 'evaluate', 'tab': 'T1'}, args={}, evaluate_returns=value)
    lines = [json.loads(line) for line in out['result']]
    assert [line['kind'] for line in lines[:-1]] == ['chunk'] * (len(lines) - 1) and lines[-1]['kind'] == 'result'
    assert len(lines[0]['body']) == size - 1 and lines[1]['body'].startswith('\U0001F600')
    assert all(len(line) < 12 * 1024 * 1024 for line in out['result'])
    assert aside.parse('\n'.join(out['result'])) == value
