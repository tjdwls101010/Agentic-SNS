"""Recovery when Threads refuses a query (plan: query rotation cases 1-4 and the per-command allowance), through the
real CLI, a scripted Aside and a local stand-in for the static CDN (THREADS_CDN_DIR)."""
import hashlib
import json

from conftest import LOGGED_IN_DOCUMENT, START, known_tab, query_result, run_cli, state
from test_cli_feed import feed_body, post
from threads.session import Session

REFUSED = {'errors': [{'message': 'Execution error', 'severity': 'CRITICAL'}]}
BUNDLE = 'https://static.cdninstagram.com/rsrc.php/v4/yZ/r/example.js'


def refused(source='stored'):
    return query_result(REFUSED, source=source)


def feed_page(ids, has_next=False, cursor=None):
    # sent with the id the skill passed (stored), as the tab does when the app has no module of its own for it
    return query_result(feed_body([[post(i, '2026-10-08T03:00:00Z')] for i in ids], has_next, cursor), source='stored')


def screen(preload=None, bundles=()):
    parts = []
    if preload:
        name, doc_id = preload
        parts.append('<script type="application/json">' + json.dumps({'require': [{
            'preloaderID': f'adp_{name}RelayPreloader_1', 'queryID': doc_id, 'queryName': name,
            'variables': {'__relay_internal__pv__BarcelonaIsLoggedInrelayprovider': True}}]}) + '</script>')
    parts += [f'<script src="{url}"></script>' for url in bundles]
    return {'status': 200, 'url': START, 'body': ''.join(parts), 'explicit': 1, 'resources': 1, 'statuses': [200],
            'signals': [], 'location': START}


def cdn(tmp_path, text):
    folder = tmp_path / 'cdn'
    folder.mkdir(exist_ok=True)
    (folder / (hashlib.sha1(BUNDLE.encode()).hexdigest() + '.js')).write_text(text)
    return {'THREADS_CDN_DIR': str(folder)}


def definition(name, doc_id, root=None, args=('after', 'before', 'data', 'sort_by', 'variant')):
    metadata = f'{{root_field_name:["{root}"]}}' if root else '{}'
    arguments = ','.join(f'{{defaultValue:null,kind:"LocalArgument",name:"{a}"}}' for a in args)
    return (f'__d("{name}_threadsRelayOperation",[],(function(t,n,r,o,a,i){{a.exports="{doc_id}"}}),null);\n'
            f'__d("{name}.threads.graphql",["BarcelonaIsLoggedIn.relayprovider"],(function(t,n,r,o,a,i,l){{'
            f'var e=[{arguments}];return{{fragment:{{argumentDefinitions:e,kind:"Fragment"}},kind:"Request",'
            f'operation:{{argumentDefinitions:e}},params:{{id:n("{name}_threadsRelayOperation"),metadata:{metadata},'
            f'name:"{name}",operationKind:"query",text:null,providedVariables:{{__relay_internal__pv__BarcelonaIs'
            f'LoggedInrelayprovider:n("BarcelonaIsLoggedIn.relayprovider")}}}}}}}}),null);\n')


def sent(browser):
    return [c['args'] for c in browser.calls() if c['op'] == 'query']


def test_a_refused_stored_id_is_learned_from_the_screen_preloader_once(browser, data_dir):
    known_tab(browser, data_dir).respond('query', refused())
    browser.respond('page', screen(('BarcelonaFeedDirectQuery', '9001')))
    browser.respond('query', feed_page(['A']))
    code, out, _ = run_cli(browser, 'feed', '--json')
    result = json.loads(out)
    assert code == 0, result
    assert [c['path'] for c in (x['args'] for x in browser.calls() if x['op'] == 'page')] == ['/']
    assert sent(browser)[1]['fallback']['doc_id'] == '9001'
    assert Session('default').query('BarcelonaFeedDirectQuery')['doc_id'] == '9001'
    assert result['tab_opened_requests'] == 1  # the screen read is setup, outside --max-requests


def test_a_query_missing_from_the_preloaders_is_learned_from_its_bundle(browser, data_dir, tmp_path):
    known_tab(browser, data_dir).respond('query', refused())
    browser.respond('page', screen(bundles=[BUNDLE])).respond('query', feed_page(['A']))
    env = cdn(tmp_path, definition('BarcelonaFeedDirectQuery', '9002'))
    code, out, _ = run_cli(browser, 'feed', '--json', env=env)
    assert code == 0, out
    assert sent(browser)[1]['fallback']['doc_id'] == '9002'


