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


# --- communities -----------------------------------------------------------------------------------------------------

def community(ident='1600000000000000001', **extra):
    return {'__typename': 'Community', 'rest_id': ident, 'id_str': ident, 'name': 'Synthetic community',
            'description': 'For tests', 'member_count': 1200, 'moderator_count': 3, 'created_at': 1767225600000,
            'join_policy': 'Open', 'is_nsfw': False, 'role': 'NonMember',
            'primary_community_topic': {'topic_id': '1', 'topic_name': 'Technology'},
            'rules': [{'rest_id': '1', 'name': 'Be kind'}], 'creator_results': {'result': OWNER}, **extra}


def test_community_posts_by_ranking_or_recency(browser, data_dir):
    timeline = {'data': {'communityResults': {'result': {'ranked_community_timeline': {'timeline': {'instructions': entries([
        {'entryId': 'tweet-21', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {'result': post('21')}}}}],
        'C1')}}}}}}
    for sort, mode in (('top', 'Relevance'), ('recent', 'Recency')):
        known_tab(browser, data_dir).respond('query', query_result(timeline, headers=RATE))
        code, out, _ = run_cli(browser, 'community', 'https://x.com/i/communities/1600000000000000001', '--sort', sort)
        assert code == 0 and 'post 21' in out, out
        call = queries(browser)[-1]
        assert call['name'] == 'CommunityTweetsTimeline' and call['variables']['communityId'] == '1600000000000000001'
        assert call['variables']['rankingMode'] == mode


def test_community_media_and_card(browser, data_dir):
    media = {'data': {'communityResults': {'result': {'community_media_timeline': {'timeline': {'instructions': entries([
        {'entryId': 'tweet-22', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {'result': post('22')}}}}])}}}}}}
    known_tab(browser, data_dir).respond('query', query_result(media, headers=RATE))
    code, out, _ = run_cli(browser, 'community', '1600000000000000001', '--tab', 'media')
    assert code == 0 and 'post 22' in out and queries(browser)[-1]['name'] == 'CommunityMediaTimeline'
    card = {'data': {'communityResults': {'result': community()}}}
    known_tab(browser, data_dir).respond('query', query_result(card, headers=RATE))
    code, out, _ = run_cli(browser, 'community', '1600000000000000001', '--tab', 'about')
    assert code == 0, out
    assert '[c1] "Synthetic community" · members=1200 moderators=3 · open to join · technology · you are not a member' in out
    assert 'rules: "Be kind"' in out and 'created by @author_a' in out


def test_a_community_that_does_not_exist_is_unavailable(browser, data_dir):
    # measured 2026-10-19: X answers 200 with a result that is only a __typename other than Community
    stub = {'data': {'communityResults': {'result': {'__typename': 'CommunityUnavailable'}}}}
    known_tab(browser, data_dir).respond('query', query_result(stub, headers=RATE))
    code, out, _ = run_cli(browser, 'community', '1600000000000000001', '--tab', 'about')
    assert code == 9


def test_without_a_target_community_lists_the_communities_x_suggests(browser, data_dir):
    discovery = {'data': {'viewer': {'community_discovery_timeline': {'timeline': {'instructions': entries([
        {'entryId': 'community-1600000000000000001', 'content': {'itemContent': {'itemType': 'TimelineCommunity',
                                                                                 'community_results': {'result': community()}}}}])}}}}}
    known_tab(browser, data_dir).respond('query', query_result(discovery, headers=RATE))
    code, out, _ = run_cli(browser, 'community')
    assert code == 0 and '[c1] "Synthetic community"' in out and 'suggest' in out, out
    call = queries(browser)[-1]
    assert call['name'] == 'CommunityDiscoveryTimeline' and call['chunk_hint'] == 'bundle.Communities'


def test_search_in_communities_reads_community_posts(browser, data_dir):
    page = {'data': {'search_by_raw_query': {'communities_latest_posts_search_page': {'timeline': {'instructions': entries([
        {'entryId': 'tweet-23', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {'result': post('23')}}}}])}}}}}
    known_tab(browser, data_dir).respond('query', query_result(page, headers=RATE))
    code, out, _ = run_cli(browser, 'search', 'rust', '--in', 'communities')
    assert code == 0 and 'post 23' in out, out
    call = queries(browser)[-1]
    assert call['name'] == 'GlobalCommunitiesLatestPostSearchTimeline' and call['variables']['rawQuery'] == 'rust'


