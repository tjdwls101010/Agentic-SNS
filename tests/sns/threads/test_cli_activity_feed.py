"""The viewer's notification list through cli.py and fake Aside; all rows here are synthetic. The list query must
never open the activity screen or send a mutation, including when its stored query id is refused."""
import json

import pytest

from tests.sns.threads.scenes import known_tab, queries, query_result, run

POST_URL = 'https://www.threads.com/@example.writer/post/Cexample'
HEAD = ['kind', 'id', 'url', 'created_at']


def row(identity='n1', *, media=True, actors=('example.actor',), title='Someone replied', body='A reply'):
    return {'__typename': 'XTHNotificationFeedRow', 'edge_id': identity, 'timestamp': 1791428400,
            'notif_name': 'reply', 'story_type': 1, 'title': {'text': title, 'ranges': []}, 'body': {'text': body},
            'sender_users': {'edges': [{'node': {'username': name}} for name in actors]},
            'destination': 'media?id=123',
            'ufi_media': {'code': 'Cexample', 'pk': '123', 'user': {'username': 'example.writer', 'pk': '456'},
                          'like_count': 3, 'text_post_app_info': {'direct_reply_count': 2, 'quote_count': 1,
                                                                'repost_count': 0}} if media else None}


def header(bucket):
    return {'__typename': 'XTHNotifFeedBucketHeader', 'bucket_type': bucket}


def inbox(nodes, more=False):
    return {'data': {'notifications': {'edges': [{'node': node} for node in nodes],
                                      'page_info': {'end_cursor': 'OLDER' if more else None, 'has_next_page': more}}}}


def test_one_page_skips_headers_and_keeps_seen_state_shared_head_and_post_counts(browser):
    nodes = [row('unknown', media=False, actors=(), body='Someone replied'), header('NEW'), row(),
             row('follow', media=False, actors=('example.one', 'example.two')), header('EARLIER'),
             row('seen', media=False, body='Someone replied'), header('OTHER'), row('other')]
    known_tab(browser).respond('threads.query', query_result(inbox(nodes)))
    code, out, _ = run(browser, 'activity', '--json', '--chars', '1')
    result = json.loads(out)
    assert code == 0, result
    records = result['results']
    assert [r['id'] for r in records] == ['unknown', 'n1', 'follow', 'seen', 'other']
    assert [r['unseen'] for r in records] == [None, True, True, False, None]
    assert all(list(r)[:4] == HEAD and r['kind'] == 'notification' for r in records)
    assert all(r['created_at'] == '2026-10-08T03:00:00Z' and r['captured_at'].endswith('Z') for r in records)
    assert records[0]['url'] is None and records[0]['post'] is None
    assert records[1]['url'] == POST_URL and records[1]['text'] == 'Someone replied\nA reply'
    assert records[1]['notification_type'] == 'reply' and records[1]['actors'] == ['example.actor']
    assert records[1]['post'] == {'url': POST_URL, 'like_count': 3, 'direct_reply_count': 2,
                                  'quote_count': 1, 'repost_count': 0}
    assert records[2]['url'] == 'https://www.threads.com/@example.one'
    assert records[2]['actors'] == ['example.one', 'example.two'] and records[3]['text'] == 'Someone replied'
    assert result['request_count'] == 1 and result['stop_reason'] == 'exhausted' and not result.get('next')
    call = queries(browser)[0]['args']
    assert call['name'] == 'BarcelonaActivityFeedV2StoryListContainerQuery'
    assert call['endpoint'] == '/api/graphql/' and call['root'] is None
    assert call['fallback']['doc_id'] == '27957944693878890'
    assert {p[1] for p in call['fallback']['providers']} == {
        'BarcelonaHasCommunityTopContributors.relayprovider', 'BarcelonaHasViewerReplied.relayprovider',
        'BarcelonaHasWebFavicons.relayprovider'}
    assert call['variables'] == {'first': 20, 'selected_filters': None}


@pytest.mark.parametrize('word,expected', [
    ('all', None), ('mentions', 'text_post_app_mentions'), ('replies', 'text_post_app_replies'),
    ('quotes', 'text_post_app_quote_posts'), ('reposts', 'text_post_app_reposts'),
    ('follows', 'text_post_app_user_follows'),
    ('conversations', 'text_post_app_conversations'), ('following', 'text_post_app_following'),
    ('requests', 'text_post_app_private_follow_requests')])
def test_filter_words_are_the_apps_wire_values(browser, word, expected):
    known_tab(browser).respond('threads.query', query_result(inbox([row()])))
    code, out, _ = run(browser, 'activity', '--filter', word, '--json')
    assert code == 0, out
    assert queries(browser)[0]['args']['variables']['selected_filters'] == expected