def test_a_query_defined_only_as_preloadable_parameters_is_learned_from_its_bundle(browser, data_dir, tmp_path):
    # the format Threads used for the feed query on 2026-10-17: an id and providers, no full definition
    text = ('__d("BarcelonaFeedDirectQuery$Parameters.threads",["BarcelonaIsLoggedIn.relayprovider"],(function(t,n,r,o,a,i)'
            '{"use strict";var e={kind:"PreloadableConcreteRequest",params:{id:"9003",metadata:{},name:"BarcelonaFeedDirectQuery",'
            'operationKind:"query",text:null,providedVariables:{__relay_internal__pv__BarcelonaIsLoggedInrelayprovider:'
            'n("BarcelonaIsLoggedIn.relayprovider")}}};a.exports=e}),null);\n')
    known_tab(browser, data_dir).respond('query', refused())
    browser.respond('page', screen(bundles=[BUNDLE])).respond('query', feed_page(['A']))
    code, out, _ = run_cli(browser, 'feed', '--json', env=cdn(tmp_path, text))
    assert code == 0, out
    assert sent(browser)[1]['fallback']['doc_id'] == '9003'


def test_a_refused_live_module_reloads_the_tab_once(browser, data_dir):
    known_tab(browser, data_dir).respond('query', refused(source='live'))
    browser.respond('navigate', {'navigating': True, 'explicit': 0, 'resources': 0, 'statuses': [], 'signals': [],
                                 'location': START})
    browser.respond('state', state(resources=30, document='<script>{"csrf_token":"t","NON_FACEBOOK_USER_ID":"1000000009","username":"v"}</script>'))
    browser.respond('state', state()).respond('query', feed_page(['A']))
    code, out, _ = run_cli(browser, 'feed', '--json')
    result = json.loads(out)
    assert code == 0, result
    assert browser.ops().count('navigate') == 1 and 'page' not in browser.ops()
    assert result['tab_opened_requests'] == 40


def test_a_renamed_query_is_found_by_its_arguments_and_root_and_kept_once_it_reads(browser, data_dir, tmp_path):
    args = ('after', 'before', 'meta_place_id', 'pinned_ids', 'power_search_info', 'query', 'recent',
            'search_surface', 'tagID', 'trend_fbid')
    root = 'xdt_api__v1__text_feed__search_results__connection_v2'
    text = definition('BarcelonaSearchResultsV2Query', '9003', root=root, args=args) + \
        definition('BarcelonaSomethingElseQuery', '9004', root='other_root', args=args)
    known_tab(browser, data_dir).respond('query', refused())
    browser.respond('page', screen(bundles=[BUNDLE]))
    body = {'data': {'searchResults': {'edges': [{'node': {'thread': {'thread_items': [{'post': {
        'pk': '3000000000000000801', 'code': 'Cs801', 'user': {'pk': '1', 'username': 'a'}}}]}}}],
        'page_info': {'has_next_page': False, 'end_cursor': None}}}}
    browser.respond('query', query_result(body))
    code, out, _ = run_cli(browser, 'search', 'words', '--json', env=cdn(tmp_path, text))
    assert code == 0, out
    assert sent(browser)[1]['name'] == 'BarcelonaSearchResultsV2Query'
    assert 'BarcelonaSearchResultsV2Query' in sent(browser)[1]['allowed']
    assert Session('default').renamed('search_posts') == 'BarcelonaSearchResultsV2Query'


def test_no_certain_successor_stops_with_an_update_needed(browser, data_dir, tmp_path):
    known_tab(browser, data_dir).respond('query', refused())
    browser.respond('page', screen(bundles=[BUNDLE]))
    code, out, _ = run_cli(browser, 'search', 'words', '--json', env=cdn(tmp_path, ''))
    assert code == 6 and 'update' in json.loads(out)['fix']
    assert browser.ops().count('query') == 1


def test_learning_is_capped_per_command_however_many_queries_it_uses(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', refused()).respond('page', screen(('BarcelonaFeedDirectQuery', '1'))) \
        .respond('query', feed_page(['A'], True, 'C1'))
    for n in range(2, 4):
        browser.respond('query', refused()).respond('page', screen(('BarcelonaFeedPaginationDirectQuery', str(n)))) \
            .respond('query', feed_page([chr(64 + n)], True, f'C{n}'))
    browser.respond('query', refused())
    code, out, _ = run_cli(browser, 'feed', '--limit', '10', '--json')
    result = json.loads(out)
    assert code == 8 and len(result['results']) == 3
    assert browser.ops().count('page') == 3 and 'recovery allowance' in result['message']


def test_a_lost_aside_connection_is_exit_3(browser, data_dir):
    known_tab(browser, data_dir).respond('query', {'__raw_stdout': '', '__exit': 1})
    code, out, err = run_cli(browser, 'feed')
    assert code == 3 and json.loads(out)['error'] == 'aside'


def test_a_refused_live_module_in_a_tab_emptied_meanwhile_gets_a_new_tab_not_a_reload(browser, data_dir):
    known_tab(browser, data_dir).respond('query', {**refused(source='live'), '__blank_after': True})
    browser.respond('open', {'tab': {'id': 'NEW1', 'url': START}})
    browser.respond('state', state(resources=30, document=LOGGED_IN_DOCUMENT)).respond('state', state())
    browser.respond('query', feed_page(['A']))
    code, out, _ = run_cli(browser, 'feed', '--json')
    assert code == 0, out
    assert 'navigate' not in browser.ops() and browser.ops().count('open') == 1
