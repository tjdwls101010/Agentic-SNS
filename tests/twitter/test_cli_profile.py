"""profile and about through the real CLI and a scripted Aside (fixtures: paging.json window cases, profile_access;
records_accounts.json)."""
import json
import time
from datetime import date, timedelta

from conftest import command_of, known_tab, query_result, run_cli, state

RATE = {'x-rate-limit-limit': '150', 'x-rate-limit-remaining': '149', 'x-rate-limit-reset': str(int(time.time()) + 900)}


def user(ident='1000000001', handle='author_a', **extra):
    return {'__typename': 'User', 'rest_id': ident, 'core': {'screen_name': handle, 'name': 'Author A',
                                                              'created_at': 'Mon Jan 02 03:04:05 +0000 2012'},
            'relationship_counts': {'followers': 1200, 'following': 300}, 'tweet_counts': {'tweets': 4500},
            'is_blue_verified': True, 'privacy': {'protected': False},
            'relationship_perspectives': {'following': False, 'followed_by': False}, **extra}


def by_name(node):
    return query_result({'data': {'user': {'result': node}}}, headers=RATE)


def stamp(days_ago):
    return time.strftime('%a %b %d %H:%M:%S +0000 %Y', time.gmtime(time.time() - days_ago * 86400))


def tweet(ident, days_ago=0):
    return {'__typename': 'Tweet', 'rest_id': ident, 'core': {'user_results': {'result': user()}},
            'legacy': {'full_text': f'post {ident}', 'created_at': stamp(days_ago)}}


def timeline(entries, bottom=None, pin=None):
    items = [{'entryId': f'tweet-{t["rest_id"]}', 'content': {'itemContent': {'itemType': 'TimelineTweet',
                                                                              'tweet_results': {'result': t}}}} for t in entries]
    if bottom:
        items.append({'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': bottom}})
    instructions = [{'type': 'TimelineAddEntries', 'entries': items}]
    if pin:
        instructions.insert(0, {'type': 'TimelinePinEntry', 'entry': {'entryId': f'tweet-{pin["rest_id"]}', 'content': {
            'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {'result': pin}}}}})
    return query_result({'data': {'user': {'result': {'timeline': {'timeline': {'instructions': instructions}}}}}},
                        headers=RATE)


def test_posts_find_the_account_once_then_read_its_posts_and_reposts(browser, data_dir):
    known_tab(browser, data_dir).respond('query', by_name(user()))
    browser.respond('query', timeline([tweet('11'), tweet('12')], bottom='CUR1'))
    code, out, _ = run_cli(browser, 'profile', '@author_a')
    assert code == 0, out
    assert out.splitlines()[0].startswith('profile · tab=posts · 2 shown · stopped=limit_reached · requests=2/25')
    calls = [c['args'] for c in browser.calls() if c['op'] == 'query']
    assert [c['name'] for c in calls] == ['UserByScreenName', 'UserTweets']
    assert calls[0]['variables']['screen_name'] == 'author_a' and calls[1]['variables']['userId'] == '1000000001'
    more = command_of(out.splitlines()[-1])
    browser.respond('state', state()).respond('query', timeline([tweet('13')]))
    code, out, _ = run_cli(browser, *more)
    assert code == 0 and 'post 13' in out
    assert [c['args']['name'] for c in browser.calls() if c['op'] == 'query'][-1] == 'UserTweets'  # no second lookup


def test_a_since_window_closes_on_the_newest_first_posts_tab_and_a_pin_does_not_close_it(browser, data_dir):
    since = (date.today() - timedelta(days=3)).isoformat()
    known_tab(browser, data_dir).respond('query', by_name(user()))
    browser.respond('query', timeline([tweet('21', 0), tweet('22', 1)], bottom='CUR1', pin=tweet('20', 900)))
    browser.respond('query', timeline([tweet('23', 5), tweet('24', 6)], bottom='CUR2'))
    code, out, _ = run_cli(browser, 'profile', 'author_a', '--since', since)
    assert code == 0, out
    lines = out.splitlines()
    assert 'stopped=window_reached' in lines[0] and lines[1].endswith('closed (as served)')
    assert 'post 21' in out and 'post 22' in out and 'post 20' not in out and 'post 23' not in out
    assert [c['args']['name'] for c in browser.calls() if c['op'] == 'query'].count('UserTweets') == 2


def test_a_tab_url_reads_that_tab(browser, data_dir):
    known_tab(browser, data_dir).respond('query', by_name(user())).respond('query', timeline([tweet('31')]))
    code, out, _ = run_cli(browser, 'profile', 'https://x.com/author_a/with_replies')
    assert code == 0 and 'tab=replies' in out.splitlines()[0]
    assert [c['args']['name'] for c in browser.calls() if c['op'] == 'query'][-1] == 'UserRepliesTimeline'


def test_media_is_every_kind_of_media_and_not_in_date_order(browser, data_dir):
    known_tab(browser, data_dir).respond('query', by_name(user())).respond('query', timeline([tweet('41')]))
    code, out, _ = run_cli(browser, 'profile', 'author_a', '--tab', 'media', '--since', date.today().isoformat())
    assert code == 0, out
    assert [c['args']['name'] for c in browser.calls() if c['op'] == 'query'][-1] == 'UserMedia'
    assert out.splitlines()[1].endswith('closed (read to the end)')


def test_a_protected_account_not_followed_is_unavailable_not_empty(browser, data_dir):
    known_tab(browser, data_dir).respond('query', by_name(user(privacy={'protected': True})))
    browser.respond('query', timeline([]))
    code, out, _ = run_cli(browser, 'profile', 'author_a')
    assert code == 9 and 'protected' in json.loads(out)['message']


def test_a_public_account_with_an_empty_tab_is_empty(browser, data_dir):
    known_tab(browser, data_dir).respond('query', by_name(user())).respond('query', timeline([]))
    code, out, _ = run_cli(browser, 'profile', 'author_a', '--tab', 'highlights')
    assert code == 7


def test_an_unknown_handle_is_unavailable(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result({'data': {}}, headers=RATE))
    code, out, _ = run_cli(browser, 'profile', 'nobody_here')
    assert code == 9 and 'nobody_here' in json.loads(out)['message']


def test_about_reads_one_card_and_says_what_the_marks_mean(browser, data_dir):
    known_tab(browser, data_dir).respond('query', by_name(user(parody_commentary_fan_label='Commentary')))
    code, out, _ = run_cli(browser, 'about', '@author_a')
    assert code == 0, out
    assert '[a1] @author_a (Author A) · paid check · commentary account' in out
    assert 'followers=1200 following=300 posts=4500' in out and 'joined=2012-01-0' in out


def test_about_several_in_one_request_names_the_unresolved(browser, data_dir):
    batch = {'data': {'users': [{'result': user()}, {'result': {'__typename': 'UserUnavailable'}}]}}
    known_tab(browser, data_dir).respond('query', query_result(batch, headers=RATE))
    code, out, _ = run_cli(browser, 'about', 'author_a', 'gone_one', '--json')
    envelope = json.loads(out)
    assert code == 0 and envelope['unresolved'] == ['gone_one'] and envelope['results'][0]['username'] == 'author_a'
    [query] = [c['args'] for c in browser.calls() if c['op'] == 'query']
    assert query['name'] == 'UsersByScreenNames' and query['variables']['screen_names'] == ['author_a', 'gone_one']
