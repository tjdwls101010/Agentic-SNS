"""What a request of the dedicated tab is allowed to be (fixtures/requests.json): the registry of the 35 wired operations
and the variables each surface sends, and, in the Node snippet harness with the webpack page model, the read list, the
GET method, the feature values, the header set and what is never sent."""
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from sns.x import web
from tests.sns.fakes.snippet_runner import needs_node, run as run_harness
from tests.sns.x.data import fixture
from tests.sns.x.scenes import known_tab, queries, query_result, run as run_cli, state

REQUESTS = fixture('requests.json')
PAGE = fixture('page.json')
SURFACES = REQUESTS['variables']['surfaces']
BEARER = 'AAAAAAAAAAAAAAAAAAAAA' + 'SYNTHETICBEARER' * 3  # the public bearer's shape, a made-up value


USER = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'example_author', 'name': 'Example'}}


def home(ids, bottom='CUR1'):
    """A HomeTimeline answer with these posts and a Bottom cursor (none when `bottom` is None)."""
    entries = [{'entryId': f'tweet-{i}', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {
        'result': {'__typename': 'Tweet', 'rest_id': i, 'core': {'user_results': {'result': USER}},
                   'legacy': {'full_text': f'post {i}', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026'}}}}}}
               for i in ids]
    if bottom:
        entries.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}})
    return {'data': {'home': {'home_timeline_urt': {'instructions': [{'type': 'TimelineAddEntries',
                                                                       'entries': entries}]}}}}


RATE = {'x-rate-limit-limit': '500', 'x-rate-limit-remaining': '499', 'x-rate-limit-reset': '1900000000'}


# --- the registry (operations.json) ------------------------------------------------------------------------------

def test_the_registry_holds_exactly_the_35_wired_operations_of_the_apps_snapshot():
    assert sorted(web.OPERATIONS) == sorted(REQUESTS['read_only']['read_list']) == web.READ_OPERATIONS
    assert len(web.OPERATIONS) == 35
    for dropped in ('UserOriginalsTimeline', 'UserVideoTimeline', 'CommunityAboutTimeline'):
        assert dropped not in web.OPERATIONS


def test_every_registered_operation_is_used_by_some_read_and_every_read_is_registered():
    """Wired means a feature or the client names it; an operation nobody names is dead weight in the table."""
    from pathlib import Path
    root = Path(web.__file__).resolve().parents[1]
    source = '\n'.join(p.read_text(encoding='utf-8') for p in root.rglob('*.py') if p.name != 'targets.py')
    unused = [name for name in web.OPERATIONS if f"'{name}'" not in source]
    assert not unused, unused


@pytest.mark.parametrize('name', sorted(web.OPERATIONS))
def test_an_operation_entry_says_where_its_data_sits_and_what_it_sends(name):
    spec = web.OPERATIONS[name]
    assert set(spec) >= {'query_id', 'root', 'variables', 'field_toggles', 'chunk_hint', 'source'}
    assert spec['root'].startswith('data.') and spec['query_id'] and isinstance(spec['variables'], dict)


CALLER_SET = ('rawQuery', 'context', 'product', 'querySource', 'withGrokTranslatedBio', 'rankingMode')


def placeholder(value):
    items = value if isinstance(value, list) else [value]
    return all(isinstance(item, str) and item.startswith('<') for item in items)


@pytest.mark.parametrize('surface', sorted(SURFACES))
def test_a_surfaces_variables_are_the_registrys_defaults_plus_what_its_caller_adds(surface):
    """The fixture lists what a surface sends: placeholders (`<id>`) are the caller's own arguments, everything else is
    the registry default of its operation, and the field toggles are the registry's."""
    case = SURFACES[surface]
    spec = web.OPERATIONS[case['operation']]
    for key, value in case['variables'].items():
        if key in CALLER_SET:
            continue  # the caller sets it (or its variant does), whatever the registry default says
        if placeholder(value):
            assert key not in spec['variables'], (surface, key)  # a caller's argument, not a default
        else:
            assert spec['variables'].get(key) == value, (surface, key)
    assert set(spec['variables']) <= set(case['variables']), surface  # a default the fixture does not show is stale
    assert spec['field_toggles'] == case['field_toggles'], surface


def test_a_cursor_is_sent_only_when_continuing(browser):
    """rules[0..2]: the first page sends no cursor; the page after sends it as the cursor variable; the profile's user id
    comes from the handle once and is kept for later pages."""
    known_tab(browser)
    browser.respond('x.query', query_result(home(['1850000000000000001']), headers=RATE))
    browser.respond('x.query', query_result(home(['1850000000000000002'], bottom=None), headers=RATE))
    code, out, _ = run_cli(browser, 'feed', '--limit', '2')
    assert code == 0, out
    first, second = [c['args']['variables'] for c in queries(browser)]
    assert 'cursor' not in first and second['cursor'] == 'CUR1'


def test_the_read_list_sent_to_the_page_is_the_registry(browser):
    known_tab(browser).respond('x.query', query_result(home(['1850000000000000001']), headers=RATE))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 0, out
    [call] = queries(browser)
    assert call['args']['allowed'] == web.READ_OPERATIONS and call['args']['name'] in web.READ_OPERATIONS


# --- search variants, as the client sends them -----------------------------------------------------------------------

def search_page():
    return {'data': {'search_by_raw_query': {'search_timeline': {'timeline': {'instructions': [
        {'type': 'TimelineAddEntries', 'entries': []}]}}}}}


@pytest.mark.parametrize('arguments, product', [(['--type', 'posts', '--sort', 'latest'], 'Latest'),
                                                (['--type', 'posts', '--sort', 'top'], 'Top'),
                                                (['--type', 'accounts'], 'People'), (['--type', 'media'], 'Media')])
def test_search_sends_the_products_variables_the_fixture_lists(browser, arguments, product):
    case = SURFACES['search']
    known_tab(browser).respond('x.query', query_result(search_page()))
    run_cli(browser, 'search', 'words', *arguments)
    [call] = queries(browser)
    sent = call['args']['variables']
    expected = {**case['variables'], **case['variants'].get(product, {}), 'rawQuery': 'words'}
    assert call['args']['name'] == 'SearchTimeline'
    assert {k: sent[k] for k in expected} == expected


def test_quotes_asks_the_way_xs_own_quotes_screen_asks(browser):
    case = SURFACES['quotes']
    known_tab(browser)
    for sort, variant in (('recent', {}), ('top', case['variants']['top'])):
        browser.respond('x.query', query_result(search_page()))
        run_cli(browser, 'quotes', '1850000000000000001', '--sort', sort)
        browser.respond('x.state', state())  # the next command looks at the known tab again
        expected = {**case['variables'], **variant,
                    'rawQuery': case['variables']['rawQuery'].replace('<id>', '1850000000000000001')}
        assert {k: queries(browser)[-1]['args']['variables'][k] for k in expected} == expected


# --- the page function, in the harness -------------------------------------------------------------------------------

def definition(op):
    return ('e.exports={queryId:"%s",operationName:"%s",operationType:"%s",metadata:{featureSwitches:[%s],'
            'fieldToggles:[%s]}}' % (op['queryId'], op['operationName'], op['operationType'],
                                     ','.join('"%s"' % f for f in op['featureSwitches']),
                                     ','.join('"%s"' % f for f in op['fieldToggles'])))


def page(*, defined=(), store=None, cookie='ct0=SYNTHCSRF0000; twid=u%3D1000000099; lang=en', bearer=True,
         generator=True):
    modules = {str(100 + i): definition(op) for i, op in enumerate(defined)}
    exports = {}
    if generator:
        modules['200'] = 'function(e,t){const n="x-client-transaction-id";if(rweb_client_transaction_id_enabled)return 1}'
        exports['200'] = {'Ay': {'__function': None}, 'kc': {'__generator': True}}
    if bearer:
        modules['201'] = 'function(e,t){const s="%s";t.headers={authorization:"Bearer "+s}}' % BEARER
    return {'location': 'https://x.com/i/xskill', 'modules': modules, 'exports': exports, 'cookie': cookie,
            'state': {'session': {'user_id': '1000000099', 'language': 'en'},
                      'featureSwitch': {'user': {'config': store or {}}}}}


def op(name, kind='query', switches=(), toggles=()):
    return {'queryId': f'SYNTHq{name[:6]}', 'operationName': name, 'operationType': kind,
            'featureSwitches': list(switches), 'fieldToggles': list(toggles)}


def call(tmp_path, spec, **args):
    base = {'name': 'TweetDetail', 'allowed': web.READ_OPERATIONS, 'variables': {}, 'toggles': {}}
    sources = {name: web.snippet(name) for name in web.SNIPPET_NAMES}
    return run_harness(tmp_path, 'webpack', [{'snippet': 'query', 'args': {**base, **args}}], spec, sources)


@needs_node
@pytest.mark.parametrize('case', REQUESTS['read_only']['cases'], ids=lambda c: f"{c['operation']}-{c['operationType']}")
def test_read_only_only_a_listed_query_the_app_defines_as_a_query_is_sent(tmp_path, case):
    name = case['operation']
    allowed = web.READ_OPERATIONS + ['CreateTweet', 'FavoriteTweet']  # a mutation's name on the list is still refused
    if name == 'SomeUnlistedQuery':
        allowed = web.READ_OPERATIONS
    out = call(tmp_path, page(defined=[op(name, case['operationType'])]), name=name, allowed=allowed)
    if case['expected'] == 'send':
        assert len(out['fetches']) == 1 and out['results'][0]['explicit'] == 1
    else:
        assert out['fetches'] == [] and out['results'][0]['refused']


@needs_node
@pytest.mark.parametrize('case', REQUESTS['method']['cases'], ids=lambda c: c['operation'])
def test_every_query_is_a_get_with_json_in_the_query_string(tmp_path, case):
    name = case['operation']
    out = call(tmp_path, page(defined=[op(name, case['operationType'], toggles=['withArticleRichContentState'])]),
               name=name, variables={'focalTweetId': '1'}, toggles={'withArticleRichContentState': True})
    [fetch] = out['fetches']
    assert fetch['method'] == case['expected'] == 'GET'
    query = parse_qs(urlsplit(fetch['url']).query)
    assert set(query) == {'variables', 'features', 'fieldToggles'}
    assert all(isinstance(json.loads(values[0]), dict) for values in query.values())


@needs_node
def test_features_are_the_modules_switches_with_the_stores_values_and_false_when_unknown(tmp_path):
    simple, retry = REQUESTS['features']['cases']
    out = call(tmp_path, page(defined=[op('TweetDetail', switches=simple['featureSwitches'])], store=simple['store']))
    assert json.loads(parse_qs(urlsplit(out['fetches'][0]['url']).query)['features'][0]) == simple['expected']
    out = call(tmp_path, page(defined=[op('TweetDetail', switches=retry['featureSwitches'])], store=retry['store']),
               extra_features=retry['missing_named'])
    assert json.loads(parse_qs(urlsplit(out['fetches'][0]['url']).query)['features'][0]) == retry['expected_retry']


@needs_node
def test_field_toggles_take_their_values_from_the_registry_and_unknown_names_are_false(tmp_path):
    toggles = web.OPERATIONS['TweetDetail']['field_toggles']
    assert toggles['withArticleRichContentState'] and toggles['withArticleSummaryText'] and toggles['withArticleVoiceOver']
    out = call(tmp_path, page(defined=[op('TweetDetail', toggles=[*toggles, 'brandNewToggle'])]), toggles=toggles)
    sent = json.loads(parse_qs(urlsplit(out['fetches'][0]['url']).query)['fieldToggles'][0])
    assert sent == {**toggles, 'brandNewToggle': False}


@needs_node
def test_the_request_carries_exactly_the_apps_headers_and_none_it_never_sends(tmp_path):
    headers = REQUESTS['headers']
    out = call(tmp_path, page(defined=[op('TweetDetail')]))
    [fetch] = out['fetches']
    assert set(fetch['headers']) == set(headers['set'])
    assert fetch['headers']['authorization'] == 'Bearer ' + BEARER and fetch['headers']['x-csrf-token'] == 'SYNTHCSRF0000'
    assert fetch['headers']['x-client-transaction-id'] == 'TXID:GET:/i/api/graphql/SYNTHqTweetD/TweetDetail'
    for never in headers['never'] + list(headers['polling_only']):
        assert never not in {k.lower() for k in fetch['headers']}


@needs_node
@pytest.mark.parametrize('case', REQUESTS['headers']['missing_cases'], ids=lambda c: c['missing'])
def test_a_request_is_not_sent_when_a_source_of_its_headers_is_missing(tmp_path, case):
    change = {'bearer': {'bearer': False}, 'ct0': {'cookie': 'twid=u%3D1'}, 'generator': {'generator': False}}[case['missing']]
    out = call(tmp_path, page(defined=[op('TweetDetail')], **change))
    result = out['results'][0]
    reason = 'login' if result.get('login') else 'missing' if result.get('missing') else None
    assert out['fetches'] == [] and result['explicit'] == 0 and case['expected']['sent'] is False
    assert reason == case['expected']['reason']


def test_the_clients_reads_all_come_from_the_registrys_roots(browser):
    """A read whose data sits where the registry says is `ok`; the client cuts the answer at the registry's root."""
    known_tab(browser).respond('x.query', query_result(home(['1850000000000000001']), headers=RATE))
    code, out, _ = run_cli(browser, 'feed', '--json')
    assert code == 0 and json.loads(out)['results'][0]['id'] == '1850000000000000001'
    assert web.OPERATIONS['HomeTimeline']['root'] == 'data.home.home_timeline_urt.instructions'