def test_search_in_communities_reads_posts_only(browser, data_dir):
    code, out, _ = run_cli(browser, 'search', 'rust', '--in', 'communities', '--type', 'accounts')
    assert code == 2 and 'posts only' in json.loads(out)['message'] and browser.calls() == []


def test_suggested_communities_and_community_search_continue_from_their_more_line(browser, data_dir):
    from conftest import command_of, state
    discovery = {'data': {'viewer': {'community_discovery_timeline': {'timeline': {'instructions': entries([
        {'entryId': 'community-1600000000000000001', 'content': {'itemContent': {'itemType': 'TimelineCommunity',
                                                                                 'community_results': {'result': community()}}}}],
        'DISC2')}}}}}
    search = {'data': {'search_by_raw_query': {'communities_latest_posts_search_page': {'timeline': {'instructions': entries([
        {'entryId': 'tweet-24', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {'result': post('24')}}}}],
        'SRCH2')}}}}}
    for args, body, cursor in ((['community'], discovery, 'DISC2'), (['search', 'rust', '--in', 'communities'], search, 'SRCH2')):
        known_tab(browser, data_dir).respond('query', query_result(body, headers=RATE))
        code, out, _ = run_cli(browser, *args)
        assert code == 0 and out.splitlines()[-1].startswith('more: '), out
        browser.respond('state', state()).respond('query', query_result(body, headers=RATE))
        code, out, _ = run_cli(browser, *command_of(out.splitlines()[-1]))
        assert code == 0, out
        assert queries(browser)[-1]['variables']['cursor'] == cursor and queries(browser)[-1]['name'] == queries(browser)[-2]['name']


# --- trends ----------------------------------------------------------------------------------------------------------

def trend(name, rank, query, promoted=False):
    content = {'itemType': 'TimelineTrend', 'name': name, 'rank': str(rank),
               'trend_metadata': {'domain_context': 'Music · Trending'},
               'trend_url': {'url': f'twitter://search/?query={query}&src=trend_click'}}
    if promoted:
        content['promoted_metadata'] = {'advertiser_results': {}}
    return {'entryId': f'trend-{rank}', 'content': {'itemContent': content}}


def explore(initial_entries):
    return query_result({'data': {'explore_page': {'body': {'__typename': 'SegmentedTimelines', 'initialTimeline': {
        'id': 'for_you', 'timeline': {'timeline': {'instructions': entries(initial_entries)}}}, 'timelines': [
        {'id': 'for_you', 'timeline': {'id': 'VEZPUllPVQ=='}}, {'id': 'trending', 'timeline': {'id': 'VFJFTkRJTkc='}}]}}}},
        headers=RATE)


def test_trends_reads_the_trending_tab_by_its_timeline_and_leaves_ads_out(browser, data_dir):
    trending = query_result({'data': {'timeline': {'timeline': {'instructions': entries(
        [trend('#Synthetic', 1, '%23Synthetic'), trend('Ad', 2, 'ad', promoted=True), trend('Plain words', 3, '%22Plain+words%22')])}}}},
        headers=RATE)
    known_tab(browser, data_dir).respond('query', explore([])).respond('query', trending)
    code, out, _ = run_cli(browser, 'trends')
    assert code == 0, out
    assert out.splitlines()[0].startswith('trends · tab=trending · 2 shown') and 'requests=2/25' in out.splitlines()[0]
    assert '[t1] "#Synthetic" · trend · #1 · Music · Trending' in out and 'search: "#Synthetic"' in out
    assert 'search: "\\"Plain words\\""' in out and '"Ad"' not in out and 'promoted' in out
    calls = queries(browser)
    assert [c['name'] for c in calls] == ['ExplorePage', 'GenericTimelineById']
    assert calls[1]['variables']['timelineId'] == 'VFJFTkRJTkc='


