"""Reading posts: pages, limits and unshown tails, date windows, continuation and the dense text rendering."""
import json
from datetime import datetime

import pytest

from tests.facebook.helpers import (Account, LIMITED, chunks, envelope, feed_page, feed_stories, fixture_response,
                                    group_page, login, more_args, post_response, story, story_id_page, text_more,
                                    timeline_page)

SEOUL = {'TZ': 'Asia/Seoul'}


def dated(ident, day, **fields):
    return story(ident, ident, creation_time=int(datetime.fromisoformat(day).timestamp()), **fields)


def test_feed_midpage_resume_has_no_loss_and_no_refetch(tmp_path):
    account = Account(tmp_path)
    first = account.run('feed', '--limit', '1', '--json', responses=[login(), feed_page(['p1', 'p2', 'p3'])])
    assert first.code == 0 and first.ids == ['p1']
    second = account.run(*more_args(first.data['next']), responses=[login()])
    assert second.code == 0 and second.ids == ['p2']
    assert second.snippets == ['tokens']


def test_split_page_keeps_the_server_cursor_behind_its_unshown_tail(tmp_path):
    account = Account(tmp_path)
    first = account.run('feed', '--limit', '1', '--json', responses=[login(), feed_page(['p1', 'p2'], 'next')])
    tail = account.run(*more_args(first.data['next']), responses=[login()])
    assert tail.code == 0 and tail.ids == ['p2'] and tail.snippets == ['tokens']
    following = account.run(*more_args(tail.data['next']), responses=[login(), feed_page(['p3'])])
    assert following.code == 0 and following.ids == ['p3']
    assert following.graphql()['variables']['cursor'] == 'next'


def test_exhausted_last_page_tail_is_served_without_restarting(tmp_path):
    account = Account(tmp_path)
    first = account.run('feed', '--limit', '1', '--json', responses=[login(), feed_page(['p1', 'p2'])])
    second = account.run(*more_args(first.data['next'])[:-2], '--limit', '5', '--after',
                         more_args(first.data['next'])[-1], responses=[login()])
    assert second.code == 0 and second.ids == ['p2']
    assert second.data['stop_reason'] == 'exhausted' and 'next' not in second.data
    assert second.snippets == ['tokens']


def test_empty_feed_page_with_a_next_cursor_continues_to_real_results(tmp_path):
    result = Account(tmp_path).run('feed', '--limit', '1', '--json',
                                   responses=[login(), feed_page([], 'next'), feed_page(['p1'])])
    assert result.code == 0 and result.ids == ['p1']
    assert result.graphql(1)['variables']['cursor'] == 'next'


def test_nonempty_connection_with_unreadable_posts_is_failure_not_empty(tmp_path):
    page = feed_stories([{'unknown_shape': 'synthetic'}])
    assert Account(tmp_path).run('feed', '--limit', '1', '--json', responses=[login(), page]).code == 6


def test_missing_page_info_is_a_partial_failure_not_exhaustion(tmp_path):
    page = envelope({'data': {'viewer': {'news_feed': {'edges': [{'node': story('p1')}]}}}})
    result = Account(tmp_path).run('feed', '--json', responses=[login(), page])
    assert result.code == 8
    assert result.data['stop_reason'] == 'query_failure' and result.ids == ['p1']
    assert result.data['message'] == 'Missing explicit pagination metadata.'


@pytest.mark.parametrize('edges,has_next,code', [([{'node': story('x')}], False, 0), ([], False, 7),
                                                 ([], True, 0), ([], None, 6)])
def test_inline_connection_and_deferred_page_info_are_read_together(tmp_path, edges, has_next, code):
    info = {'end_cursor': 'next'}
    if has_next is not None:
        info['has_next_page'] = has_next
    body = chunks({'data': {'viewer': {'news_feed': {'edges': edges}}}},
                  {'path': ['viewer', 'news_feed'], 'data': {'page_info': info}})
    result = Account(tmp_path).run('feed', '--json', responses=[login(), body, feed_page(['after'])])
    assert result.code == code, result.stdout
    if has_next is True:
        assert result.ids == ['after'] and result.graphql(1)['variables']['cursor'] == 'next'


def test_deferred_metadata_cannot_supply_edges_from_a_different_connection(tmp_path):
    body = envelope(feed_page(['x'])['body'] + '\n' + json.dumps({'path': ['other', 'news_feed'],
                                              'data': {'page_info': {'has_next_page': False}}}))
    assert Account(tmp_path).run('feed', responses=[login(), body]).code == 6


