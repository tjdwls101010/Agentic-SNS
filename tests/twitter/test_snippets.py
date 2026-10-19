"""The browser snippets, run as composed for the browser under Node with a fake x.com page (snippet_harness.mjs):
what they send, what they refuse, and what the tab's ledger and signal store report (fixtures: page, requests,
accounting)."""
import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from conftest import fixture
from twitter import x_web

HARNESS = Path(__file__).with_name('snippet_harness.mjs')
PAGE = fixture('page.json')
REQUESTS = fixture('requests.json')
ALLOWED = ['TweetDetail', 'SearchTimeline', 'Viewer', 'Retweeters', 'CreateTweet']
BEARER = 'AAAAAAAAAAAAAAAAAAAAA' + 'SYNTHETICBEARER' * 3  # the public bearer's shape, a made-up value


def definition(op):
    return ('e.exports={queryId:"%s",operationName:"%s",operationType:"%s",metadata:{featureSwitches:[%s],'
            'fieldToggles:[%s]}}' % (op['queryId'], op['operationName'], op['operationType'],
                                     ','.join('"%s"' % f for f in op['featureSwitches']),
                                     ','.join('"%s"' % f for f in op['fieldToggles'])))


def page(**extra):
    modules = {str(100 + i): definition(op) for i, op in enumerate(PAGE['webpack']['synthetic_definitions'])}
    modules['200'] = 'function(e,t){const n="x-client-transaction-id";if(rweb_client_transaction_id_enabled)return 1}'
    modules['201'] = 'function(e,t){const s="%s";t.headers={authorization:"Bearer "+s}}' % BEARER
    modules['202'] = 'function(e,t){const s="%s"}' % BEARER  # the same value in another module is fine
    spec = {'location': 'https://x.com/i/xskill', 'modules': modules,
            'exports': {'200': {'Ay': {'__function': None}, 'kc': {'__generator': True}}},
            'state': PAGE['store']['synthetic_state'],
            'cookie': 'ct0=SYNTHCSRF0000; twid=u%3D1000000099; lang=en'}
    spec.update(extra)
    return spec


