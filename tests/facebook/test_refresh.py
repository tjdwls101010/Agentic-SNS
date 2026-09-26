"""refresh: mine and capture query candidates, save only those a replay verifies, and never loosen protection."""
import json

import pytest

from tests.facebook.helpers import LIMITED, Account, envelope, feed_page, login

POST = 'https://www.facebook.com/example/posts/123'
BUNDLE = 'https://static.xx.fbcdn.net/rsrc.php/v4/test.js'
ROUTES = ['https://www.facebook.com/', 'https://www.facebook.com/zuck', 'https://www.facebook.com/zuck/about',
          'https://www.facebook.com/search/top/?q=facebook', 'https://www.facebook.com/groups/1084901568224581/']
NAMES = {'newsfeed': 'CometNewsFeedPaginationQuery', 'timeline': 'ProfileCometTimelineFeedRefetchQuery',
         'about': 'ProfileCometAboutAppSectionQuery', 'search': 'SearchCometResultsPaginatedResultsQuery',
         'group': 'GroupsCometFeedRegularStoriesPaginationQuery', 'post': 'CometSinglePostDialogContentQuery',
         'comments': 'CommentListComponentsRootQuery', 'comments_page': 'CommentsListComponentsPaginationQuery',
         'replies': 'Depth1CommentsListPaginationQuery'}
MINED = ['newsfeed', 'timeline', 'about', 'search', 'group', 'post']
MINED_IDS = {key: str(100 + index) for index, key in enumerate(MINED)}
REPLAY_ORDER = ['newsfeed', 'about', 'group', 'search', 'timeline']  # post goes last, after its sample lookup
FLAG = '__relay_internal__pv__{}relayprovider'
SETUP = 7  # home + five route pages + one bundle


def mined(url, *, queries=(), scripts=(), flags=None, body='<html>synthetic route</html>', status=200):
    return {'status': status, 'url': url, 'body': body, 'queries': list(queries), 'scripts': list(scripts),
            'relay_provider_flags': flags or {}}


def mining(flags=None, bundle_status=200):
    return [mined(ROUTES[0], scripts=[BUNDLE], flags=flags),
            mined(BUNDLE, queries=[{'name': NAMES[k], 'doc_id': MINED_IDS[k]} for k in MINED],
                  body='__d("synthetic")', status=bundle_status),
            *[mined(route) for route in ROUTES[1:]]]


def replay(key):
    sample = {'__typename': 'Story', 'id': 'synthetic', 'feedback': {'id': 'feedback'}, 'permalink_url': POST}
    body = {'newsfeed': {'news_feed': {'edges': [{'node': sample}]}},
            'timeline': {'timeline_list_feed_units': {'edges': [{'node': sample}]}},
            'group': {'group_feed': {'edges': [{'node': sample}]}},
            'search': {'results': {'edges': [{'node': sample}]}},
            'about': {'about_app_sections': {'nodes': [{'id': 'synthetic'}]}},
            'post': {'node': {'__typename': 'Story', 'id': 'synthetic'}},
            'comments': {'comments': {'edges': [{'node': {'id': 'synthetic'}}]}},
            'comments_page': {'comments': {'edges': [{'node': {'id': 'synthetic'}}]}},
            'replies': {'replies_connection': {'edges': [{'node': {'id': 'synthetic'}}]}}}[key]
    return envelope({'data': body})


def story_page():
    return envelope('<html>"storyID":"PUBLIC_STORY"</html>', url=POST)


def replays(keys=REPLAY_ORDER):
    return [replay(k) for k in keys] + [story_page(), replay('post')]


def captured(queries=(), *, envelopes=(), failed=None, count=4, complete=True, url=POST):
    return envelope({'queries': list(queries), 'envelopes': list(envelopes), 'failed': failed,
                     'request_count': count, 'count_complete': complete}, url=url)


def comment_candidates(flags=None):
    variables = {'feedbackID': 'PRIVATE', 'cursor': 'PRIVATE_CURSOR', 'fb_dtsg': 'SECRET', **(flags or {})}
    return [{'name': NAMES[key], 'doc_id': str(800 + i), 'variables': dict(variables)}
            for i, key in enumerate(['comments', 'comments_page', 'replies'])]


def replay_calls(result):
    return {next(k for k, n in NAMES.items() if n == call['args']['name']): call['args']
            for call in result.calls if call['name'] == 'graphql'}