def test_the_for_you_tab_is_already_in_the_explore_answer(browser, data_dir):
    user = {'entryId': 'who-1', 'content': {'entryType': 'TimelineTimelineModule', 'items': [
        {'entryId': 'who-1-user-1', 'item': {'itemContent': {'itemType': 'TimelineUser', 'user_results': {'result': OWNER}}}}]}}
    known_tab(browser, data_dir).respond('query', explore([trend('#Synthetic', 1, '%23Synthetic'), user]))
    code, out, _ = run_cli(browser, 'trends', '--tab', 'foryou')
    assert code == 0 and '[t1] "#Synthetic"' in out and '@author_a' not in out, out
    assert 'other items' in out and [c['name'] for c in queries(browser)] == ['ExplorePage']


def test_a_tab_explore_does_not_name_is_a_shape_change(browser, data_dir):
    known_tab(browser, data_dir).respond('query', explore([]))
    code, out, _ = run_cli(browser, 'trends', '--tab', 'sports')
    assert code == 6 and 'sports' in json.loads(out)['message']


# --- spaces ----------------------------------------------------------------------------------------------------------

def space(state='Running', **metadata):
    return {'data': {'audioSpace': {'is_subscribed': False, 'metadata': {
        'rest_id': '1AbCdEfGhIjKl', 'title': 'Synthetic space', 'state': state, 'created_at': 1767225600000,
        'started_at': 1767225660000, 'total_live_listeners': 12, 'total_replay_watched': 0,
        'is_space_available_for_replay': True, 'creator_results': {'result': OWNER}, **metadata},
        'participants': {'total': 15, 'admins': [{'twitter_screen_name': 'author_a', 'display_name': 'A'}],
                         'speakers': [{'twitter_screen_name': 'speaker_b', 'display_name': 'B'}], 'listeners': []}}}}


def test_about_a_space_reads_its_card(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(space(), headers=RATE))
    code, out, _ = run_cli(browser, 'about', 'https://x.com/i/spaces/1AbCdEfGhIjKl')
    assert code == 0, out
    assert '[s1] "Synthetic space" · live · hosted by @author_a · listeners=12 · participants=15' in out
    assert 'speakers: @speaker_b' in out and 'replay available' in out
    call = queries(browser)[-1]
    assert call['name'] == 'AudioSpaceById' and call['variables']['id'] == '1AbCdEfGhIjKl'
    assert call['chunk_hint'] == 'bundle.AudioSpacePeek'


def test_a_space_that_does_not_exist_is_unavailable(browser, data_dir):
    # measured 2026-10-19: X answers 200 with an audioSpace that has no metadata
    known_tab(browser, data_dir).respond('query', query_result({'data': {'audioSpace': {'is_subscribed': False}}}, headers=RATE))
    code, out, _ = run_cli(browser, 'about', 'https://x.com/i/spaces/1AbCdEfGhIjKl')
    assert code == 9


def test_a_space_is_read_on_its_own(browser, data_dir):
    code, out, _ = run_cli(browser, 'about', 'author_a', 'https://x.com/i/spaces/1AbCdEfGhIjKl')
    assert code == 2 and 'on its own' in json.loads(out)['message'] and browser.calls() == []


# --- notifications ---------------------------------------------------------------------------------------------------

def notification(ident, icon='recommendation_icon', text='New post from Author A', stamp='1767225600000'):
    return {'entryId': f'notification-{ident}', 'content': {'itemContent': {
        'itemType': 'TimelineNotification', 'id': ident, 'notification_icon': icon,
        'rich_message': {'text': text, 'entities': []}, 'timestamp_ms': stamp,
        'notification_url': {'url': 'https://x.com/author_a/status/31', 'urlType': 'ExternalUrl'},
        'template': {'__typename': 'TimelineNotificationAggregateUserActions',
                     'from_users': [{'user_results': {'result': OWNER}}],
                     'target_objects': [{'tweet_results': {'result': post('31')}}]}}}}


def notifications(items, bottom=None):
    return query_result({'data': {'viewer_v2': {'user_results': {'result': {'notification_timeline': {'timeline': {
        'instructions': entries(items, bottom)}}}}}}}, headers=RATE)