def run(tmp_path, calls, page_spec):
    for index, call in enumerate(calls):
        source = tmp_path / f'call{index}.js'
        source.write_text(x_web.snippet(call.pop('snippet')))
        call['source'] = str(source)
    case = tmp_path / 'case.json'
    case.write_text(json.dumps({'calls': calls, 'page': page_spec}))
    done = subprocess.run(['node', str(HARNESS), str(case)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def query(**extra):
    return {'name': 'TweetDetail', 'allowed': ALLOWED, 'variables': {'focalTweetId': '1850000000000000001'},
            'toggles': {'withArticleRichContentState': True}, **extra}


def params(fetch):
    return {key: json.loads(values[0]) for key, values in parse_qs(urlsplit(fetch['url']).query).items()}


def test_query_sends_one_get_the_way_the_app_does(tmp_path):
    out = run(tmp_path, [{'snippet': 'query', 'args': query()}], page(fetch=[{'status': 200, 'body': '{"data":{}}',
              'headers': {'x-rate-limit-limit': '300', 'x-rate-limit-remaining': '299', 'x-rate-limit-reset': '1792300000'}}]))
    [fetch] = out['fetches']
    url = urlsplit(fetch['url'])
    assert fetch['method'] == 'GET' and fetch['credentials'] == 'include'
    assert url.path == '/i/api/graphql/SYNTHqTD01/TweetDetail'
    assert url.fragment.startswith('xs-') and len(url.fragment) > 8  # the nonce, never sent to x.com
    sent = params(fetch)
    assert sent['variables'] == {'focalTweetId': '1850000000000000001'}
    assert sent['features'] == {'synthetic_alpha_enabled': True, 'synthetic_beta_enabled': False}
    assert sent['fieldToggles'] == {'withArticleRichContentState': True, 'withArticlePlainText': False}
    assert set(fetch['headers']) == set(REQUESTS['headers']['set'])
    assert fetch['headers']['authorization'] == 'Bearer ' + BEARER
    assert fetch['headers']['x-csrf-token'] == 'SYNTHCSRF0000'
    assert fetch['headers']['x-twitter-client-language'] == 'en'
    assert fetch['headers']['x-client-transaction-id'] == 'TXID:GET:/i/api/graphql/SYNTHqTD01/TweetDetail'
    assert out['generator_calls'] == [['x.com', '/i/api/graphql/SYNTHqTD01/TweetDetail', 'GET']]  # no query, no fragment
    [result] = out['results']
    assert result['status'] == 200 and result['explicit'] == 1 and result['used']['source'] == 'live'
    assert result['headers'] == {'x-rate-limit-limit': '300', 'x-rate-limit-remaining': '299',
                                 'x-rate-limit-reset': '1792300000'}
    assert result['ours'] == 1 and result['resources'] == 0  # its own timing entry is not background


def test_a_feature_the_store_does_not_know_is_false_and_extra_names_are_added(tmp_path):
    out = run(tmp_path, [{'snippet': 'query', 'args': query(name='SearchTimeline', variables={'rawQuery': 'x'},
                                                            extra_features=['delta_enabled'], toggles={})}], page())
    sent = params(out['fetches'][0])
    assert sent['features'] == {'synthetic_alpha_enabled': True, 'synthetic_gamma_enabled': False, 'delta_enabled': False}
    assert 'fieldToggles' not in sent


@pytest.mark.parametrize('name, why', [('CreateTweet', 'mutation'), ('UnlistedQuery', 'not a read operation'),
                                       ('Tweet Detail', 'not a read operation')])
def test_what_is_not_a_listed_query_is_refused_before_anything_is_sent(tmp_path, name, why):
    allowed = ALLOWED + ['Tweet Detail']
    out = run(tmp_path, [{'snippet': 'query', 'args': query(name=name, allowed=allowed if name != 'UnlistedQuery' else ALLOWED)}],
              page())
    assert out['fetches'] == [] and why in out['results'][0]['refused']


@pytest.mark.parametrize('change, missing', [
    ({'exports': {}}, 'the signature generator'),
    ({'modules_extra': {'203': 'function(){const s="AAAAAAAAAAAAAAAAAAAAAOTHERVALUEOTHERVALUEOTHERVALUEOTHERVALUE"}'}}, 'the bearer'),
    ({'state': {'session': {}, 'featureSwitch': {'user': {'config': {}}}}}, 'a logged-in session'),
    ({'cookie': 'twid=u%3D1'}, 'a logged-in session'),
])
def test_a_missing_part_sends_nothing(tmp_path, change, missing):
    spec = page()
    extra_modules = change.pop('modules_extra', None)
    if extra_modules:
        spec['modules'].update(extra_modules)
    spec.update(change)
    out = run(tmp_path, [{'snippet': 'query', 'args': query()}], spec)
    assert out['fetches'] == [] and out['results'][0]['missing'] == missing


def test_an_operation_in_a_lazy_chunk_is_loaded_by_its_hint_then_sent(tmp_path):
    lazy = {'queryId': 'SYNTHqRT01', 'operationName': 'Retweeters', 'operationType': 'query',
            'featureSwitches': ['synthetic_alpha_enabled'], 'fieldToggles': []}
    spec = page(chunks={'68992': {'name': 'shared~bundle.QuoteTweetActivity~bundle.TweetActivity',
                                  'modules': {'752268': definition(lazy)}},
                        '12': {'name': 'bundle.Other', 'modules': {}}})
    out = run(tmp_path, [{'snippet': 'query', 'args': query(name='Retweeters', variables={'tweetId': '1'}, toggles={},
                                                            chunk_hint='bundle.TweetActivity')}], spec)
    assert out['chunk_loads'] == [68992]
    assert urlsplit(out['fetches'][0]['url']).path == '/i/api/graphql/SYNTHqRT01/Retweeters'
    assert out['results'][0]['used']['source'] == 'chunk'


def test_without_a_definition_the_stored_id_is_used(tmp_path):
    out = run(tmp_path, [{'snippet': 'query', 'args': query(name='Retweeters', variables={'tweetId': '1'}, toggles={},
                                                            fallback={'query_id': 'STOREDqRT', 'features': ['f1']})}],
              page())
    assert urlsplit(out['fetches'][0]['url']).path == '/i/api/graphql/STOREDqRT/Retweeters'
    assert params(out['fetches'][0])['features'] == {'f1': False}
    assert out['results'][0]['used']['source'] == 'stored'


def test_plain_timing_names_count_the_own_request_as_background(tmp_path):
    out = run(tmp_path, [{'snippet': 'query', 'args': query()}], page(fragment=False))
    assert out['results'][0]['ours'] == 0 and out['results'][0]['resources'] == 1


def test_an_own_entry_arriving_in_the_next_call_is_still_the_skills(tmp_path):
    out = run(tmp_path, [{'snippet': 'query', 'args': query()}, {'snippet': 'state', 'args': {}, 'late_own': True}],
              page(no_own_entry=True))
    assert out['results'][0]['ours'] == 0 and out['results'][0]['resources'] == 0  # nothing arrived during the call
    assert out['results'][1]['ours'] == 1 and out['results'][1]['resources'] == 0  # recognised by its nonce later


def test_a_background_entry_with_the_same_url_is_never_taken_for_the_skills(tmp_path):
    out = run(tmp_path, [{'snippet': 'query', 'args': query()}, {'snippet': 'state', 'args': {}, 'same_url': True}],
              page(no_own_entry=True))
    assert out['results'][1]['ours'] == 0 and out['results'][1]['resources'] == 1


def test_several_entries_with_the_same_url_only_the_nonce_one_is_the_skills(tmp_path):
    out = run(tmp_path, [{'snippet': 'query', 'args': query()},
                         {'snippet': 'state', 'args': {}, 'same_url': True, 'late_own': True}], page(no_own_entry=True))
    assert out['results'][1]['ours'] == 1 and out['results'][1]['resources'] == 1


def test_what_loaded_before_the_kit_is_counted_at_its_first_look(tmp_path):
    out = run(tmp_path, [{'snippet': 'state', 'args': {}}],
              page(buffered=[{'url': 'https://x.com/i/api/graphql/a/ViewerBadgeCounts', 'status': 200},
                             {'url': 'https://abs.twimg.com/responsive-web/client-web/main.js', 'status': 200},
                             {'url': 'https://api.x.com/1.1/jot/client_event.json', 'status': 200}]))
    state = out['results'][0]
    assert state['resources'] == 2  # the static CDN file is not counted
    assert state['user_id'] == '1000000099' and state['app'] and state['store'] and state['ct0']


def app_response(op, status=200, body='{"data":{}}', remaining=None):
    headers = {}
    if remaining is not None:
        headers = {'x-rate-limit-limit': '50', 'x-rate-limit-remaining': str(remaining), 'x-rate-limit-reset': '1792300000'}
    return {'url': f'https://x.com/i/api/graphql/abcSYNTH/{op}?variables=%7B%7D', 'status': status, 'body': body,
            'headers': headers}


def test_another_operations_limit_is_reported_not_stopped_on(tmp_path):
    out = run(tmp_path, [{'snippet': 'state', 'args': {}},
                         {'snippet': 'query', 'args': query(), 'app': [app_response('ViewerBadgeCounts', 429, remaining=0)]}],
              page())
    result = out['results'][1]
    assert len(out['fetches']) == 1 and result['status'] == 200
    [signal] = result['signals']
    assert signal['path'] == '/i/api/graphql/abcSYNTH/ViewerBadgeCounts' and signal['status'] == 429
    assert signal['rate'] == {'limit': 50, 'remaining': 0, 'reset': 1792300000}


def test_the_asked_operations_own_limit_stops_the_call(tmp_path):
    out = run(tmp_path, [{'snippet': 'state', 'args': {}},
                         {'snippet': 'query', 'args': query(), 'app': [app_response('TweetDetail', 429)]}], page())
    assert out['fetches'] == [] and out['results'][1]['stopped'] == 'limit'


@pytest.mark.parametrize('response', [app_response('HomeTimeline', 200, '{"errors":[{"code":326,"message":"locked"}]}'),
                                      app_response('HomeTimeline', 403, '<!DOCTYPE html><html class="cf"></html>'),
                                      app_response('HomeTimeline', 401, '{"errors":[{"code":32}]}')])
def test_a_lock_challenge_or_logout_signal_stops_every_call(tmp_path, response):
    out = run(tmp_path, [{'snippet': 'state', 'args': {}}, {'snippet': 'query', 'args': query(), 'app': [response]}],
              page())
    assert out['fetches'] == [] and out['results'][1]['stopped'] == 'signal'


@pytest.mark.parametrize('path', ['/account/access', '/i/flow/login'])
def test_a_tab_on_a_lock_or_login_page_sends_nothing(tmp_path, path):
    out = run(tmp_path, [{'snippet': 'query', 'args': query()}], page(location='https://x.com' + path))
    assert out['fetches'] == [] and out['results'][0]['stopped'] == 'location'
    assert out['results'][0]['moved'] == path


def test_signals_survive_a_reload_of_the_same_tab_but_not_a_new_tab(tmp_path):
    lock = app_response('HomeTimeline', 200, '{"errors":[{"code":326}]}')
    out = run(tmp_path, [{'snippet': 'state', 'args': {}}, {'snippet': 'state', 'args': {}, 'app': [lock]},
                         {'snippet': 'state', 'args': {}, 'reload': True}, {'snippet': 'state', 'args': {}, 'lost': True}],
              page())
    assert len(out['results'][1]['signals']) == 1
    assert len(out['results'][2]['signals']) == 1 and out['results'][3]['signals'] == []


def test_a_lock_code_in_a_json_typed_app_response_is_still_a_signal(tmp_path):
    lock = {**app_response('HomeTimeline', 200, '{"errors":[{"code":326}]}'), 'type': 'json'}
    out = run(tmp_path, [{'snippet': 'state', 'args': {}}, {'snippet': 'state', 'args': {}, 'app': [lock]}], page())
    assert [s['codes'] for s in out['results'][1]['signals']] == [[326]]


def test_acknowledged_signals_are_dropped(tmp_path):
    out = run(tmp_path, [{'snippet': 'state', 'args': {}},
                         {'snippet': 'state', 'args': {}, 'app': [app_response('ViewerBadgeCounts', 429)]},
                         {'snippet': 'state', 'args': {'__ack': 9999999999999}}], page())
    assert out['results'][1]['signals'] and out['results'][2]['signals'] == []


def test_arm_waits_for_the_document_then_installs_the_kit(tmp_path):
    out = run(tmp_path, [{'snippet': 'arm', 'args': {}}], page(location='about:blank'))
    assert out['results'] == [None]
    out = run(tmp_path, [{'snippet': 'arm', 'args': {}}, {'snippet': 'state', 'args': {}}],
              page(buffered=[{'url': 'https://x.com/i/api/graphql/a/DataSaverMode', 'status': 200}]))
    armed, state = out['results']
    assert armed['location'] == 'https://x.com/i/xskill' and 'installed_at' in armed
    assert state['resources'] == 1  # the same kit: its first look reports what the load did


def test_modules_lists_the_live_operations_and_loads_hinted_chunks(tmp_path):
    spec = page(chunks={'7': {'name': 'bundle.Notifications', 'modules': {'9': definition(
        {'queryId': 'SYNTHqNT', 'operationName': 'NotificationsTimeline', 'operationType': 'query', 'featureSwitches': [],
         'fieldToggles': []})}}})
    out = run(tmp_path, [{'snippet': 'modules', 'args': {'names': ['TweetDetail', 'NotificationsTimeline', 'Retweeters'],
                                                         'hints': ['bundle.Notifications']}}], spec)
    live = out['results'][0]['live']
    assert live['TweetDetail']['query_id'] == 'SYNTHqTD01' and live['NotificationsTimeline']['query_id'] == 'SYNTHqNT'
    assert live['Retweeters'] is None and out['results'][0]['generator'] and out['results'][0]['bearer']
    assert out['fetches'] == []


def test_blank_empties_the_tab(tmp_path):
    out = run(tmp_path, [{'snippet': 'blank', 'args': {}}], page())
    assert out['locations'] == ['about:blank'] and out['fetches'] == []


def test_no_snippet_spells_the_word_the_repl_refuses():
    for name in ('state', 'arm', 'query', 'modules', 'close', 'blank'):
        assert 'require(' not in x_web.snippet(name), name


def test_the_skills_own_response_is_not_kept_as_a_background_signal(tmp_path):
    # the skill classifies its own answer itself; if the hook saw it too, the same 429 would come back as a signal
    out = run(tmp_path, [{'snippet': 'state', 'args': {}}, {'snippet': 'query', 'args': query()},
                         {'snippet': 'state', 'args': {}}],
              page(fetch=[{'status': 429, 'body': '{"errors":[{"code":88}]}', 'headers': {'x-rate-limit-limit': '300',
                           'x-rate-limit-remaining': '0', 'x-rate-limit-reset': '1792300000'}}]))
    assert out['results'][1]['status'] == 429
    assert out['results'][1]['signals'] == [] and out['results'][2]['signals'] == []


def test_arm_says_whether_the_timing_buffer_was_still_whole_at_install(tmp_path):
    main = {'url': 'https://abs.twimg.com/responsive-web/client-web/main.SYNTH.js', 'status': 200}
    out = run(tmp_path, [{'snippet': 'arm', 'args': {}}], page(buffered=[main], entries_api=True))
    assert out['results'][0]['buffer_intact'] is True
    out = run(tmp_path, [{'snippet': 'arm', 'args': {}}], page(buffered=[], entries_api=True))
    assert out['results'][0]['buffer_intact'] is False