def test_deferred_page_info_ignores_nested_other_connections(tmp_path):
    body = chunks({'data': {'viewer': {'news_feed': {'edges': [{'node': story('p1')}]}},
                            'other': {'page_info': {'has_next_page': True, 'end_cursor': 'wrong'}}}},
                  {'path': ['viewer', 'news_feed'], 'data': {'page_info': {'has_next_page': False}}})
    result = Account(tmp_path).run('feed', '--json', responses=[login(), body])
    assert result.code == 0 and result.ids == ['p1']
    assert result.data['stop_reason'] == 'exhausted' and 'next' not in result.data


def test_page_info_accepts_the_anti_json_prefix(tmp_path):
    body = envelope('for (;;);' + feed_page(['p1'], 'next')['body'])
    result = Account(tmp_path).run('feed', '--limit', '1', '--json', responses=[login(), body])
    assert result.code == 0 and result.ids == ['p1'] and result.data['next']


def test_repeated_cursor_stops_as_a_query_failure(tmp_path):
    result = Account(tmp_path).run('feed', '--json', responses=[login(), feed_page(['p1'], 'same'),
                                                                feed_page(['p2'], 'same'), feed_page(['p3'])])
    assert result.code == 8 and result.ids == ['p1', 'p2']
    assert result.data['message'] == 'The server repeated a cursor.'


@pytest.mark.parametrize('command,page,target', [('profile', timeline_page, '42'), ('group', group_page, '123')])
def test_numeric_targets_skip_resolution_and_keep_window_order(tmp_path, command, page, target):
    body = page([dated('inside', '2026-09-03T12:00:00'), dated('outside', '2026-08-01T12:00:00')])
    result = Account(tmp_path).run(command, target, '--since', '2026-09-01', '--until', '2026-09-05', '--json',
                                   responses=[login(), body])
    assert result.code == 0 and result.ids == ['inside']
    assert result.snippets == ['tokens', 'graphql']


def test_profile_window_is_sent_to_the_server_as_local_day_bounds(tmp_path):
    result = Account(tmp_path).run('profile', '42', '--since', '2026-09-01', '--until', '2026-09-05', '--json',
                                   env=SEOUL, responses=[login(), timeline_page([dated('p', '2026-09-03T12:00:00')])])
    variables = result.graphql()['variables']
    assert variables['afterTime'] == 1788188400    # 2026-09-01T00:00:00+09:00
    assert variables['beforeTime'] == 1788620399   # 2026-09-05T23:59:59+09:00
    assert result.data['window_mode'] == 'server' and result.data['window_complete'] is True


def test_ranked_date_window_filters_without_resorting_or_stopping_at_old_posts(tmp_path):
    first = group_page([dated('old', '2020-01-01T12:00:00'),
                        dated('pinned', '2020-01-01T12:00:00', is_pinned_story=True)], 'b')
    second = group_page([dated('newer', '2026-09-03T12:00:00'), story('old'), dated('new', '2026-09-02T12:00:00'),
                         dated('future', '2026-10-01T12:00:00')])
    result = Account(tmp_path).run('group', '123', '--sort', 'top', '--since', '2026-09-01', '--until', '2026-09-30',
                                   '--json', responses=[login(), first, second])
    assert result.code == 0 and result.ids == ['pinned', 'newer', 'new']
    assert result.data['stop_reason'] == 'exhausted'
    assert result.data['window_mode'] == 'client' and result.data['window_complete'] is False


@pytest.mark.parametrize('command,args,response', [
    ('feed', [], feed_page(['x'])),
    ('profile', ['42'], timeline_page([story('x')])),
    ('group', ['123'], group_page([story('x')])),
    ('search', ['synthetic', '--type', 'posts'], envelope({'data': {'serpResponse': {'results': {
        'edges': [{'node': story('x')}], 'page_info': {'has_next_page': False}}}}})),
])
def test_each_timeline_query_accepts_its_connection(tmp_path, command, args, response):
    result = Account(tmp_path).run(command, *args, '--json', responses=[login(), response])
    assert result.code == 0 and result.ids == ['x']


# --- the dense text rendering ---------------------------------------------------------------------------------------

def test_dense_post_text_separates_display_clipping_from_server_truncation(tmp_path):
    body = feed_stories([{'feedback': {'id': 'synthetic-post', 'reaction_count': {'count': 0}}, 'creation_time': 0,
                          'actors': [{'name': 'Synthetic Author'}], 'message': {'text': 'One\nTwo more'}}])
    result = Account(tmp_path).run('feed', '--chars', '7', env=SEOUL, responses=[login(), body])
    assert result.code == 0
    assert result.stdout == ('feed · sort=top · 1 shown · stopped=exhausted\n'
                             '[p1] Synthetic Author · 1970-01-01T09:00+09:00 · status · reactions=0 comments=? shares=?\n'
                             '     text[7/12 chars, complete]: "One⏎Two…"\n'
                             '     url: unavailable   author: unavailable\n')