def test_my_notifications_say_what_happened_and_which_are_xs_suggestions(browser, data_dir):
    known_tab(browser, data_dir).respond('query', notifications([notification('N1'), notification('N2', 'heart_icon', 'Author A liked your post')]))
    code, out, _ = run_cli(browser, 'me', 'notifications')
    assert code == 0, out
    assert '[n1] suggested by X · 2026-01-01' in out and '"New post from Author A"' in out
    assert '[n2] like · 2026-01-01' in out and 'accounts: @author_a' in out and 'posts: 31' in out
    call = queries(browser)[-1]
    assert call['name'] == 'NotificationsTimeline' and call['variables']['timeline_type'] == 'All'
    assert call['chunk_hint'] == 'bundle.Notifications'
    assert not [c for c in browser.calls() if c['op'] == 'load:arm' and 'notifications' in (c.get('url') or '')]


def test_my_mentions_are_posts(browser, data_dir):
    mention = {'entryId': 'tweet-41', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {'result': post('41')}}}}
    known_tab(browser, data_dir).respond('query', notifications([mention]))
    code, out, _ = run_cli(browser, 'me', 'mentions')
    assert code == 0 and 'post 41' in out, out
    assert queries(browser)[-1]['variables']['timeline_type'] == 'Mentions'


def test_an_empty_timeline_object_is_empty_not_a_shape_change(browser, data_dir):
    # measured 2026-10-19: ListMemberships for an account in no lists answers {"timeline": {}} under the user
    empty = query_result({'data': {'user': {'result': {'__typename': 'User', 'timeline': {}}}}}, headers=RATE)
    known_tab(browser, data_dir).respond('query', by_name()).respond('query', empty)
    code, out, _ = run_cli(browser, 'profile', 'author_a', '--tab', 'memberships')
    assert code == 7 and json.loads(out)['error'] == 'empty'


# --- P4 review: an answer the skill misreads is a shape change, never "empty" or "does not exist" -------------------

def test_a_page_of_entries_none_of_which_can_be_read_is_a_shape_change(browser, data_dir):
    broken = [{'entryId': f'user-{i}', 'content': {'itemContent': {'itemType': 'TimelineUser', 'user_results': {
        'result': {'__typename': 'User', 'renamed_id': str(i)}}}}} for i in range(3)]
    page = query_result({'data': {'user': {'result': {'timeline': {'timeline': {'instructions': entries(broken)}}}}}}, headers=RATE)
    known_tab(browser, data_dir).respond('query', by_name()).respond('query', page)
    code, out, _ = run_cli(browser, 'graph', 'author_a', 'followers')
    assert code == 6, out


def test_an_account_with_a_name_but_no_id_is_still_shown(browser, data_dir):
    named = [{'entryId': 'user-x', 'content': {'itemContent': {'itemType': 'TimelineUser', 'user_results': {
        'result': {'__typename': 'User', 'core': {'screen_name': 'named_one'}}}}}}]
    page = query_result({'data': {'user': {'result': {'timeline': {'timeline': {'instructions': entries(named)}}}}}}, headers=RATE)
    known_tab(browser, data_dir).respond('query', by_name()).respond('query', page)
    code, out, _ = run_cli(browser, 'graph', 'author_a', 'followers')
    assert code == 0 and '@named_one' in out, out


def test_an_empty_timeline_object_with_errors_or_on_other_reads_is_not_empty(browser, data_dir):
    with_errors = query_result({'data': {'user': {'result': {'__typename': 'User', 'timeline': {}}}},
                                'errors': [{'code': 22, 'message': 'Authorization'}]}, headers=RATE)
    known_tab(browser, data_dir).respond('query', by_name()).respond('query', with_errors)
    code, out, _ = run_cli(browser, 'profile', 'author_a', '--tab', 'memberships')
    assert code == 6, out
    followers = query_result({'data': {'user': {'result': {'__typename': 'User', 'timeline': {}}}}}, headers=RATE)
    known_tab(browser, data_dir).respond('query', by_name()).respond('query', followers)
    code, out, _ = run_cli(browser, 'graph', 'author_a', 'followers')
    assert code == 6, out


