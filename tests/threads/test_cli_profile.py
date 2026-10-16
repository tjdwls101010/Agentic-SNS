"""profile and about through the real CLI and a scripted Aside."""
import json

from conftest import START, known_tab, query_result, run_cli
from threads.session import Session

USER = {'pk': '1000000001', 'username': 'example.author', 'full_name': 'Example Author', 'follower_count': 1234,
        'biography': 'Writes about examples.', 'is_verified': True, 'text_post_app_is_private': False,
        'friendship_status': {'following': True}}
OTHER = {'pk': '1000000002', 'username': 'someone.else'}


def by_name(user=USER):
    return query_result({'data': {'xdt_text_app_user_by_username': user}})


def tab_body(items, has_next=False, cursor=None):
    edges = [{'node': {'thread_items': [{'post': item}]}} for item in items]
    return {'data': {'mediaData': {'edges': edges, 'page_info': {'has_next_page': has_next, 'end_cursor': cursor}}}}


def item(pk, author=USER, taken_at=1791428400, **info):
    return {'pk': pk, 'code': 'C' + pk[-4:], 'user': author, 'taken_at': taken_at, 'caption': {'text': 'p' + pk[-2:]},
            'text_post_app_info': info}


def test_the_threads_tab_finds_the_profile_then_reads_ten_a_page(browser, data_dir):
    known_tab(browser, data_dir).respond('query', by_name()).respond(
        'query', query_result(tab_body([item('3000000000000000401')], True, 'TABCUR')))
    code, out, _ = run_cli(browser, 'profile', '@Example.Author', '--json')
    result = json.loads(out)
    assert code == 0, result
    calls = [c['args'] for c in browser.calls() if c['op'] == 'query']
    assert calls[0]['name'] == 'BarcelonaProfilePageFallbackQuery' and calls[0]['variables']['username'] == 'example.author'
    assert calls[1]['name'] == 'BarcelonaProfileThreadsTabDirectQuery'
    assert calls[1]['variables']['userID'] == '1000000001' and calls[1]['variables']['first'] == 10
    assert result['tab'] == 'threads' and result.get('next')


def test_a_tab_url_reads_that_tab_and_a_conflicting_option_is_refused(browser, data_dir):
    known_tab(browser, data_dir)
    code, out, _ = run_cli(browser, 'profile', 'https://www.threads.com/@example.author/replies', '--tab', 'media')
    assert code == 2 and 'replies' in json.loads(out)['message']


def repost_screen(name='BarcelonaProfileRepostsTabDirectQuery'):
    preload = {'require': [{'preloaderID': f'adp_{name}RelayPreloader_1', 'queryID': '5551', 'queryName': name,
                            'variables': {'userID': '1000000001', 'first': 25,
                                          '__relay_internal__pv__BarcelonaIsLoggedInrelayprovider': True}}]}
    html = ('<script type="application/json">' + json.dumps(preload) + '</script>'
            '<script>{"csrf_token":"t","NON_FACEBOOK_USER_ID":"1000000009","username":"v"}</script>')
    return {'status': 200, 'url': START, 'body': html, 'explicit': 1, 'resources': 1, 'statuses': [200], 'signals': [],
            'location': START}


def test_the_reposts_tab_learns_its_query_from_its_screen_and_keeps_it_once_it_proves_itself(browser, data_dir):
    original = item('3000000000000000501', author=OTHER, taken_at=1760000000)
    repost = item('3000000000000000502', share_info={'reposted_post': original})
    known_tab(browser, data_dir).respond('query', by_name()).respond('page', repost_screen())
    browser.respond('query', query_result(tab_body([repost])))
    code, out, _ = run_cli(browser, 'profile', '@example.author', '--tab', 'reposts', '--json')
    result = json.loads(out)
    assert code == 0, result
    [page] = [c for c in browser.calls() if c['op'] == 'page']
    assert page['args']['path'] == '/@example.author/reposts'
    sent = [c['args'] for c in browser.calls() if c['op'] == 'query'][-1]
    assert sent['name'] == 'BarcelonaProfileRepostsTabDirectQuery' and sent['fallback']['doc_id'] == '5551'
    assert Session('default').renamed('profile_reposts') == 'BarcelonaProfileRepostsTabDirectQuery'
    assert result['tab_opened_requests'] == 1 and result['request_count'] == 3  # the screen read is setup
    assert result['results'][0]['reposted_post']['created_at'] == '2025-10-09T08:53:20Z'


def test_a_learned_query_that_returns_something_else_is_not_kept(browser, data_dir):
    known_tab(browser, data_dir).respond('query', by_name()).respond('page', repost_screen())
    browser.respond('query', query_result(tab_body([item('3000000000000000503', author=OTHER)])))
    code, out, _ = run_cli(browser, 'profile', '@example.author', '--tab', 'reposts', '--json')
    assert code == 6 and 'did not return' in json.loads(out)['message']
    assert Session('default').renamed('profile_reposts') is None


def test_an_empty_tab_of_a_private_profile_not_followed_is_unavailable(browser, data_dir):
    private = {**USER, 'text_post_app_is_private': True, 'friendship_status': {'following': False}}
    known_tab(browser, data_dir).respond('query', by_name(private)).respond('query', query_result(tab_body([])))
    code, out, _ = run_cli(browser, 'profile', '@example.author')
    assert code == 9 and json.loads(out)['error'] == 'unavailable'


def test_an_empty_tab_of_a_followed_private_profile_is_empty(browser, data_dir):
    private = {**USER, 'text_post_app_is_private': True, 'friendship_status': {'following': True}}
    known_tab(browser, data_dir).respond('query', by_name(private)).respond('query', query_result(tab_body([])))
    code, out, _ = run_cli(browser, 'profile', '@example.author')
    assert code == 7


def test_an_unknown_handle_is_unavailable(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result({'data': {'xdt_text_app_user_by_username': None}}))
    code, out, _ = run_cli(browser, 'profile', '@nobody.here')
    assert code in (6, 9)


def test_about_shows_the_card_with_unpublished_counts_unknown(browser, data_dir):
    known_tab(browser, data_dir).respond('query', by_name()).respond('query', query_result({'data': {'user': USER}}))
    code, out, _ = run_cli(browser, 'about', '@example.author')
    assert code == 0, out
    assert '[a1] @example.author (Example Author) · verified · followers=1234 following=? mutuals=?' in out
    assert 'bio: "Writes about examples."' in out


def test_about_refuses_a_card_about_someone_else(browser, data_dir):
    known_tab(browser, data_dir).respond('query', by_name()).respond('query', query_result({'data': {'user': OTHER}}))
    code, out, _ = run_cli(browser, 'about', '@example.author')
    assert code == 6
