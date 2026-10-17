"""graph and me through the real CLI and a scripted Aside (fixtures/records_lists.json shapes)."""
import json

from conftest import command_of, known_tab, query_result, run_cli, state

USER = {'pk': '1000000001', 'username': 'example.author'}


def by_name():
    return query_result({'data': {'xdt_text_app_user_by_username': USER}})


def accounts(names):
    return [{'node': {'pk': str(2000000000 + i), 'username': name}} for i, name in enumerate(names)]


def test_followers_report_the_profiles_total_and_stop_at_threads_sample(browser, data_dir):
    body = {'data': {'fetch__XDTUserDict': {'followers': {'edges': accounts(['a.one', 'b.two'])}},
                     'xdt_api__v1__text_feed__user_counts': {'follower_count': 5000}}}
    known_tab(browser, data_dir).respond('query', by_name()).respond('query', query_result(body))
    code, out, _ = run_cli(browser, 'graph', '@example.author', 'followers', '--json')
    result = json.loads(out)
    assert code == 0, result
    assert result['stop_reason'] == 'server_capped' and result['reported_total'] == 5000
    assert [r['username'] for r in result['results']] == ['a.one', 'b.two']
    call = [c['args'] for c in browser.calls() if c['op'] == 'query'][1]
    assert call['name'] == 'BarcelonaFriendshipsFollowersTabQuery' and call['variables']['userID'] == '1000000001'


def test_followers_stay_one_sample_even_when_threads_offers_a_cursor(browser, data_dir):
    first = {'data': {'fetch__XDTUserDict': {'followers': {'edges': accounts(['a.one']),
                                                           'page_info': {'has_next_page': True, 'end_cursor': 'F2'}}}}}
    known_tab(browser, data_dir).respond('query', by_name()).respond('query', query_result(first))
    code, out, _ = run_cli(browser, 'graph', '@example.author', 'followers', '--limit', '5', '--json')
    result = json.loads(out)
    assert code == 0 and result['stop_reason'] == 'server_capped' and 'next' not in result
    assert browser.ops().count('query') == 2


def test_following_pages_by_offset_and_more_continues_with_the_profiles_id(browser, data_dir):
    body = {'data': {'user': {'following': {'edges': accounts(['c.three']),
                                            'page_info': {'has_next_page': True, 'end_cursor': '20'}}}}}
    known_tab(browser, data_dir).respond('query', by_name()).respond('query', query_result(body))
    code, out, _ = run_cli(browser, 'graph', '@example.author', 'following')
    assert code == 0 and '[a1] @c.three' in out
    more = next(line for line in out.splitlines() if line.startswith('more: '))
    assert command_of(more)[:3] == ['graph', 'https://www.threads.com/@example.author', 'following']
    nxt = {'data': {'user': {'following': {'edges': accounts(['d.four'])[0:1],
                                           'page_info': {'has_next_page': False, 'end_cursor': None}}}}}
    nxt['data']['user']['following']['edges'][0]['node']['pk'] = '2000000077'
    browser.respond('state', state()).respond('query', query_result(nxt, doc_id='777'))
    code, out, _ = run_cli(browser, *command_of(more))
    assert code == 0 and '@d.four' in out
    calls = [c['args'] for c in browser.calls() if c['op'] == 'query']
    assert len(calls) == 3  # the continuation needs no new id lookup
    # observed 2026-10-17: without its providers Threads answers missing_required_variable_value
    assert calls[1]['endpoint'] == '/graphql/query' and calls[1]['root'] == 'fetch__XDTUserDict'
    assert '__relay_internal__pv__BarcelonaIsLoggedInrelayprovider' in dict(calls[1]['fallback']['providers'])
    # observed 2026-10-17: the tab query itself takes the offset; its refetchable twin is not on the profile screen
    assert calls[2]['name'] == 'BarcelonaFriendshipsFollowingTabQuery'
    assert calls[2]['variables']['userID'] == '1000000001' and calls[2]['variables']['after'] == '20'


def test_liked_is_one_batch(browser, data_dir):
    body = {'data': {'xdt_text_app_viewer': {'liked_media': {'edges': [{'node': {'thread_items': [{'post': {
        'pk': '3000000000000000131', 'code': 'CLike', 'user': USER, 'caption': {'text': 'liked'}}}]}}]}}}}
    known_tab(browser, data_dir).respond('query', query_result(body))
    code, out, _ = run_cli(browser, 'me', 'liked', '--json')
    result = json.loads(out)
    assert code == 0 and result['stop_reason'] == 'not_paginable' and result['collection'] == 'liked'
    assert [c['args']['name'] for c in browser.calls() if c['op'] == 'query'] == ['BarcelonaLikedPageViewerQuery']


def test_an_empty_saved_batch_is_empty(browser, data_dir):
    body = {'data': {'xdt_text_app_viewer': {'saved_media': {'edges': []}}}}
    known_tab(browser, data_dir).respond('query', query_result(body))
    code, out, _ = run_cli(browser, 'me', 'saved')
    assert code == 7