def test_text_output_ends_with_the_continuation_command(tmp_path):
    result = Account(tmp_path).run('feed', '--limit', '1', responses=[login(), feed_page(['p1', 'p2'])])
    assert result.stdout.splitlines()[0] == 'feed · sort=top · 1 shown · stopped=limit_reached'
    assert more_args(text_more(result.stdout)) == ['feed', '--sort', 'top', '--limit', '1', '--chars', '180',
                                                   '--after', '1']


def test_nested_shared_chain_renders_every_body_handle_and_truncation(tmp_path):
    result = Account(tmp_path).run('post', 'https://www.facebook.com/zuck/posts/123', responses=[
        login(), story_id_page(), fixture_response('nested_shared_chain.ndjson'),
        envelope({'data': {'node': {'comments': {'edges': [], 'page_info': {'has_next_page': False}}}}})])
    assert result.code == 0, result.stdout
    text = result.stdout
    assert 'text[11/11 chars, complete]: "Synthetic B"' in text
    assert 'url: "https://example.test/posts/B"' in text
    assert 'text[15/15 chars, truncated]: "Synthetic C cut"' in text
    assert 'url: "https://example.test/posts/C"' in text
    assert text.index('Synthetic B') < text.index('Synthetic C cut')


def test_deep_shared_chain_renders_the_tail(tmp_path):
    node = {'feedback': {'id': 'tail'}, 'message': {'text': 'Deepest synthetic'},
            'permalink_url': 'https://example.test/tail'}
    for depth in range(30):
        node = {'feedback': {'id': f'wrapper-{depth}'}, 'message': {'text': 'Synthetic wrapper'},
                'attached_story': node}
    result = Account(tmp_path).run('feed', '--chars', '500', responses=[login(), feed_stories([node])])
    assert result.code == 0
    assert 'shared-from[30]: unavailable · undated · url: "https://example.test/tail" · ' \
           'text[17/17 chars, complete]: "Deepest synthetic"' in result.stdout
    assert 'incomplete (cycle)' not in result.stdout


def test_post_shows_full_text_whatever_chars_says(tmp_path):
    long_text = 'Complete synthetic post ' * 20
    result = Account(tmp_path).run('post', 'https://www.facebook.com/zuck/posts/123', '--chars', '1', responses=[
        login(), story_id_page(), post_response(long_text),
        envelope({'data': {'node': {'comments': {'edges': [], 'page_info': {'has_next_page': False}}}}})])
    assert result.code == 0
    assert json.dumps(long_text) in result.stdout
    assert 'comments starts from' not in result.stdout


def test_post_keeps_deferred_updates_and_incomplete_marker_on_requested_root(tmp_path):
    body = chunks({'data': {'unrelated': {'feedback': {'id': 'decoy'}, 'message': {'text': 'Wrong post'}},
                            'node': {'feedback': {'id': 'post-feedback'}, 'message': None}}},
                  {'path': ['node'], 'data': {'feedback': {'id': 'post-feedback'},
                                              'message': {'text': 'Deferred full post'}}},
                  {'path': ['node', 'message'], 'data': {'text': 'Unsupported partial patch'}})
    result = Account(tmp_path).run('post', 'https://www.facebook.com/zuck/posts/123', '--json', responses=[
        login(), story_id_page(), body,
        envelope({'data': {'node': {'comments': {'edges': [], 'page_info': {'has_next_page': False}}}}})])
    assert result.code == 0, result.stdout
    post = result.data['results'][0]
    assert (post['id'], post['text'], post['incomplete']) == ('post-feedback', 'Deferred full post', True)


def test_post_without_its_requested_root_is_a_query_failure(tmp_path):
    body = envelope({'data': {'node': {'id': 'x', '__typename': 'Story'}}})
    result = Account(tmp_path).run('post', 'https://www.facebook.com/zuck/posts/123', responses=[
        login(), story_id_page(), body])
    assert result.code == 6
    assert result.data['message'] == 'The post response contains no readable post.'


def test_post_story_id_lookup_failure_stops_before_the_query(tmp_path):
    result = Account(tmp_path).run('post', 'https://www.facebook.com/zuck/posts/123', responses=[
        login(), envelope('<html>no id</html>', url='https://www.facebook.com/zuck/posts/123')])
    assert result.code == 6 and result.snippets == ['tokens', 'page']


def test_explicitly_empty_result_is_its_own_exit_not_a_query_failure(tmp_path):
    result = Account(tmp_path).run('feed', '--json', responses=[login(), feed_page([])])
    assert result.code == 7
    assert result.data['error'] == 'empty' and result.data['stop_reason'] == 'exhausted'


def test_blocked_feed_keeps_records_read_before_the_block(tmp_path):
    result = Account(tmp_path).run('feed', '--json', responses=[login(), feed_page(['p1'], 'next'), LIMITED])
    assert result.code == 5
    assert result.data['stop_reason'] == 'blocked' and result.ids == ['p1']
