"""search and quotes through the real CLI and a scripted Aside (P2 R8: the app's search and quotes requests)."""
import json
import time

from conftest import known_tab, query_result, run_cli

RATE = {'x-rate-limit-limit': '50', 'x-rate-limit-remaining': '49', 'x-rate-limit-reset': str(int(time.time()) + 900)}
A = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'author_a', 'name': 'A'}}


def tweet(ident, **extra):
    return {'__typename': 'Tweet', 'rest_id': ident, 'core': {'user_results': {'result': A}},
            'legacy': {'full_text': f'post {ident}', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026'}, **extra}


def results(items, bottom='CUR1'):
    entries = []
    for node in items:
        key = 'user_results' if node['__typename'] == 'User' else 'tweet_results'
        entries.append({'entryId': f'x-{node["rest_id"]}', 'content': {'itemContent': {key: {'result': node}}}})
    if bottom:
        entries.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}})
    return query_result({'data': {'search_by_raw_query': {'search_timeline': {'timeline': {'instructions': [
        {'type': 'TimelineAddEntries', 'entries': entries}]}}}}}, headers=RATE)


def query_args(browser):
    return [c['args'] for c in browser.calls() if c['op'] == 'query']


def test_search_passes_the_query_as_typed_with_the_apps_variables(browser, data_dir):
    known_tab(browser, data_dir).respond('query', results([tweet('1')]))
    code, out, _ = run_cli(browser, 'search', 'claude code -is:retweet lang:en')
    assert code == 0, out
    [args] = query_args(browser)
    assert args['name'] == 'SearchTimeline'
    assert args['variables'] == {'rawQuery': 'claude code -is:retweet lang:en', 'count': 20, 'querySource': 'typed_query',
                                 'product': 'Top', 'withGrokTranslatedBio': True,
                                 'withQuickPromoteEligibilityTweetFields': False}
    assert out.splitlines()[0].startswith('search · sort=top · type=posts · 1 shown · stopped=limit_reached')


def test_latest_media_and_accounts_choose_their_product(browser, data_dir):
    for args, product in ((['--sort', 'latest'], 'Latest'), (['--type', 'media'], 'Media'), (['--type', 'accounts'], 'People')):
        node = A if product == 'People' else tweet('2')
        known_tab(browser, data_dir).respond('query', results([node], bottom=None))
        code, out, _ = run_cli(browser, 'search', 'ai', *args)
        assert code == 0, out
        sent = query_args(browser)[-1]['variables']
        assert sent['product'] == product and sent['withGrokTranslatedBio'] is (product == 'People')


def test_a_search_with_since_and_until_read_to_its_end_closes_its_window(browser, data_dir):
    known_tab(browser, data_dir).respond('query', results([tweet('3')])).respond('query', results([], bottom=None))
    code, out, _ = run_cli(browser, 'search', 'topic since:2026-10-12 until:2026-10-19', '--sort', 'latest', '--limit', '50')
    assert code == 0, out
    assert out.splitlines()[1] == 'window 2026-10-12..2026-10-19 · closed (server-filtered)'


def test_the_search_limit_before_any_result_is_exit_10(browser, data_dir):
    reset = int(time.time()) + 700
    known_tab(browser, data_dir).respond('query', query_result('{"errors":[{"code":88}]}', status=429, headers={
        'x-rate-limit-limit': '50', 'x-rate-limit-remaining': '0', 'x-rate-limit-reset': str(reset)}))
    code, out, _ = run_cli(browser, 'search', 'ai')
    envelope = json.loads(out)
    assert code == 10 and envelope['limit']['operation'] == 'SearchTimeline' and envelope['limit']['reset'] == reset


def test_quotes_ask_the_way_the_quotes_screen_does(browser, data_dir):
    quoted = tweet('9')
    known_tab(browser, data_dir).respond('query', results([tweet('4', quoted_status_result={'result': quoted})]))
    code, out, _ = run_cli(browser, 'quotes', 'https://x.com/author_a/status/9', '--chars', '0')
    assert code == 0, out
    [args] = query_args(browser)
    assert args['variables']['rawQuery'] == 'quoted_tweet_id:9 OR url:"status/9/video" OR url:"status/9/photo"'
    assert args['variables']['querySource'] == 'tdqt' and args['variables']['product'] == 'Top'
    assert 'quoting: @author_a' in out


def test_empty_search_text_is_refused(browser, data_dir):
    code, out, _ = run_cli(browser, 'search', '  ')
    assert code == 2 and browser.calls() == []