@pytest.mark.parametrize('limit', [1, 50])
def test_limit_is_the_first_variable_and_a_server_cap_is_never_paginated(browser, limit):
    known_tab(browser).respond('threads.query', query_result(inbox([header('NEW'), row()], more=True)))
    code, out, _ = run(browser, 'activity', '--limit', str(limit), '--json')
    result = json.loads(out)
    assert code == 0, result
    assert len(queries(browser)) == 1 and queries(browser)[0]['args']['variables']['first'] == limit
    assert result['stop_reason'] == 'server_capped' and not result.get('next')
    assert any('older activity' in note and 'only this page' in note for note in result['coverage'])


@pytest.mark.parametrize('limit', ['0', '51', '-1'])
def test_limit_outside_one_to_fifty_is_refused_before_aside(browser, limit):
    code, out, _ = run(browser, 'activity', '--limit', limit)
    assert code == 2 and '1 to 50' in json.loads(out)['message']
    assert browser.calls() == []


@pytest.mark.parametrize('broken', [{'__typename': 'UnknownRow'},
                                    {**row(), 'edge_id': None}, {**row(), 'title': None, 'body': None}])
def test_an_unreadable_row_is_a_failure_instead_of_an_empty_list(browser, broken):
    known_tab(browser).respond('threads.query', query_result(inbox([broken])))
    code, out, _ = run(browser, 'activity', '--json')
    assert code == 6 and json.loads(out)['results'] == [], out


@pytest.mark.parametrize('source', ['stored', 'live'])
def test_a_refused_activity_query_never_learns_or_reloads_a_screen(browser, source):
    refused = {'errors': [{'message': 'Execution error', 'severity': 'CRITICAL'}]}
    known_tab(browser).respond('threads.query', query_result(refused, source=source))
    code, out, _ = run(browser, 'activity', '--json')
    result = json.loads(out)
    assert code == 6, result
    assert 'no longer accepts the stored activity query' in result['message']
    assert 'does not open the activity screen to relearn' in result['message']
    assert 'marks notifications seen' in result['message']
    assert len(queries(browser)) == 1
    assert not set(browser.ops()) & {'threads.page', 'threads.navigate', 'threads.route', 'open'}


def test_the_query_allow_list_contains_no_mutation(browser):
    known_tab(browser).respond('threads.query', query_result(inbox([row()])))
    code, out, _ = run(browser, 'activity')
    assert code == 0, out
    assert not any('Mutation' in name for name in queries(browser)[0]['args']['allowed'])
    assert not set(browser.ops()) & {'threads.page', 'threads.navigate', 'threads.route', 'open'}


def test_text_renders_notification_labels_seen_state_and_full_text(browser):
    nodes = [header('NEW'), row(), header('EARLIER'), row('n2')]
    known_tab(browser).respond('threads.query', query_result(inbox(nodes)))
    code, out, _ = run(browser, 'activity', '--chars', '0')
    assert code == 0, out
    assert '[n1] 2026-10-08' in out and ' · reply · unseen' in out
    assert '[n2] 2026-10-08' in out and ' · reply · seen' in out
    assert 'Someone replied' in out and 'A reply' in out and 'url: "' + POST_URL + '"' in out


def test_activity_help_explains_the_read_coverage_and_seen_caveat(browser):
    code, out, _ = run(browser, 'activity', '--help')
    assert code == 0, out
    assert 'one page' in out and 'server_capped' in out and 'requests: 1.' in out
    assert ('Reading the list sends no seen change (the app marks notifications seen only when its activity screen '
            'opens, which this skill never does); seen state as observed on 2026-10-22.') in out
    assert '[n1] notification' in out and 'the dedicated tab:' in out
    assert browser.calls() == []


def test_the_notification_schema_describes_every_record_key(browser):
    code, out, _ = run(browser, 'schema', 'notification')
    assert code == 0, out
    schema = next(r for r in json.loads(out)['results'] if r.get('object') == 'notification')
    assert set(schema['fields']) == {*HEAD, 'notification_type', 'text', 'unseen', 'actors', 'post', 'captured_at'}
    assert all(key in schema['fields']['post'] for key in ('url', 'like_count', 'direct_reply_count',
                                                         'quote_count', 'repost_count'))
    assert schema['fields']['url'].startswith('string | null —')
    assert schema['fields']['unseen'].startswith('boolean | null —')
    assert schema['fields']['actors'].startswith('array<string> —')


def test_an_explicit_empty_activity_list_is_empty_not_failed(browser):
    known_tab(browser).respond('threads.query', query_result(inbox([header('EARLIER')])))
    code, out, _ = run(browser, 'activity', '--json')
    result = json.loads(out)
    assert code == 7 and result['results'] == [] and result['stop_reason'] == 'exhausted', result
