"""search through the real CLI and a scripted Aside."""
import json

from conftest import command_of, known_tab, query_result, run_cli, state

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


def dated(pk, when):
    return {'node': {'thread': {'thread_items': [{'post': {'pk': pk, 'code': 'C' + pk[-3:], 'user': AUTHOR,
                                                           'taken_at': when, 'caption': {'text': 'about ai'}}}]}}}


def test_dates_and_author_are_filtered_by_threads_and_the_window_closes_when_read_to_the_end(browser, data_dir):
    # 2026-10-01 00:00 and 2026-10-04 00:00 in Asia/Seoul (UTC+9): the until day is included
    body = {'data': {'searchResults': {'edges': [dated('3000000000000000611', 1790942400)],
                                       'page_info': {'has_next_page': False, 'end_cursor': None}}}}
    known_tab(browser, data_dir).respond('query', query_result(body))
    code, out, _ = run_cli(browser, 'search', 'words', '--sort', 'recent', '--since', '2026-10-01', '--until',
                           '2026-10-03', '--from', '@example.author', '--json', env={'TZ': 'Asia/Seoul'})
    result = json.loads(out)
    assert code == 0, result
    [call] = [c['args'] for c in browser.calls() if c['op'] == 'query']
    assert call['variables']['power_search_info'] == {'author_username': 'example.author',
                                                      'lookback_min_unixtime': 1790780400,
                                                      'lookback_max_unixtime': 1791039600}
    assert result['window'] == {'since': '2026-10-01', 'until': '2026-10-03', 'coverage': 'closed (server-filtered)'}


def test_the_next_page_keeps_the_filter(browser, data_dir):
    page1 = {'data': {'searchResults': {'edges': [dated('3000000000000000612', 1790942400)],
                                        'page_info': {'has_next_page': True, 'end_cursor': 'S2'}}}}
    known_tab(browser, data_dir).respond('query', query_result(page1))
    code, out, _ = run_cli(browser, 'search', 'words', '--from', 'example.author', '--json')
    first = json.loads(out)
    assert code == 0 and first['next'] and '--from example.author' in first['next']
    page2 = {'data': {'searchResults': {'edges': [dated('3000000000000000613', 1790942400)],
                                        'page_info': {'has_next_page': False, 'end_cursor': None}}}}
    browser.respond('state', state()).respond('query', query_result(page2))
    code, out, _ = run_cli(browser, *command_of('more: ' + first['next']))
    assert code == 0, out
    last = [c['args'] for c in browser.calls() if c['op'] == 'query'][-1]
    assert last['variables']['after'] == 'S2'
    assert last['variables']['power_search_info'] == {'author_username': 'example.author'}


def test_filters_apply_to_posts_and_tags_only(browser, data_dir):
    known_tab(browser, data_dir)
    assert run_cli(browser, 'search', 'x', '--type', 'accounts', '--since', '2026-10-01')[0] == 2
    assert run_cli(browser, 'search', 'x', '--from', 'not a handle!')[0] == 2
    assert browser.ops().count('query') == 0


def test_a_dated_search_reads_on_until_threads_has_no_more(browser, data_dir):
    pages = [{'data': {'searchResults': {'edges': [dated(f'300000000000000062{n}', 1790942400)],
                                         'page_info': {'has_next_page': n < 2, 'end_cursor': f'S{n + 1}' if n < 2 else None}}}}
             for n in range(3)]
    known_tab(browser, data_dir)
    for body in pages:
        browser.respond('query', query_result(body))
    code, out, _ = run_cli(browser, 'search', 'words', '--since', '2026-10-01', '--json', env={'TZ': 'Asia/Seoul'})
    result = json.loads(out)
    assert code == 0 and len(result['results']) == 3 and result['window']['coverage'] == 'closed (server-filtered)'