def saved(account):
    path = account.home / 'registry.json'
    return json.loads(path.read_text()) if path.exists() else None


def test_refresh_verifies_six_mined_candidates_and_preserves_other_overrides(tmp_path):
    account = Account(tmp_path)
    account.home.mkdir(parents=True)
    previous = {'queries': {'comments': {'doc_id': '777'}, 'newsfeed': {'variables': {'count': 9}}},
                'relay_provider_flags': {FLAG.format('Existing'): True}}
    (account.home / 'registry.json').write_text(json.dumps(previous))
    result = account.run('refresh', responses=[login(), *mining(), *replays()])
    assert result.code == 0, result.stdout
    data = result.data
    assert set(data['updated']) == set(MINED)
    assert set(data['missing']) == {'comments', 'comments_page', 'replies'} and data['failed'] == {}
    assert result.snippets == ['tokens', *['mine'] * 6, *['graphql'] * 5, 'page', 'graphql']
    assert [call['args']['url'] for call in result.calls if call['name'] == 'mine'] == [
        ROUTES[0], BUNDLE, *ROUTES[1:]]
    calls = replay_calls(result)
    assert {key: call['doc_id'] for key, call in calls.items()} == MINED_IDS
    assert calls['timeline']['variables']['id'] == '4'
    assert calls['group']['variables']['id'] == '1084901568224581'
    assert calls['about']['variables']['sectionToken'] == 'YXBwX3NlY3Rpb246NDoyMzI3MTU4MjI3'
    assert calls['search']['variables']['args']['text'] == 'facebook'
    assert calls['search']['variables']['args']['callsite'] == 'COMET_GLOBAL_SEARCH'
    assert calls['post']['variables']['storyID'] == 'PUBLIC_STORY'
    registry = saved(account)
    assert registry['queries']['comments'] == {'doc_id': '777'}
    assert registry['queries']['newsfeed'] == {'variables': {'count': 9}, 'name': NAMES['newsfeed'], 'doc_id': '100'}
    assert registry['relay_provider_flags'] == previous['relay_provider_flags']
    assert 'synthetic' not in json.dumps(registry)
    feed = account.run('feed', '--limit', '1', responses=[login(), feed_page(['p1'])])
    assert feed.code == 0 and feed.graphql()['doc_id'] == '100' and feed.graphql()['variables']['count'] == 9


def test_verified_home_feed_supplies_the_post_sample_without_saving_its_handle(tmp_path):
    account = Account(tmp_path)
    result = account.run('refresh', responses=[login(), *mining(), *replays()])
    assert 'post' in result.data['updated']
    calls = replay_calls(result)
    assert calls['post']['variables']['storyID'] == 'PUBLIC_STORY' and calls['post']['referer'] == POST
    assert [c['args']['url'] for c in result.calls if c['name'] == 'page'] == [POST]
    text = (account.home / 'registry.json').read_text()
    assert 'PUBLIC_STORY' not in text and 'example/posts' not in text


def test_refresh_does_not_report_success_when_no_queries_were_found(tmp_path):
    result = Account(tmp_path).run('refresh', responses=[login(), *[mined(route) for route in ROUTES]])
    assert result.code == 8
    assert result.data['ok'] is False and result.data['updated'] == []
    assert result.data['stop_reason'] == 'query_failure'
    assert result.data['fix'] == ('Read missing/failed; only verified updates were saved. '
                                  'Use --capture POST_URL for comment queries.')


@pytest.mark.parametrize('body', ['', '{"data":null}', '{"data":{"wrong":{}}}', '{"errors":[{"severity":"CRITICAL"}]}'])
def test_unverified_replay_responses_never_replace_cache(tmp_path, body):
    account = Account(tmp_path)
    result = account.run('refresh', responses=[login(), *mining(), *[envelope(body)] * 5])
    assert result.code == 8
    assert result.data['updated'] == []
    assert set(result.data['failed'].values()) == {'replay_failed', 'sample_post_missing'}
    assert result.data['failed']['post'] == 'sample_post_missing'
    assert saved(account) is None


