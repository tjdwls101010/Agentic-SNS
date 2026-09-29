"""What a read returns: records, reposts and quotes, thread roles and completeness, places, trends and targets."""
import pytest

from .fake_data import entry, instructions, tweet, user, wrap
from .helpers import calls, invoke, script, text


def timeline(*raw, cursor='next'):
    """One TimelineAddEntries instruction over raw entries, with a bottom cursor unless cursor is None."""
    entries = list(raw) + ([{'entryId': 'cursor-bottom', 'content': {'cursorType': 'Bottom', 'value': cursor}}]
                           if cursor else [])
    return [{'type': 'TimelineAddEntries', 'entries': entries}]


def module(identity, *children):
    return {'entryId': identity, 'content': {'items': [
        {'entryId': child['entryId'], 'item': {'itemContent': child['content']['itemContent']}} for child in children]}}


def show_more(module_id, value):
    return {'type': 'TimelineAddToModule', 'moduleEntryId': module_id, 'moduleItems': [
        {'entryId': module_id + '-more', 'item': {'itemContent': {'itemType': 'TimelineTimelineCursor',
                                                                   'cursorType': 'ShowMoreThreads', 'value': value}}}]}


def post(identity, parent=None, text='example', replies=9, **legacy):
    node = tweet(identity, parent)
    node['legacy'].update(full_text=text, reply_count=replies, entities={}, **legacy)
    return node


def test_profile_card_maps_current_user_shape(fake_env):
    node = user()
    node.update(relationship_counts={'followers': 1200, 'following': 3}, tweet_counts={'tweets': 42},
                privacy={'protected': True})
    script(fake_env, {'op': 'UserByScreenName', 'body': wrap('UserByScreenName', node)})
    code, doc = invoke(['about', '@example'], fake_env)
    card = doc['results'][0]
    assert code == 0
    assert (card['followers_count'], card['following_count'], card['tweet_count'], card['verified_type'],
            card['is_protected']) == (1200, 3, 42, 'Government', True)


def test_repost_row_keeps_reposter_identity_and_original_content(fake_env):
    original = post('201')
    original['legacy']['favorite_count'] = 12
    original['note_tweet'] = {'note_tweet_results': {'result': {'text': 'long text'}}}
    outer = post('202', retweeted_status_result={'result': original}, quoted_status_id_str='299')
    outer['core']['user_results']['result'] = user('101', 'reposter')
    wrapped = {'__typename': 'TweetWithVisibilityResults', 'tweet': outer,
               'limitedActionResults': {'limited_actions': [{'action': 'Reply'}]}}
    raw = {'entryId': 'tweet-202', 'content': {'itemContent': {'tweet_results': {'result': wrapped}}}}
    script(fake_env, {'op': 'HomeTimeline', 'body': wrap('HomeTimeline', timeline(raw))})
    code, doc = invoke(['home', '--limit', '1'], fake_env)
    row = doc['results'][0]
    assert code == 0
    assert row['author']['screen_name'] == 'reposter' and row['id'] == '202'
    assert row['text'] == 'long text' and row['url'].endswith('/201') and row['like_count'] == 12
    assert row['quoted_tweet_id'] == '299' and 'Reply' in row['limited_actions']


def test_pinned_entry_is_marked_ads_removed_and_bottom_cursor_continues(fake_env):
    pinned = {'type': 'TimelinePinEntry', 'entry': entry(post('200'))}
    body = [pinned, *timeline({'entryId': 'promoted-201', 'content': entry(post('201'))['content']}, entry(post('202')))]
    script(fake_env, {'op': 'UserTweets', 'body': wrap('UserTweets', body)})
    code, doc = invoke(['user', '@example', '--limit', '2'], fake_env)
    assert code == 0 and [r['id'] for r in doc['results']] == ['200', '202']
    assert doc['results'][0]['is_pinned'] and not doc['results'][1]['is_pinned']
    code, doc = invoke(['user', '@example', '--limit', '1', '--after', str(doc['next_handle'])], fake_env)
    assert [c['variables'].get('cursor') for c in calls(fake_env) if c['op'] == 'UserTweets'] == [None, 'next']


def thread(*raw, extra=(), cursor=None):
    return wrap('TweetDetail', [*timeline(*raw, cursor=cursor), *extra])


def test_thread_roles_depth_and_completeness(fake_env):
    script(fake_env, {'op': 'TweetDetail', 'body': thread(entry(post('1')), entry(post('2', '1')),
                                                          module('conversationthread-3', entry(post('3', '2')),
                                                                 entry(post('4', '3'))))})
    code, doc = invoke(['post', '2'], fake_env)
    rows = doc['results']
    assert code == 0 and [r['role'] for r in rows] == ['parent', 'focal', 'reply', 'reply']
    assert rows[-1]['depth'] == 1 and rows[-1]['module'] == 'conversationthread-3'
    assert {k: doc[k] for k in ('reported', 'direct_shown', 'nested_shown', 'hidden_branches')} == dict(
        reported=9, direct_shown=1, nested_shown=1, hidden_branches=0)


def test_related_posts_are_not_replies(fake_env):
    script(fake_env, {'op': 'TweetDetail', 'body': thread(entry(post('2')),
                                                          module('tweetdetailrelatedtweets-9', entry(post('9'))))})
    code, doc = invoke(['post', '2'], fake_env)
    assert code == 0 and [r['id'] for r in doc['results']] == ['2'] and doc['direct_shown'] == 0


def test_hidden_branches_are_counted_not_followed(fake_env):
    extra = [show_more('conversationthread-a', 'h1'), show_more('conversationthread-b', 'h2')]
    script(fake_env, {'op': 'TweetDetail', 'body': thread(entry(post('1')), entry(post('2', '1')), extra=extra)})
    code, output = text(['post', '1'], fake_env)
    assert code == 0 and 'replies: 1 direct shown of 9 reported · +0 nested · hidden branches 2' in output
    assert len(calls(fake_env)) == 1


