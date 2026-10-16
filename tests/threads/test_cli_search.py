"""search through the real CLI and a scripted Aside."""
import json

from conftest import known_tab, query_result, run_cli

AUTHOR = {'pk': '1000000001', 'username': 'example.author'}


def results(pks, has_next=True, cursor='S2'):
    edges = [{'node': {'thread': {'thread_items': [{'post': {'pk': pk, 'code': 'C' + pk[-3:], 'user': AUTHOR,
                                                             'caption': {'text': 'about ai'}}}]}}} for pk in pks]
    return {'data': {'searchResults': {'edges': edges, 'page_info': {'has_next_page': has_next, 'end_cursor': cursor}}}}


def test_post_search_sends_the_words_and_the_order(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(results(['3000000000000000601'])))
    code, out, _ = run_cli(browser, 'search', 'example words', '--sort', 'recent', '--json')
    result = json.loads(out)
    assert code == 0 and result['type'] == 'posts' and result['sort'] == 'recent' and result.get('next')
    [call] = [c['args'] for c in browser.calls() if c['op'] == 'query']
    assert call['name'] == 'BarcelonaSearchResultsQuery' and call['endpoint'] == '/graphql/query'
    assert call['variables']['query'] == 'example words' and call['variables']['recent'] == 1
    assert call['variables']['search_surface'] == 'default'


def test_tag_search_and_the_next_page(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(results(['3000000000000000602'])))
    browser.respond('query', query_result(results(['3000000000000000603'], has_next=False, cursor=None)))
    code, out, _ = run_cli(browser, 'search', 'exampletag', '--type', 'tags', '--limit', '2', '--json')
    assert code == 0 and len(json.loads(out)['results']) == 2
    calls = [c['args'] for c in browser.calls() if c['op'] == 'query']
    assert calls[0]['variables']['search_surface'] == 'tags'
    assert calls[1]['name'] == 'BarcelonaSearchResultsRefetchableQuery' and calls[1]['variables']['after'] == 'S2'


def test_account_search_is_one_batch(browser, data_dir):
    body = {'data': {'xdt_api__v1__users__search_connection': {'edges': [
        {'node': {'pk': '1000000001', 'username': 'example.author', 'is_verified': True}},
        {'node': {'pk': '1000000005', 'username': 'example.author2'}}]}}}
    known_tab(browser, data_dir).respond('query', query_result(body))
    code, out, _ = run_cli(browser, 'search', 'example', '--type', 'accounts')
    assert code == 0 and 'stopped=not_paginable' in out and '[a2] @example.author2' in out
    assert 'sort=' not in out.splitlines()[0]


def test_account_search_takes_no_sort_and_empty_text_is_refused(browser, data_dir):
    known_tab(browser, data_dir)
    assert run_cli(browser, 'search', 'x', '--type', 'accounts', '--sort', 'recent')[0] == 2
    assert run_cli(browser, 'search', '  ')[0] == 2