def test_a_card_whose_fields_moved_is_a_shape_change_not_a_missing_target(browser, data_dir):
    moved = [('list', '1500000000000000001', {'data': {'list': {**{k: v for k, v in x_list().items() if k != 'name'}, 'title': 'L'}}}),
             ('community', '1600000000000000001', {'data': {'communityResults': {'result': {**community(), '__typename': 'CommunityV2'}}}}),
             ('about', 'https://x.com/i/spaces/1AbCdEfGhIjKl', {'data': {'audioSpace': {'is_subscribed': False, 'meta': {}}}})]
    for command, target, body in moved:
        known_tab(browser, data_dir).respond('query', query_result(body, headers=RATE))
        args = [command, target] + (['--tab', 'about'] if command != 'about' else [])
        code, out, _ = run_cli(browser, *args)
        assert code == 6, (command, out)


def test_explore_without_its_first_page_is_a_shape_change(browser, data_dir):
    body = {'data': {'explore_page': {'body': {'initialTimeline': {'id': 'for_you', 'timeline': {}},
                                                'timelines': [{'id': 'for_you', 'timeline': {'id': 'X'}}]}}}}
    known_tab(browser, data_dir).respond('query', query_result(body, headers=RATE))
    code, out, _ = run_cli(browser, 'trends', '--tab', 'foryou')
    assert code == 6, out


def test_notification_times_come_as_iso_text(browser, data_dir):
    # measured: every captured notification sends timestamp_ms as "YYYY-MM-DDTHH:MM:SS.mmmZ"
    item = notification('N9', stamp='2026-10-18T03:04:05.678Z')
    known_tab(browser, data_dir).respond('query', notifications([item]))
    code, out, _ = run_cli(browser, 'me', 'notifications', '--json')
    assert code == 0 and json.loads(out)['results'][0]['created_at'].startswith('2026-10-18T03:04:05')


def test_an_event_ends_with_the_search_that_reads_it(browser, data_dir):
    event = {'entryId': 'stories-1', 'content': {'itemContent': {'itemType': 'TimelineEventSummary', 'title': 'A synthetic event',
             'event': {'rest_id': '17'}, 'eventSummaryUrl': {'url': 'twitter://trending/?id=17', 'urlType': 'DeepLink'}}}}
    known_tab(browser, data_dir).respond('query', explore([event]))
    code, out, _ = run_cli(browser, 'trends', '--tab', 'foryou')
    assert code == 0 and 'search: "A synthetic event"' in out, out


def test_suggested_communities_take_no_tab_or_sort(browser, data_dir):
    for extra in (['--tab', 'media'], ['--sort', 'recent']):
        code, out, _ = run_cli(browser, 'community', *extra)
        assert code == 2 and browser.calls() == [], out


def test_a_single_card_or_the_trends_are_not_collected_into_a_file(browser, data_dir, tmp_path):
    for args in (['list', '1500000000000000001', '--tab', 'about'], ['community', '1600000000000000001', '--tab', 'about'],
                 ['trends']):
        code, out, _ = run_cli(browser, *args, '--out', str(tmp_path / 'x.ndjson'))
        assert code == 2 and browser.calls() == [], (args, out)


# --- P4 re-review -------------------------------------------------------------------------------------------------

def test_the_for_you_tab_with_only_unreadable_trends_is_a_shape_change(browser, data_dir):
    broken = {'entryId': 'trend-1', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {'result': {'__typename': 'Tweet'}}}}}
    known_tab(browser, data_dir).respond('query', explore([broken]))
    code, out, _ = run_cli(browser, 'trends', '--tab', 'foryou')
    assert code == 6, out


def test_an_empty_or_unavailable_post_result_is_an_unavailable_post_not_a_shape_change(browser, data_dir):
    items = [{'entryId': 'tweet-61', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {}}}},
             {'entryId': 'tweet-62', 'content': {'itemContent': {'itemType': 'TimelineTweet',
                                                                 'tweet_results': {'result': {'__typename': 'TweetUnavailable'}}}}}]
    page = query_result({'data': {'user': {'result': {'timeline': {'timeline': {'instructions': entries(items)}}}}}}, headers=RATE)
    known_tab(browser, data_dir).respond('query', page)
    code, out, _ = run_cli(browser, 'me', 'likes', '--json')
    assert code == 0, out
    assert [(r['id'], r['unavailable']) for r in json.loads(out)['results']] == [('61', True), ('62', True)]