def trend(identity, name, item_type='TimelineTrend', **fields):
    return {'entryId': identity, 'content': {'itemContent': {'itemType': item_type, 'name': name, **fields}}}


def test_trends_keep_events_count_promoted_and_other_items(fake_env):
    rows = [trend('trend-a', 'A'),
            {'entryId': 'trends', 'content': {'items': [
                {'entryId': 'event-b', 'item': {'itemContent': {'itemType': 'TimelineEventSummary', 'title': 'B'}}},
                {'entryId': 'trend-ad', 'item': {'itemContent': {'itemType': 'TimelineTrend', 'name': 'Advertisement',
                                                                 'promoted_metadata': {'advertiser': 'example'}}}}]}},
            {'entryId': 'unknown', 'content': {'itemContent': {'itemType': 'NewThing'}}}]
    script(fake_env, {'op': 'GenericTimelineById', 'body': wrap('GenericTimelineById', timeline(*rows, cursor=None))})
    code, doc = invoke(['trends'], fake_env)
    assert code == 0 and [r['kind'] for r in doc['results']] == ['trend', 'event']
    assert doc['promoted'] == 1 and doc['other_items'] == 1 and doc['next'] is None
    assert doc['stop_reason'] == 'not_paginable'


def test_community_member_roles_and_card(fake_env):
    moderator = module('communityModerators-1', entry(user('2', 'moderator'), 'user'))
    member = module('communityMembers-1', entry(user('1', 'member'), 'user'))
    card = {'rest_id': '1', 'name': 'Example', 'rules': [{'name': 'Kindness'}], 'is_nsfw': True}
    script(fake_env, {'op': 'CommunityByRestId', 'body': wrap('CommunityByRestId', card)},
           {'op': 'CommunityAboutTimeline', 'body': wrap('CommunityAboutTimeline', timeline(moderator, member, cursor=None))})
    code, doc = invoke(['community', '1', '--tab', 'about'], fake_env)
    assert code == 0 and [r['role'] for r in doc['results']] == ['moderator', 'member']
    assert doc['card']['rules'] == [{'name': 'Kindness'}] and doc['card']['url'] == 'https://x.com/i/communities/1'
    assert doc['card']['is_nsfw'] is True


def test_top_termination_does_not_end_bottom_pagination(fake_env):
    body = [{'type': 'TimelineTerminateTimeline', 'direction': 'Top'},
            *instructions([tweet(str(200 + i)) for i in range(5)])]
    script(fake_env, {'op': 'HomeTimeline', 'body': wrap('HomeTimeline', body)})
    code, doc = invoke(['home', '--limit', '10'], fake_env)
    assert code == 0 and doc['stop_reason'] == 'exhausted'
    assert [c['op'] for c in calls(fake_env)] == ['HomeTimeline', 'HomeTimeline']


def test_community_landing_url_is_a_string_next_hop(fake_env):
    raw = {'entryId': 'tweet-1', 'content': {'itemContent': {
        'tweet_results': {'result': {'rest_id': '1', 'legacy': {'full_text': 'Synthetic'}}},
        'socialContext': {'landingUrl': {'url': 'https://twitter.com/i/communities/123', 'urlType': 'ExternalUrl'}}}}}
    script(fake_env, {'op': 'CommunitiesExploreTimeline', 'body': wrap('CommunitiesExploreTimeline', timeline(raw))})
    code, doc = invoke(['communities', '--limit', '1'], fake_env)
    assert code == 0 and doc['results'][0]['community_url'] == 'https://twitter.com/i/communities/123'


@pytest.mark.parametrize('value', ['@example', 'example', 'https://x.com/example?s=20', 'mobile.twitter.com/example/',
                                   'https://www.x.com/example/'])
def test_profile_target_forms(value, fake_env):
    code, _ = invoke(['about', value], fake_env)
    assert code == 0 and calls(fake_env)[0]['variables']['screen_name'] == 'example'


@pytest.mark.parametrize('value', ['123', 'https://x.com/example/status/123/photo/1', '/i/web/status/123',
                                   'm.twitter.com/example/status/123/analytics#x',
                                   'https://www.twitter.com/example/status/123/video/1'])
def test_post_target_forms(value, fake_env):
    code, _ = invoke(['post', value], fake_env)
    assert code == 0 and calls(fake_env)[0]['variables']['focalTweetId'] == '123'


@pytest.mark.parametrize('command,value,op,key', [
    ('list', '123', 'ListByRestId', 'listId'),
    ('list', 'https://x.com/i/lists/123/?s=20', 'ListByRestId', 'listId'),
    ('community', '123', 'CommunityByRestId', 'communityId'),
    ('community', 'https://twitter.com/i/communities/123', 'CommunityByRestId', 'communityId'),
])
def test_place_target_forms(command, value, op, key, fake_env):
    invoke([command, value, '--tab', 'about'], fake_env)
    assert (calls(fake_env)[0]['op'], calls(fake_env)[0]['variables'][key]) == (op, '123')


@pytest.mark.parametrize('value', ['123', 'https://evil.com/example', 'https://x.com/messages', 'https://t.co/foo',
                                   'https://x.com@evil.com/example', 'https://x.com:abc/example',
                                   'https://x.com:99999/example', 'https://[x.com/example'])
def test_invalid_profile_targets_are_argument_errors_before_any_request(value, fake_env):
    code, doc = invoke(['about', value], fake_env)
    assert (code, doc['error']) == (2, 'arguments') and calls(fake_env) == []
