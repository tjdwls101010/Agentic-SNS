"""profile and about through the real CLI and a scripted Aside (fixtures: paging.json window cases, profile_access;
records_accounts.json)."""
import json
import time

from tests.sns.x.scenes import known_tab, queries, query_result, rerun, run, state

RATE = {'x-rate-limit-limit': '150', 'x-rate-limit-remaining': '149', 'x-rate-limit-reset': str(int(time.time()) + 900)}


def user(ident='1000000001', handle='author_a', **extra):
    return {'__typename': 'User', 'rest_id': ident, 'core': {'screen_name': handle, 'name': 'Author A',
                                                              'created_at': 'Mon Jan 02 03:04:05 +0000 2012'},
            'relationship_counts': {'followers': 1200, 'following': 300}, 'tweet_counts': {'tweets': 4500},
            'is_blue_verified': True, 'privacy': {'protected': False},
            'relationship_perspectives': {'following': False, 'followed_by': False}, **extra}


def by_name(node):
    return query_result({'data': {'user': {'result': node}}}, headers=RATE)


def stamp(days_ago, at=None):
    return time.strftime('%a %b %d %H:%M:%S +0000 %Y', time.gmtime(time.time() - days_ago * 86400 if at is None else at))


def utc_day(days_ago=0, at=None):
    """A day as the runs see it (TZ=UTC): the machine's own zone never decides what the window keeps."""
    return time.strftime('%Y-%m-%d', time.gmtime(time.time() - days_ago * 86400 if at is None else at))


def tweet(ident, days_ago=0, at=None):
    return {'__typename': 'Tweet', 'rest_id': ident, 'core': {'user_results': {'result': user()}},
            'legacy': {'full_text': f'post {ident}', 'created_at': stamp(days_ago, at)}}


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


def test_posts_find_the_account_once_then_read_its_posts_and_reposts(browser):
    known_tab(browser).respond('x.query', by_name(user()))
    browser.respond('x.query', timeline([tweet('11'), tweet('12')], bottom='CUR1'))
    code, out, _ = run(browser, 'profile', '@author_a')
    assert code == 0, out
    assert out.splitlines()[0].startswith('x profile · tab=posts · 2 shown · stopped=limit_reached · requests=2')
    calls = [c['args'] for c in queries(browser)]
    assert [c['name'] for c in calls] == ['UserByScreenName', 'UserTweets']
    assert calls[0]['variables']['screen_name'] == 'author_a' and calls[1]['variables']['userId'] == '1000000001'
    browser.respond('x.state', state()).respond('x.query', timeline([tweet('13')]))
    code, out, _ = rerun(browser, out.splitlines()[-1])
    assert code == 0 and 'post 13' in out
    assert [c['args']['name'] for c in queries(browser)][-1] == 'UserTweets'  # no second lookup


def test_a_since_window_closes_on_the_newest_first_posts_tab_and_a_pin_does_not_close_it(browser):
    since = utc_day(3)
    known_tab(browser).respond('x.query', by_name(user()))
    browser.respond('x.query', timeline([tweet('21', 0), tweet('22', 1)], bottom='CUR1', pin=tweet('20', 900)))
    browser.respond('x.query', timeline([tweet('23', 5), tweet('24', 6)], bottom='CUR2'))
    code, out, _ = run(browser, 'profile', 'author_a', '--since', since)
    assert code == 0, out
    lines = out.splitlines()
    assert 'stopped=window_reached' in lines[0] and lines[1].endswith('closed (as served)')
    assert 'post 21' in out and 'post 22' in out and 'post 20' not in out and 'post 23' not in out
    assert [c['args']['name'] for c in queries(browser)].count('UserTweets') == 2


def test_a_tab_url_reads_that_tab(browser):
    known_tab(browser).respond('x.query', by_name(user())).respond('x.query', timeline([tweet('31')]))
    code, out, _ = run(browser, 'profile', 'https://x.com/author_a/with_replies')
    assert code == 0 and 'tab=replies' in out.splitlines()[0]
    assert [c['args']['name'] for c in queries(browser)][-1] == 'UserRepliesTimeline'


def test_media_is_every_kind_of_media_and_not_in_date_order(browser):
    posted = time.time()
    known_tab(browser).respond('x.query', by_name(user())).respond('x.query', timeline([tweet('41', at=posted)]))
    code, out, _ = run(browser, 'profile', 'author_a', '--tab', 'media', '--since', utc_day(at=posted))
    assert code == 0, out
    assert [c['args']['name'] for c in queries(browser)][-1] == 'UserMedia'
    assert out.splitlines()[1].endswith('closed (read to the end)')


def test_a_protected_account_not_followed_is_unavailable_not_empty(browser):
    known_tab(browser).respond('x.query', by_name(user(privacy={'protected': True})))
    browser.respond('x.query', timeline([]))
    code, out, _ = run(browser, 'profile', 'author_a')
    assert code == 9 and 'protected' in json.loads(out)['message']


def test_a_public_account_with_an_empty_tab_is_empty(browser):
    known_tab(browser).respond('x.query', by_name(user())).respond('x.query', timeline([]))
    code, out, _ = run(browser, 'profile', 'author_a', '--tab', 'highlights')
    assert code == 7