def test_a_card_stub_is_only_the_measured_one(browser, data_dir):
    for target, body in (('1500000000000000001', {'data': {'list': {}}}), ('1500000000000000001', {'data': {'list': {'id_str': '1'}}})):
        known_tab(browser, data_dir).respond('query', query_result(body, headers=RATE))
        code, out, _ = run_cli(browser, 'list', target, '--tab', 'about')
        assert code == 6, out
    known_tab(browser, data_dir).respond('query', query_result({'data': {'audioSpace': {}}}, headers=RATE))
    code, out, _ = run_cli(browser, 'about', 'https://x.com/i/spaces/1AbCdEfGhIjKl')
    assert code == 6, out


# --- final review -------------------------------------------------------------------------------------------------

def test_only_the_measured_empty_tweet_results_is_a_deleted_post(browser, data_dir):
    moved = [{'entryId': f'tweet-7{i}', 'content': {'itemContent': {'itemType': 'TimelineTweet',
                                                                     'tweet_results': {'tweet': {'rest_id': f'7{i}'}}}}} for i in range(2)]
    page = query_result({'data': {'user': {'result': {'timeline': {'timeline': {'instructions': entries(moved)}}}}}}, headers=RATE)
    known_tab(browser, data_dir).respond('query', page)
    code, out, _ = run_cli(browser, 'me', 'likes')
    assert code == 6, out


def test_unreadable_entries_of_a_kind_the_surface_does_not_hold_are_mixed_in_not_a_shape_change(browser, data_dir):
    who = {'entryId': 'who-to-follow-1', 'content': {'entryType': 'TimelineTimelineModule', 'items': [
        {'entryId': 'who-to-follow-1-user-x', 'item': {'itemContent': {'itemType': 'TimelineUser', 'user_results': {
            'result': {'__typename': 'User'}}}}}]}}
    page = query_result({'data': {'user': {'result': {'timeline': {'timeline': {'instructions': entries([who])}}}}}}, headers=RATE)
    known_tab(browser, data_dir).respond('query', by_name()).respond('query', page)
    code, out, _ = run_cli(browser, 'profile', 'author_a')
    assert code == 7, out


def test_mentions_keep_notification_entries(browser, data_dir):
    known_tab(browser, data_dir).respond('query', notifications([notification('N5', 'reply_icon', 'Author A replied')]))
    code, out, _ = run_cli(browser, 'me', 'mentions')
    assert code == 0 and '[n1] reply' in out, out


def test_an_unavailable_quote_keeps_its_id_and_a_repost_of_a_gone_post_keeps_its_own_link(browser, data_dir):
    quoting = {**post('81'), 'quoted_status_result': {'result': {'__typename': 'TweetUnavailable', 'reason': 'Protected'}}}
    quoting['legacy'] = {**quoting['legacy'], 'quoted_status_id_str': '555'}
    reposting = {**post('82'), 'legacy': {**post('82')['legacy'], 'retweeted_status_result': {'result': {'__typename': 'TweetUnavailable'}}}}
    items = [{'entryId': f'tweet-{n["rest_id"]}', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {'result': n}}}}
             for n in (quoting, reposting)]
    page = query_result({'data': {'user': {'result': {'timeline': {'timeline': {'instructions': entries(items)}}}}}}, headers=RATE)
    known_tab(browser, data_dir).respond('query', page)
    code, out, _ = run_cli(browser, 'me', 'likes')
    assert code == 0, out
    assert 'post 555' in out and 'Protected' in out
    assert 'url: "https://x.com/author_a/status/82"' in out


def test_a_post_entry_whose_result_key_was_renamed_is_unreadable_not_mixed_in(browser, data_dir):
    renamed = [{'entryId': 'tweet-91', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweetResult': {'result': post('91')}}}}]
    page = query_result({'data': {'user': {'result': {'timeline': {'timeline': {'instructions': entries(renamed)}}}}}}, headers=RATE)
    known_tab(browser, data_dir).respond('query', page)
    code, out, _ = run_cli(browser, 'me', 'likes')
    assert code == 6, out
