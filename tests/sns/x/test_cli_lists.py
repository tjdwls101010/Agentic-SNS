"""graph and me through the real CLI and a scripted Aside (fixtures: paging.json account lists)."""
import json
import time

from tests.sns.x.scenes import ACCOUNT, known_tab, queries, query_result, run

RATE = {'x-rate-limit-limit': '500', 'x-rate-limit-remaining': '499', 'x-rate-limit-reset': str(int(time.time()) + 900)}


def account(ident, handle):
    return {'__typename': 'User', 'rest_id': ident, 'core': {'screen_name': handle, 'name': handle.title()}}


def accounts(nodes, bottom='CUR'):
    items = [{'entryId': f'user-{n["rest_id"]}', 'content': {'itemContent': {'itemType': 'TimelineUser',
                                                                             'user_results': {'result': n}}}} for n in nodes]
    if bottom:
        items.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}})
    return query_result({'data': {'user': {'result': {'timeline': {'timeline': {'instructions': [
        {'type': 'TimelineAddEntries', 'entries': items}]}}}}}}, headers=RATE)


def by_name():
    return query_result({'data': {'user': {'result': account('1000000001', 'author_a')}}}, headers=RATE)


def test_following_reads_one_page_of_accounts(browser):
    known_tab(browser).respond('x.query', by_name())
    browser.respond('x.query', accounts([account('2000000001', 'friend_one'), account('2000000002', 'friend_two')]))
    code, out, _ = run(browser, 'graph', 'author_a', 'following')
    assert code == 0, out
    assert 'x graph · relation=following · 2 shown' in out.splitlines()[0]
    assert '[a1] @friend_one (Friend_One)' in out and out.splitlines()[-1].startswith('more: ')
    calls = [c['args'] for c in queries(browser)]
    assert [c['name'] for c in calls] == ['UserByScreenName', 'Following']
    assert calls[1]['variables']['userId'] == '1000000001' and calls[1]['variables']['withGrokTranslatedBio'] is True


def test_three_pages_with_nothing_new_stop_an_account_list(browser):
    known_tab(browser).respond('x.query', by_name())
    one = account('2000000001', 'friend_one')
    for cursor in ('C1', 'C2', 'C3', 'C4'):
        browser.respond('x.query', accounts([one] if cursor == 'C1' else [], bottom=cursor))
    browser.respond('x.query', accounts([account('2000000009', 'never_reached')], bottom=None))
    code, out, _ = run(browser, 'graph', 'author_a', 'followers', '--limit', '50')
    assert code == 8 and 'nothing new' in out and 'never_reached' not in out
    assert [c['args']['name'] for c in queries(browser)].count('Followers') == 4


def test_verified_and_known_use_their_own_operations(browser):
    for relation, operation in (('verified', 'BlueVerifiedFollowers'), ('known', 'FollowersYouKnow')):
        known_tab(browser).respond('x.query', by_name()).respond('x.query', accounts([account('3', 'x_one')], bottom=None))
        code, out, _ = run(browser, 'graph', 'author_a', relation)
        assert code == 0, out
        assert [c['args']['name'] for c in queries(browser)][-1] == operation


def test_my_likes_use_the_logged_in_account(browser):
    post = {'__typename': 'Tweet', 'rest_id': '1850000000000000001', 'core': {'user_results': {'result': account('1', 'a')}},
            'legacy': {'full_text': 'liked', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026'}}
    timeline = query_result({'data': {'user': {'result': {'timeline': {'timeline': {'instructions': [{'type': 'TimelineAddEntries', 'entries': [
        {'entryId': 'tweet-1850000000000000001', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {'result': post}}}}]}]}}}}}},
        headers=RATE)
    known_tab(browser).respond('x.query', timeline)
    code, out, _ = run(browser, 'me', 'likes')
    assert code == 0 and 'liked' in out
    [call] = [c['args'] for c in queries(browser)]
    assert call['name'] == 'Likes' and call['variables']['userId'] == ACCOUNT


def test_empty_bookmarks_are_empty(browser):
    known_tab(browser).respond('x.query', query_result({'data': {'bookmark_timeline_v2': {'timeline': {'instructions': []}}}},
                                                               headers=RATE))
    code, out, _ = run(browser, 'me', 'bookmarks')
    assert code == 7 and json.loads(out)['error'] == 'empty'


def retweeters(nodes, bottom='CUR'):
    items = [{'entryId': f'user-{n["rest_id"]}', 'content': {'itemContent': {'itemType': 'TimelineUser',
                                                                             'user_results': {'result': n}}}} for n in nodes]
    if bottom:
        items.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}})
    return query_result({'data': {'retweeters_timeline': {'timeline': {'instructions': [
        {'type': 'TimelineAddEntries', 'entries': items}]}}}}, headers=RATE)


def test_reposts_reads_the_accounts_that_reposted_a_post(browser):
    known_tab(browser).respond('x.query', retweeters([account('2000000001', 'fan_one')]))
    code, out, _ = run(browser, 'reposts', 'https://x.com/author_a/status/1850000000000000009')
    assert code == 0, out
    assert out.splitlines()[0].startswith('x reposts · 1 shown') and '[a1] @fan_one' in out
    [call] = [c['args'] for c in queries(browser)]
    assert call['name'] == 'Retweeters' and call['variables']['tweetId'] == '1850000000000000009'
    assert call['chunk_hint'] == 'bundle.TweetActivity'  # a lazily loaded operation, loaded from its chunk by hint


def test_similar_accounts_are_xs_recommendation_for_that_profile(browser):
    module = {'entryId': 'similarto-1', 'content': {'entryType': 'TimelineTimelineModule', 'items': [
        {'entryId': 'similarto-1-user-3', 'item': {'itemContent': {'itemType': 'TimelineUser',
                                                                   'user_results': {'result': account('3', 'alike_one')}}}}]}}
    connect = query_result({'data': {'connect_tab_timeline': {'timeline': {'instructions': [
        {'type': 'TimelineAddEntries', 'entries': [module]}, {'type': 'TimelineTerminateTimeline', 'direction': 'Bottom'}]}}}},
        headers=RATE)
    known_tab(browser).respond('x.query', by_name()).respond('x.query', connect)
    code, out, _ = run(browser, 'graph', 'author_a', 'similar')
    assert code == 0, out
    assert '[a1] @alike_one' in out and 'recommend' in out
    call = [c['args'] for c in queries(browser)][-1]
    assert call['name'] == 'ConnectTabTimeline' and json.loads(call['variables']['context']) == {'contextualUserId': '1000000001'}