def test_bundle_request_failure_reports_every_mined_query_without_replaying_cached_ids(tmp_path):
    account = Account(tmp_path)
    result = account.run('refresh', responses=[login(), *mining(bundle_status=500)])
    assert result.code == 8
    assert result.data['updated'] == []
    assert result.data['failed'] == {key: 'mining_request_failed' for key in MINED}
    assert set(result.data['missing']) == {'comments', 'comments_page', 'replies'}
    assert 'graphql' not in result.snippets and saved(account) is None


def test_static_bundle_auth_literals_are_source_code_not_account_challenges(tmp_path):
    account = Account(tmp_path)
    responses = mining()
    responses[1]['body'] = 'const config={"checkpoint_url":"/checkpoint/","error":1357001};'
    result = account.run('refresh', responses=[login(), *responses, *replays()])
    assert result.code == 0, result.stdout
    assert not account.blocked()


def test_atomic_replace_failure_preserves_old_cache_and_removes_temporary(tmp_path):
    account = Account(tmp_path)
    account.home.mkdir(parents=True)
    original = '{"queries":{"comments":{"doc_id":"777"}}}\n'
    (account.home / 'registry.json').write_text(original)
    result = account.run('refresh', responses=[login(), *mining(), *replays()],
                         env={'FAKE_FAIL_REPLACE': 'registry.json'})
    assert result.code == 6
    assert result.data['message'] == 'Could not save registry overrides; the previous file was preserved.'
    assert (account.home / 'registry.json').read_text() == original
    assert not [p for p in account.home.iterdir() if p.name.startswith('.registry-')]


@pytest.mark.parametrize('response,code', [(envelope({'caa_login_form_data': {}}), 4), (LIMITED, 5),
                                           (envelope({'challenge_url': '/checkpoint/'}), 5)])
def test_login_or_block_during_replay_stops_further_requests_and_cache_write(tmp_path, response, code):
    account = Account(tmp_path)
    result = account.run('refresh', responses=[login(), *mining(), response, *replays()[1:]])
    assert result.code == code
    assert result.snippets.count('graphql') == 1
    assert saved(account) is None
    assert account.blocked() == (code == 5)


@pytest.mark.parametrize('args', [['--capture'], ['--post', POST], ['--capture', 'https://evil.example/posts/1'],
                                  ['--capture', 'https://www.facebook.com:bad/posts/1'], ['--capture', 'https://www.facebook.com/zuck']])
def test_capture_arguments_are_checked_before_any_request(tmp_path, args):
    result = Account(tmp_path).run('refresh', *args)
    assert result.code == 2 and result.calls == []


def capture_run(account, feed_capture, post_capture, after=None, **kwargs):
    responses = [login(), *mining(), feed_capture, post_capture]
    if after is None:
        after = [*[replay(k) for k in ['newsfeed', 'about', 'comments', 'comments_page', 'group', 'replies', 'search',
                                       'timeline']], story_page(), replay('post')]
    return account.run('refresh', '--capture', POST, responses=responses + after, **kwargs)


def test_capture_saves_only_verified_metadata_and_replays_instance_variables(tmp_path):
    account = Account(tmp_path)
    flags = {FLAG.format('Valid'): True, FLAG.format('String'): 'AUTO_TRANSLATE',
             FLAG.format('Invalid'): {'token': 'SECRET'}}
    candidates = comment_candidates(flags)
    for candidate in candidates:
        candidate['variables'][FLAG.format('FailedOnly')] = candidate['name'] == NAMES['replies']
    after = [*[replay(k) for k in ['newsfeed', 'about', 'comments', 'comments_page', 'group']],
             envelope({'errors': [{'message': 'SECRET remote failure'}]}),
             *[replay(k) for k in ['search', 'timeline']], story_page(), replay('post')]
    result = capture_run(account, captured(candidates, url=ROUTES[0]), captured(candidates), after)
    assert result.code == 8, result.stdout
    assert set(result.data['updated']) == {*MINED, 'comments', 'comments_page'}
    assert result.data['failed'] == {'replies': 'replay_failed'}
    captures = [call['args'] for call in result.calls if call['name'] == 'capture']
    assert [(c['url'], c['actions'], c['request_budget']) for c in captures] == [
        (ROUTES[0], ['scroll_feed'] * 3, 400 - SETUP),
        (POST, ['open_comments', 'sort_comments', 'more_comments', 'expand_replies'], 400 - SETUP - 4)]
    text = (account.home / 'registry.json').read_text()
    assert all(secret not in text for secret in ('PRIVATE', 'SECRET', 'feedbackID', 'cursor', 'fb_dtsg'))
    registry = json.loads(text)
    assert registry['relay_provider_flags'] == {FLAG.format('Valid'): True, FLAG.format('String'): 'AUTO_TRANSLATE',
                                                FLAG.format('FailedOnly'): False}
    assert 'replies' not in registry['queries']
    comments = replay_calls(result)['comments']
    assert comments['doc_id'] == '800' and comments['variables']['feedbackID'] == 'PRIVATE'
    assert comments['referer'] == POST


