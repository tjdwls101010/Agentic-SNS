"""The browser snippets, run as composed for the browser under Node with a fake www.threads.com page
(snippet_harness.mjs): what they send, what they refuse, and what the tab's ledger and signal store report."""
import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs

import pytest

from conftest import fixture
from threads import threads_web

HARNESS = Path(__file__).with_name('snippet_harness.mjs')
REQUESTS = fixture('requests.json')
HEADERS = REQUESTS['headers']
ALLOWED = ['BarcelonaFeedPaginationDirectQuery', 'BarcelonaSearchResultsQuery']
PROVIDER = '__relay_internal__pv__BarcelonaIsLoggedInrelayprovider'


def page(**extra):
    state = HEADERS['tab_state']
    modules = {'CurrentUserInitialData': {'NON_FACEBOOK_USER_ID': '1000000009', 'USER_ID': '0', 'APP_ID': state['APP_ID']},
               'getAsyncParams': {'__function': state['async_params']},
               'BarcelonaIsLoggedIn.relayprovider': {'__provider': True}}
    modules.update(extra.pop('modules', {}))
    return {'location': 'https://www.threads.com/search', 'cookie': state['cookie'], 'modules': modules, **extra}


def run(tmp_path, calls, page_spec):
    for index, call in enumerate(calls):
        source = tmp_path / f'call{index}.js'
        source.write_text(threads_web.snippet(call.pop('snippet')))
        call['source'] = str(source)
    case = tmp_path / 'case.json'
    case.write_text(json.dumps({'calls': calls, 'page': page_spec}))
    done = subprocess.run(['node', str(HARNESS), str(case)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def query_args(**extra):
    return {'name': 'BarcelonaFeedPaginationDirectQuery', 'allowed': ALLOWED, 'variables': {'first': 10},
            'fallback': {'doc_id': '1234567890123456', 'providers': [[PROVIDER, 'BarcelonaIsLoggedIn.relayprovider']]},
            'asbd_id': '359341', **extra}


def form_of(fetch):
    return {key: values[0] for key, values in parse_qs(fetch['body']).items()}


def test_query_sends_one_post_the_way_the_app_does(tmp_path):
    out = run(tmp_path, [{'snippet': 'query', 'args': query_args()}],
              page(fetch=[{'status': 200, 'body': '{"data": {"feedData": {}}}'}]))
    [fetch] = out['fetches']
    assert fetch['method'] == 'POST' and fetch['url'] == 'https://www.threads.com/api/graphql/'
    expected = HEADERS['expected']
    for key, value in expected['headers'].items():
        assert fetch['headers'][key] == value, key
    assert fetch['headers']['x-asbd-id'] == '359341'
    form = form_of(fetch)
    for key, value in expected['form_includes'].items():
        assert form[key] == value, key
    assert form['av'] == '1000000009' and form['fb_api_req_friendly_name'] == 'BarcelonaFeedPaginationDirectQuery'
    assert json.loads(form['variables']) == {'first': 10, PROVIDER: True}  # a provider evaluated from its module
    assert out['results'][0]['used'] == {'source': 'stored', 'doc_id': '1234567890123456', 'flags': None}


def test_distillery_queries_go_to_graphql_query_with_their_root_field(tmp_path):
    out = run(tmp_path, [{'snippet': 'query', 'args': query_args(name='BarcelonaSearchResultsQuery', endpoint='/graphql/query',
                                                                 root='xdt_api__v1__text_feed__search_results__connection_v2')}],
              page(fetch=[{'status': 200, 'body': '{}'}]))
    [fetch] = out['fetches']
    assert fetch['url'] == 'https://www.threads.com/graphql/query'
    assert fetch['headers']['x-root-field-name'] == 'xdt_api__v1__text_feed__search_results__connection_v2'


def test_the_live_module_wins_over_the_stored_id(tmp_path):
    live = {'BarcelonaFeedPaginationDirectQuery.threads.graphql': {'params': {
        'id': '999', 'operationKind': 'query', 'providedVariables': {PROVIDER: False}}}}
    out = run(tmp_path, [{'snippet': 'query', 'args': query_args()}], page(modules=live, fetch=[{'status': 200, 'body': '{}'}]))
    form = form_of(out['fetches'][0])
    assert form['doc_id'] == '999' and json.loads(form['variables'])[PROVIDER] is False
    assert out['results'][0]['used']['source'] == 'live'


def test_a_live_id_without_its_module_uses_the_relay_operation(tmp_path):
    out = run(tmp_path, [{'snippet': 'query', 'args': query_args()}],
              page(modules={'BarcelonaFeedPaginationDirectQuery_threadsRelayOperation': '777'},
                   fetch=[{'status': 200, 'body': '{}'}]))
    assert form_of(out['fetches'][0])['doc_id'] == '777'
    assert out['results'][0]['used']['source'] == 'live_id'


def test_a_preloadable_query_sends_its_own_providers_new_ones_included(tmp_path):
    # Observed 2026-10-17: the feed query's live id and providers sat only in <Name>$Parameters.threads, with a
    # provider the stored list lacked; sending the live id without it made Threads fail the query.
    new = '__relay_internal__pv__BarcelonaHasMWRLocationConsumptionrelayprovider'
    live = {'BarcelonaFeedPaginationDirectQuery$Parameters.threads': {'params': {
                'id': '888', 'operationKind': 'query', 'providedVariables': {PROVIDER: True, new: False}}},
            'BarcelonaFeedPaginationDirectQuery_threadsRelayOperation': '888'}
    out = run(tmp_path, [{'snippet': 'query', 'args': query_args()}], page(modules=live, fetch=[{'status': 200, 'body': '{}'}]))
    form = form_of(out['fetches'][0])
    assert form['doc_id'] == '888' and json.loads(form['variables'])[new] is False
    assert out['results'][0]['used']['source'] == 'live' and out['results'][0]['used']['flags'][new] is False


def test_a_live_module_whose_provider_cannot_be_read_sends_nothing(tmp_path):
    live = {'BarcelonaFeedPaginationDirectQuery$Parameters.threads': {'params': {
        'id': '888', 'operationKind': 'query', 'providedVariables': {PROVIDER: True, 'broken': {'__throws': True}}}}}
    out = run(tmp_path, [{'snippet': 'query', 'args': query_args()}], page(modules=live, fetch=[{'status': 200, 'body': '{}'}]))
    assert out['fetches'] == [] and out['results'][0]['missing']


def test_a_stored_or_live_id_without_every_provider_value_sends_nothing(tmp_path):
    broken = {'BarcelonaIsLoggedIn.relayprovider': {'__provider': {'__throws': True}}}
    for extra in ({}, {'BarcelonaFeedPaginationDirectQuery_threadsRelayOperation': '777'}):
        out = run(tmp_path, [{'snippet': 'query', 'args': query_args()}],
                  page(modules={**broken, **extra}, fetch=[{'status': 200, 'body': '{}'}]))
        assert out['fetches'] == [] and out['results'][0]['missing'], extra


@pytest.mark.parametrize('name, allowed', [
    ('BarcelonaLikeMutation', ['BarcelonaLikeMutation']),
    ('BarcelonaMutationProbeQuery', ['BarcelonaMutationProbeQuery']),
    ('BarcelonaUnknownReadQuery', ALLOWED),
])
def test_refused_names_send_nothing(tmp_path, name, allowed):
    out = run(tmp_path, [{'snippet': 'query', 'args': query_args(name=name, allowed=allowed)}], page())
    assert out['fetches'] == [] and out['results'][0]['refused']


def test_a_live_module_that_is_no_query_is_refused(tmp_path):
    live = {'BarcelonaFeedPaginationDirectQuery.threads.graphql': {'params': {'id': '5', 'operationKind': 'mutation'}}}
    out = run(tmp_path, [{'snippet': 'query', 'args': query_args()}], page(modules=live))
    assert out['fetches'] == [] and 'not a query' in out['results'][0]['refused']


def test_no_snippet_spells_the_loader_call():
    for name in ('state', 'query', 'page', 'modules', 'blank', 'navigate'):
        assert 'require(' not in threads_web.snippet(name), name


def test_the_ledger_counts_threads_requests_not_static_files(tmp_path):
    entries = [{'url': 'https://www.threads.com/ajax/bz', 'status': 200},
               {'url': 'https://static.cdninstagram.com/rsrc.php/a.js', 'status': 200},
               {'url': 'https://scontent-ssn1-1.cdninstagram.com/v/p.jpg', 'status': 200},
               {'url': 'https://www.threads.com/graphql/query', 'status': 200}]
    out = run(tmp_path, [{'snippet': 'state', 'args': {}, 'before': entries}], page())
    assert out['results'][0]['resources'] == 2 and out['results'][0]['statuses'] == [200, 200]


def test_a_429_seen_between_calls_stops_the_next_query_before_it_sends(tmp_path):
    out = run(tmp_path, [{'snippet': 'state', 'args': {}},
                         {'snippet': 'query', 'args': query_args(), 'before': [{'url': 'https://www.threads.com/graphql/query', 'status': 429}]}],
              page())
    assert out['fetches'] == []
    assert out['results'][1]['stopped'] == 'signal' and 429 in out['results'][1]['statuses']


CHECKPOINT_BODY = json.dumps({'message': 'checkpoint_required', 'checkpoint_url': 'https://www.threads.com/challenge/x/',
                              'status': 'fail'})


def test_an_app_response_with_a_checkpoint_body_is_kept_and_stops_the_next_query(tmp_path):
    app = [{'url': 'https://www.threads.com/graphql/query', 'status': 200, 'body': CHECKPOINT_BODY}]
    out = run(tmp_path, [{'snippet': 'state', 'args': {}},
                         {'snippet': 'query', 'args': query_args(), 'app': app}], page())
    assert out['fetches'] == []
    [signal] = out['results'][1]['signals']
    assert signal['status'] == 200 and 'checkpoint_required' in signal['summary']
    assert json.loads(out['storage']['threadsSkillSignals'])[0]['summary'] == signal['summary']


def test_ordinary_app_responses_are_not_kept(tmp_path):
    app = [{'url': 'https://www.threads.com/graphql/query', 'status': 200,
            'body': '{"data":{"xdt_text_app_notification_badge":{"total_count":1}}}'}]
    out = run(tmp_path, [{'snippet': 'state', 'args': {}}, {'snippet': 'state', 'args': {}, 'app': app}], page())
    assert out['results'][1]['signals'] == []


def test_a_signal_survives_a_reload_of_the_same_tab_and_is_cleared_only_by_ack(tmp_path):
    app = [{'url': 'https://www.threads.com/graphql/query', 'status': 200, 'body': CHECKPOINT_BODY}]
    out = run(tmp_path, [{'snippet': 'state', 'args': {}},
                         {'snippet': 'state', 'args': {}, 'app': app},
                         {'snippet': 'state', 'args': {}, 'reload': True}], page())
    [signal] = out['results'][2]['signals']
    ack = signal['at']
    out = run(tmp_path, [{'snippet': 'state', 'args': {}},
                         {'snippet': 'state', 'args': {}, 'app': app},
                         {'snippet': 'state', 'args': {'__ack': 0}, 'reload': True},
                         {'snippet': 'state', 'args': {'__ack': 10 ** 13}}], page())
    assert out['results'][2]['signals'] and out['results'][3]['signals'] == []
    assert ack > 0


def test_a_lost_tab_keeps_no_signal(tmp_path):
    app = [{'url': 'https://www.threads.com/graphql/query', 'status': 200, 'body': CHECKPOINT_BODY}]
    out = run(tmp_path, [{'snippet': 'state', 'args': {}},
                         {'snippet': 'state', 'args': {}, 'app': app},
                         {'snippet': 'state', 'args': {}, 'lost': True}], page())
    assert out['results'][2]['signals'] == []  # a new tab starts empty: the skill checks what it shows instead


def test_state_reports_the_threads_account_and_the_document_when_asked(tmp_path):
    out = run(tmp_path, [{'snippet': 'state', 'args': {'document': True}}], page(html='<html>doc</html>'))
    result = out['results'][0]
    assert result['user_id'] == '1000000009' and result['app_id'] == HEADERS['tab_state']['APP_ID']
    assert result['document'] == '<html>doc</html>' and result['runtime'] is True


@pytest.mark.parametrize('path, allowed', [('/@example.user', True), ('/settings', False), ('//evil.example/', False)])
def test_page_reads_only_read_paths_without_following_redirects(tmp_path, path, allowed):
    out = run(tmp_path, [{'snippet': 'page', 'args': {'path': path}}],
              page(fetch=[{'status': 302, 'body': '', 'headers': {'location': '/@example.user'}}]))
    if allowed:
        [fetch] = out['fetches']
        assert fetch['url'] == 'https://www.threads.com' + path and fetch['redirect'] == 'manual'
        assert out['results'][0]['location_header'] == '/@example.user'
    else:
        assert out['fetches'] == [] and out['results'][0]['refused']


def test_blank_empties_the_tab_after_reporting(tmp_path):
    out = run(tmp_path, [{'snippet': 'blank', 'args': {}}], page())
    assert out['results'][0]['blanked'] is True and out['fetches'] == []


def test_navigate_goes_only_to_a_start_screen(tmp_path):
    out = run(tmp_path, [{'snippet': 'navigate', 'args': {'url': 'https://evil.example/'}}], page())
    assert out['results'][0]['refused']


# --- review findings (shared contracts): what the tab keeps must stay classifiable, and nothing is sent from a page
# --- that shows a block; the harness models the browser's single fetch (window.fetch is fetch) ---

MARKERS = threads_web.SIGNAL_MARKERS


def test_a_long_json_error_body_is_kept_as_a_classifiable_summary(tmp_path):
    body = json.dumps({'error': {'code': 4, 'message': 'Please wait'}, 'padding': 'x' * 6000})
    app = [{'url': 'https://www.threads.com/graphql/query', 'status': 200, 'body': body}]
    out = run(tmp_path, [{'snippet': 'state', 'args': {'__markers': MARKERS}},
                         {'snippet': 'state', 'args': {'__markers': MARKERS}, 'app': app}], page())
    [signal] = out['results'][1]['signals']
    assert threads_web.classify_signal(signal).block == 'rate_limit'


def test_post_text_with_alarming_words_is_not_kept(tmp_path):
    body = json.dumps({'data': {'media': {'caption': {'text': 'checkpoint challenge rate limit login_required csrf'}}}})
    app = [{'url': 'https://www.threads.com/graphql/query', 'status': 200, 'body': body}]
    out = run(tmp_path, [{'snippet': 'state', 'args': {'__markers': MARKERS}},
                         {'snippet': 'state', 'args': {'__markers': MARKERS}, 'app': app}], page())
    assert out['results'][1]['signals'] == []


def test_a_document_with_a_checkpoint_form_is_kept_by_its_marker(tmp_path):
    body = '<html>' + 'x' * 30000 + '<form method="post" action="/challenge/action/"></form></html>'
    app = [{'url': 'https://www.threads.com/', 'status': 200, 'body': body}]
    out = run(tmp_path, [{'snippet': 'state', 'args': {'__markers': MARKERS}},
                         {'snippet': 'state', 'args': {'__markers': MARKERS}, 'app': app}], page())
    [signal] = out['results'][1]['signals']
    assert threads_web.classify_signal(signal).block == 'checkpoint'


def test_state_reports_block_markers_in_the_current_document(tmp_path):
    out = run(tmp_path, [{'snippet': 'state', 'args': {'__markers': MARKERS}}],
              page(html='<html><form action="/challenge/x/"></form></html>'))
    assert out['results'][0]['markers'] == ['<form action="/challenge/']


@pytest.mark.parametrize('location', ['https://www.threads.com/challenge/', 'https://www.threads.com/accounts/login/'])
def test_nothing_is_sent_from_a_page_that_shows_a_block_or_a_login(tmp_path, location):
    out = run(tmp_path, [{'snippet': 'query', 'args': query_args()}, {'snippet': 'page', 'args': {'path': '/'}}],
              page(location=location))
    assert out['fetches'] == []
    assert [r['stopped'] for r in out['results']] == ['location', 'location']


def test_requests_finished_while_waiting_are_charged_to_the_call(tmp_path):
    waiting = [{'url': 'https://www.threads.com/ajax/bz', 'status': 200}] * 5
    out = run(tmp_path, [{'snippet': 'state', 'args': {}},
                         {'snippet': 'query', 'args': query_args(), 'before': waiting,
                          'during': [{'url': 'https://www.threads.com/api/graphql/', 'status': 200}]}],
              page(fetch=[{'status': 200, 'body': '{}'}]))
    assert out['results'][1]['resources'] == 6 and out['results'][1]['explicit'] == 1


def test_blank_actually_empties_the_tab(tmp_path):
    out = run(tmp_path, [{'snippet': 'blank', 'args': {}}], page())
    assert out['locations'][-1] == 'about:blank'


def test_our_own_suspect_response_is_seen_through_the_hooked_fetch(tmp_path):
    body = json.dumps({'errors': [{'code': 368, 'message': 'checkpoint'}]})
    out = run(tmp_path, [{'snippet': 'state', 'args': {'__markers': MARKERS}},
                         {'snippet': 'query', 'args': query_args(__markers=MARKERS)},
                         {'snippet': 'state', 'args': {'__markers': MARKERS}}],
              page(fetch=[{'status': 200, 'url': 'https://www.threads.com/api/graphql/', 'body': body}]))
    assert len(out['fetches']) == 1
    assert out['results'][2]['signals'] and out['results'][2]['signals'][0]['status'] == 200


# --- second review round ---

def test_nothing_is_sent_while_the_document_shows_a_checkpoint_form(tmp_path):
    out = run(tmp_path, [{'snippet': 'query', 'args': query_args(__markers=MARKERS)}],
              page(html='<html><form action="/challenge/x/"></form></html>'))
    assert out['fetches'] == [] and out['results'][0]['stopped'] == 'markers'
    assert out['results'][0]['markers'] == ['<form action="/challenge/']


def test_a_checkpoint_marker_deep_inside_a_json_answer_is_kept(tmp_path):
    body = json.dumps({'data': None, 'extensions': {'checkpoint_required': True}})
    app = [{'url': 'https://www.threads.com/graphql/query', 'status': 200, 'body': body}]
    out = run(tmp_path, [{'snippet': 'state', 'args': {'__markers': MARKERS}},
                         {'snippet': 'state', 'args': {'__markers': MARKERS}, 'app': app}], page())
    [signal] = out['results'][1]['signals']
    assert threads_web.classify_signal(signal).block == 'checkpoint'


def test_a_signal_kept_in_the_earlier_format_is_still_classified():
    legacy = {'url': 'https://www.threads.com/graphql/query', 'status': 200, 'at': 1,
              'body': json.dumps({'message': 'checkpoint_required', 'checkpoint_url': 'https://www.threads.com/challenge/'})}
    assert threads_web.classify_signal(legacy).block == 'checkpoint'
