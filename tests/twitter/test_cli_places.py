"""Lists, communities, spaces, trends and notifications through the real CLI and a scripted Aside (P2 R5, R8 shapes,
synthetic values)."""
import json
import time

from conftest import ACCOUNT, known_tab, query_result, run_cli

RATE = {'x-rate-limit-limit': '500', 'x-rate-limit-remaining': '499', 'x-rate-limit-reset': str(int(time.time()) + 900)}
OWNER = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'author_a', 'name': 'Author A'}}


def queries(browser):
    return [c['args'] for c in browser.calls() if c['op'] == 'query']


def entries(items, bottom=None):
    if bottom:
        items = items + [{'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}}]
    return [{'type': 'TimelineAddEntries', 'entries': items}]


def by_name():
    return query_result({'data': {'user': {'result': OWNER}}}, headers=RATE)


# --- lists --------------------------------------------------------------------------------------------------------

def x_list(ident='1500000000000000001', name='Synthetic list', **extra):
    return {'id_str': ident, 'name': name, 'description': 'A list for tests', 'mode': 'Public', 'member_count': 42,
            'subscriber_count': 7, 'created_at': 1767225600000, 'following': False, 'is_member': False,
            'user_results': {'result': OWNER}, **extra}


def list_item(node):
    return {'entryId': f'list-{node["id_str"]}', 'content': {'itemContent': {'itemType': 'TimelineTwitterList',
                                                                             'list': node}}}


def user_lists(nodes, bottom=None):
    return query_result({'data': {'user': {'result': {'timeline': {'timeline': {
        'instructions': entries([list_item(n) for n in nodes], bottom)}}}}}}, headers=RATE)


def test_a_profiles_lists_tab_shows_its_lists_with_their_next_command(browser, data_dir):
    known_tab(browser, data_dir).respond('query', by_name()).respond('query', user_lists([x_list()]))
    code, out, _ = run_cli(browser, 'profile', 'https://x.com/author_a/lists')
    assert code == 0, out
    assert out.splitlines()[0].startswith('profile · tab=lists · 1 shown')
    assert '[l1] "Synthetic list" by @author_a · public · members=42 followers=7' in out
    assert 'url: "https://x.com/i/lists/1500000000000000001"' in out
    call = queries(browser)[-1]
    assert call['name'] == 'CombinedLists' and call['variables']['userId'] == '1000000001'


def test_memberships_are_the_lists_an_account_is_in(browser, data_dir):
    known_tab(browser, data_dir).respond('query', by_name()).respond('query', user_lists([x_list(name='Others list')]))
    code, out, _ = run_cli(browser, 'profile', 'author_a', '--tab', 'memberships')
    assert code == 0 and 'Others list' in out and queries(browser)[-1]['name'] == 'ListMemberships'


def test_list_tabs_are_not_dated(browser, data_dir):
    code, out, _ = run_cli(browser, 'profile', 'author_a', '--tab', 'lists', '--since', '2026-10-01')
    assert code == 2 and 'not dated' in json.loads(out)['message'] and browser.calls() == []


def post(ident, author=OWNER):
    return {'__typename': 'Tweet', 'rest_id': ident, 'core': {'user_results': {'result': author}},
            'legacy': {'full_text': f'post {ident}', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026'}}


def test_a_list_reads_its_posts_members_or_card(browser, data_dir):
    timeline = {'data': {'list': {'tweets_timeline': {'timeline': {'instructions': entries([
        {'entryId': 'tweet-11', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {'result': post('11')}}}}],
        'C1')}}}}}
    members = {'data': {'list': {'members_timeline': {'timeline': {'instructions': entries([
        {'entryId': 'user-1', 'content': {'itemContent': {'itemType': 'TimelineUser', 'user_results': {'result': OWNER}}}}])}}}}}
    card = {'data': {'list': x_list()}}
    for tab, body, operation, expect in (('posts', timeline, 'ListLatestTweetsTimeline', 'post 11'),
                                         ('members', members, 'ListMembers', '[a1] @author_a'),
                                         ('about', card, 'ListByRestId', '[l1] "Synthetic list"')):
        known_tab(browser, data_dir).respond('query', query_result(body, headers=RATE))
        code, out, _ = run_cli(browser, 'list', 'https://x.com/i/lists/1500000000000000001', '--tab', tab)
        assert code == 0 and expect in out, (tab, out)
        call = queries(browser)[-1]
        assert call['name'] == operation and call['variables']['listId'] == '1500000000000000001'


def test_a_list_x_does_not_return_is_unavailable(browser, data_dir):
    # measured 2026-10-19: for a list that does not exist X answers 200 with a stub that has no name and no owner
    stub = {'data': {'list': {'facepile_urls': [], 'id': 'TGlzdDox', 'id_str': '1'}}}
    known_tab(browser, data_dir).respond('query', query_result(stub, headers=RATE))
    code, out, _ = run_cli(browser, 'list', '1500000000000000001', '--tab', 'about')
    assert code == 9