def test_an_unknown_handle_is_unavailable(browser):
    known_tab(browser).respond('x.query', query_result({'data': {}}, headers=RATE))
    code, out, _ = run(browser, 'profile', 'nobody_here')
    assert code == 9 and 'nobody_here' in json.loads(out)['message']


def test_about_reads_one_card_and_says_what_the_marks_mean(browser):
    known_tab(browser).respond('x.query', by_name(user(parody_commentary_fan_label='Commentary')))
    code, out, _ = run(browser, 'about', '@author_a')
    assert code == 0, out
    assert '[a1] @author_a (Author A) · paid check · commentary account' in out
    assert 'followers=1200 following=300 posts=4500' in out and 'joined=2012-01-0' in out


def test_about_several_in_one_request_names_the_unresolved(browser):
    batch = {'data': {'users': [{'result': user()}, {'result': {'__typename': 'UserUnavailable'}}]}}
    known_tab(browser).respond('x.query', query_result(batch, headers=RATE))
    code, out, _ = run(browser, 'about', 'author_a', 'gone_one', '--json')
    envelope = json.loads(out)
    assert code == 0 and envelope['unresolved'] == ['gone_one'] and envelope['results'][0]['username'] == 'author_a'
    [query] = [c['args'] for c in queries(browser)]
    assert query['name'] == 'UsersByScreenNames' and query['variables']['screen_names'] == ['author_a', 'gone_one']


def test_accounts_x_suggests_inside_a_posts_tab_are_left_out_and_do_not_break_the_window(browser):
    """Live (P6 t7): X put a who-to-follow module of three accounts, dated by when they joined, among a profile's
    posts — the window then never closed and the suggestions showed as records of the profile."""
    since = utc_day(3)
    joined = {**user('2000000001', 'suggested_one'), 'core': {'screen_name': 'suggested_one', 'name': 'S',
                                                               'created_at': 'Fri Jan 24 23:27:11 +0000 2014'}}
    who = {'entryId': 'who-to-follow-1', 'content': {'entryType': 'TimelineTimelineModule', 'items': [
        {'entryId': 'who-to-follow-1-user-2', 'item': {'itemContent': {'itemType': 'TimelineUser', 'user_results': {'result': joined}}}}]}}
    first = timeline([tweet('51', 0), tweet('52', 1)], bottom='CUR1')
    body = json.loads(first['body'])
    body['data']['user']['result']['timeline']['timeline']['instructions'][0]['entries'].insert(1, who)
    first['body'] = json.dumps(body)
    known_tab(browser).respond('x.query', by_name(user())).respond('x.query', first)
    browser.respond('x.query', timeline([tweet('53', 5)], bottom='CUR2'))
    code, out, _ = run(browser, 'profile', 'author_a', '--since', since)
    assert code == 0, out
    assert 'suggested_one' not in out and 'stopped=window_reached' in out.splitlines()[0]
    assert 'other items X mixed in' in out


def test_a_pinned_post_is_pinned_and_a_replys_parent_is_parent_id_in_the_records(browser):
    reply = tweet('62')
    reply['legacy']['in_reply_to_status_id_str'] = '1850000000000000001'
    known_tab(browser).respond('x.query', by_name(user()))
    browser.respond('x.query', timeline([reply], pin=tweet('61')))
    code, out, _ = run(browser, 'profile', 'author_a', '--json')
    assert code == 0, out
    by_id = {r['id']: r for r in json.loads(out)['results']}
    assert by_id['61']['pinned'] is True and by_id['62']['pinned'] is False
    assert by_id['62']['parent_id'] == '1850000000000000001' and 'reply_to_id' not in by_id['62']
    assert 'is_pinned' not in by_id['61']


def test_a_posts_pictures_are_numbered_and_a_videos_poster_is_kept_beside_its_file(browser):
    clip = tweet('71')
    clip['legacy']['extended_entities'] = {'media': [
        {'type': 'photo', 'id_str': '9001', 'media_url_https': 'https://pbs.twimg.com/media/A.jpg', 'ext_alt_text': 'A chart',
         'original_info': {'width': 10, 'height': 20}},
        {'type': 'video', 'id_str': '9002', 'media_url_https': 'https://pbs.twimg.com/media/B.jpg',
         'video_info': {'variants': [{'content_type': 'video/mp4', 'bitrate': 1, 'url': 'https://video.twimg.com/B.mp4'}]}}]}
    known_tab(browser).respond('x.query', by_name(user())).respond('x.query', timeline([clip]))
    code, out, _ = run(browser, 'profile', 'author_a', '--json')
    media = json.loads(out)['results'][0]['media']
    assert [(m['n'], m['kind'], m['image_url'], m['video_url'], m['alt'], m['media_id']) for m in media] == [
        (1, 'photo', 'https://pbs.twimg.com/media/A.jpg', None, 'A chart', '9001'),
        (2, 'video', 'https://pbs.twimg.com/media/B.jpg', 'https://video.twimg.com/B.mp4', None, '9002')]
    known_tab(browser).respond('x.query', by_name(user())).respond('x.query', timeline([clip]))
    code, text, _ = run(browser, 'profile', 'author_a')
    assert 'media: photo alt="A chart" · video' in text  # the text names the kind and the alt as before