def test_captured_common_flag_reaches_mined_candidates_in_the_same_refresh(tmp_path):
    account = Account(tmp_path)
    flag = FLAG.format('NewCommon')
    candidates = [{'name': NAMES['comments'], 'doc_id': '800', 'variables': {flag: True}}]
    after = [*[replay(k) for k in ['newsfeed', 'about', 'comments', 'group', 'search', 'timeline']], story_page(),
             replay('post')]
    result = capture_run(account, captured([], url=ROUTES[0], count=2), captured(candidates, count=2), after)
    assert replay_calls(result)['newsfeed']['variables'][flag] is True
    assert json.loads((account.home / 'registry.json').read_text())['relay_provider_flags'][flag] is True


def test_prefetched_provider_flags_verify_new_queries_without_opening_tabs(tmp_path):
    account = Account(tmp_path)
    flag = FLAG.format('PrefetchedCurrent')
    result = account.run('refresh', responses=[login(), *mining(flags={flag: False}), *replays()])
    assert result.code == 0 and len(result.data['updated']) == 6
    assert 'capture' not in result.snippets
    assert all(call['variables'][flag] is False for call in replay_calls(result).values())
    assert json.loads((account.home / 'registry.json').read_text())['relay_provider_flags'][flag] is False


@pytest.mark.parametrize('observation', [envelope({}, status=429), envelope({}, url='https://www.facebook.com/checkpoint/'),
                                         envelope({'checkpoint_url': '/checkpoint/'})])
def test_capture_observation_persists_block_before_any_replay(tmp_path, observation):
    account = Account(tmp_path)
    result = capture_run(account, captured([], envelopes=[observation], count=2, url=ROUTES[0]), captured([]))
    assert result.code == 5
    assert 'graphql' not in result.snippets and result.snippets.count('capture') == 1
    assert account.blocked() and saved(account) is None


@pytest.mark.parametrize('response', [LIMITED, envelope({}, url='https://www.facebook.com/checkpoint/')])
def test_capture_response_itself_is_guarded(tmp_path, response):
    account = Account(tmp_path)
    result = capture_run(account, response, captured([]))
    assert result.code == 5 and account.blocked()


def test_capture_that_did_not_complete_marks_its_queries_failed(tmp_path):
    account = Account(tmp_path)
    after = [*[replay(k) for k in ['newsfeed', 'about', 'group', 'search', 'timeline']], story_page(), replay('post')]
    result = capture_run(account, captured([], url=ROUTES[0], failed='capture_timeout', count=1),
                         captured([], failed='capture_timeout', count=1), after)
    assert result.code == 8
    # newsfeed keeps its mined candidate, so only the queries that capture alone could supply are failed.
    assert result.data['failed'] == {'comments': 'capture_failed', 'comments_page': 'capture_failed',
                                     'replies': 'capture_failed'}
    assert 'newsfeed' in result.data['updated']


def test_capture_with_an_unknown_request_count_keeps_the_whole_reservation(tmp_path):
    result = capture_run(Account(tmp_path), captured([], url=ROUTES[0], count=1, complete=False), captured([]), [])
    assert result.code == 8
    assert result.snippets.count('capture') == 1 and 'graphql' not in result.snippets


def test_capture_that_spends_the_budget_stops_the_replays(tmp_path):
    account = Account(tmp_path)
    result = capture_run(account, captured([], url=ROUTES[0], count=400 - SETUP - 1), captured([], count=1))
    assert result.code == 8
    assert 'graphql' not in result.snippets and saved(account) is None


def test_navigation_only_capture_reports_budget_exhaustion(tmp_path):
    result = capture_run(Account(tmp_path), captured([], url=ROUTES[0], failed='capture_budget', count=400 - SETUP),
                         captured([]), [])
    assert result.code == 8
    assert result.data['message'] == 'The shared request budget is exhausted during capture.'
