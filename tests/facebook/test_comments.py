"""Comments: parents are selected before replies are expanded, and every continuation keeps what was already shown."""
import json

from tests.facebook.helpers import (LIMITED, POST_URL, Account, comment_node, comment_page, envelope, login,
                                    more_args, post_response, story_id_page)

FAILURE = envelope('{"errors":[{"message":"Synthetic failure"}]}')


def opened(*pages):
    """Responses up to the first comment page: home, story id lookup, permalink."""
    return [login(), story_id_page(), post_response(), *pages]


def test_comments_limit_precedes_reply_expansion_and_resume_keeps_parent_handles(tmp_path):
    account = Account(tmp_path)
    first = account.run('comments', POST_URL, '--limit', '1', '--replies', '--json', responses=opened(
        comment_page([comment_node('c1'), comment_node('c1'), comment_node('c2')]),
        comment_page([comment_node('r1', 1, 'c1')], 'replies_connection')))
    assert first.code == 0, first.stdout
    assert first.ids == ['c1', 'r1']
    assert '_reply_handle' not in first.stdout
    replies = first.graphql(2)
    assert replies['name'] == 'Depth1CommentsListPaginationQuery'
    assert (replies['variables']['id'], replies['variables']['expansionToken']) == ('c1-feedback', 'c1-token')
    resumed = account.run(*more_args(first.data['next']), responses=[
        login(), comment_page([comment_node('r2', 1, 'c2')], 'replies_connection')])
    assert resumed.code == 0 and resumed.ids == ['c2', 'r2']
    assert resumed.graphql()['variables']['expansionToken'] == 'c2-token'


def test_parent_fragments_merge_before_limit_and_reply_expansion(tmp_path):
    first = comment_node('c1')
    first['body'] = None
    first['feedback']['replies_fields']['total_count'] = None
    result = Account(tmp_path).run('comments', POST_URL, '--limit', '1', '--replies', '--json', responses=opened(
        comment_page([first, comment_node('c1')]), comment_page([comment_node('r1', 1, 'c1')], 'replies_connection')))
    assert result.code == 0 and result.ids == ['c1', 'r1']
    assert result.data['results'][0]['text'] == 'Synthetic comment c1'


def test_comment_pages_continue_with_the_page_query_and_cursor(tmp_path):
    result = Account(tmp_path).run('comments', POST_URL, '--json', responses=opened(
        comment_page([comment_node('c1')], cursor='page2'), comment_page([comment_node('c2')])))
    assert result.code == 0 and result.ids == ['c1', 'c2']
    first, second = result.graphql(1), result.graphql(2)
    assert first['name'] == 'CommentListComponentsRootQuery' and 'commentsAfterCursor' not in first['variables']
    assert second['name'] == 'CommentsListComponentsPaginationQuery'
    assert second['variables']['commentsAfterCursor'] == 'page2'
    assert first['variables']['id'] == second['variables']['id'] == 'post-feedback'


def test_recent_order_selects_the_reverse_chronological_intent(tmp_path):
    result = Account(tmp_path).run('comments', POST_URL, '--sort', 'recent', responses=opened(
        comment_page([comment_node('c1')])))
    assert result.graphql(1)['variables']['commentsIntentToken'] == 'REVERSE_CHRONOLOGICAL_UNFILTERED_INTENT_V1'


def test_comments_connection_is_not_confused_with_its_count_only_preview(tmp_path):
    page = envelope({'data': {'node': {
        'comment_rendering_instance_for_feed_location': {'comments': {
            'edges': [{'node': comment_node('synthetic-comment')}], 'page_info': {'has_next_page': False}}},
        'comment_rendering_instance': {'comments': {'total_count': 20}}}}})
    result = Account(tmp_path).run('comments', POST_URL, '--json', responses=opened(page))
    assert result.code == 0 and result.ids == ['synthetic-comment']


def test_post_shows_full_text_and_preserves_it_when_comments_block(tmp_path):
    account = Account(tmp_path)
    result = account.run('post', POST_URL, '--json', responses=opened(LIMITED))
    assert result.code == 5, result.stdout
    assert result.data['results'][0]['text'] == 'Complete synthetic post'
    assert result.data['ok'] is False
    assert account.blocked()


def test_later_parent_block_keeps_block_exit_after_earlier_reply_failure(tmp_path):
    result = Account(tmp_path).run('comments', POST_URL, '--limit', '2', '--replies', '--json', responses=opened(
        comment_page([comment_node('c1')], cursor='second'), FAILURE, LIMITED))
    assert result.code == 5, result.stdout
    assert result.data['stop_reason'] == 'blocked'


def test_failed_reply_at_end_can_retry_without_repeating_shown_records(tmp_path):
    account = Account(tmp_path)
    first = account.run('comments', POST_URL, '--limit', '2', '--replies', '--json', responses=opened(
        comment_page([comment_node('c1'), comment_node('c2')]),
        comment_page([comment_node('r1', 1, 'c1')], 'replies_connection'), FAILURE))
    assert first.code == 8, first.stdout
    assert first.ids == ['c1', 'r1', 'c2']
    assert first.data['replies_incomplete'] == [{'parent_id': 'c2', 'reason': 'request_failure', 'retryable': True,
                                                 'code': 6, 'message': 'Facebook query failed or its expected '
                                                                       'structure changed.'}]
    retried = account.run(*more_args(first.data['next']), responses=[
        login(), comment_page([comment_node('r2', 1, 'c2')], 'replies_connection')])
    assert retried.code == 0 and retried.ids == ['r2']
    assert 'next' not in retried.data


def test_reply_batch_limit_is_reported_without_retrying_first_batch_forever(tmp_path):
    replies = json.loads(comment_page([comment_node('r1', 1, 'c1')], 'replies_connection')['body'])
    replies['data']['node']['replies_connection']['page_info'] = {'has_next_page': True, 'end_cursor': 'reply2'}
    result = Account(tmp_path).run('comments', POST_URL, '--limit', '1', '--replies', '--json', responses=opened(
        comment_page([comment_node('c1')]), envelope(replies)))
    assert result.code == 8
    assert result.data['stop_reason'] == 'query_failure'
    assert result.data['replies_incomplete'][0]['reason'] == 'batch_limit'
    assert result.data['replies_incomplete'][0]['retryable'] is False
    assert 'next' not in result.data


def test_reply_retry_and_unshown_parent_tail_resume_independently(tmp_path):
    account = Account(tmp_path)
    first = account.run('comments', POST_URL, '--limit', '1', '--replies', '--json', responses=opened(
        comment_page([comment_node('c1'), comment_node('c2')]), FAILURE))
    assert first.code == 8, first.stdout
    assert first.ids == ['c1']
    second = account.run(*more_args(first.data['next']), responses=[
        login(), comment_page([comment_node('r1', 1, 'c1')], 'replies_connection'),
        comment_page([comment_node('r2', 1, 'c2')], 'replies_connection')])
    assert second.code == 0 and second.ids == ['r1', 'c2', 'r2']
    assert 'next' not in second.data


def test_replies_are_expanded_only_for_parents_that_report_replies(tmp_path):
    quiet = comment_node('c1')
    quiet['feedback']['replies_fields']['total_count'] = 0
    result = Account(tmp_path).run('comments', POST_URL, '--replies', '--json', responses=opened(
        comment_page([quiet, comment_node('c2')]), comment_page([comment_node('r2', 1, 'c2')], 'replies_connection')))
    assert result.code == 0 and result.ids == ['c1', 'c2', 'r2']
    assert [call['args']['name'] for call in result.calls if call['name'] == 'graphql'] == [
        'CometSinglePostDialogContentQuery', 'CommentListComponentsRootQuery', 'Depth1CommentsListPaginationQuery']


def test_post_continues_comments_with_the_first_batch_root_cursor(tmp_path):
    account = Account(tmp_path)
    first = account.run('post', POST_URL, '--json', responses=opened(
        comment_page([comment_node('c1')], cursor='page2')))
    assert first.code == 0
    assert more_args(first.data['next']) == ['comments', POST_URL, '--sort', 'top', '--json', '--after', '1']
    following = account.run(*more_args(first.data['next']), responses=[login(), comment_page([comment_node('c2')])])
    assert following.code == 0 and following.ids == ['c2']
    assert following.graphql()['variables']['commentsAfterCursor'] == 'page2'


def test_post_limit_selects_parents_within_the_first_batch_and_continues_with_the_rest(tmp_path):
    account = Account(tmp_path)
    first = account.run('post', POST_URL, '--limit', '1', '--json', responses=opened(
        comment_page([comment_node('c1'), comment_node('c2')])))
    assert first.code == 0 and first.ids == ['post-feedback', 'c1']
    following = account.run(*more_args(first.data['next']), responses=[login()])
    assert following.code == 0 and following.ids == ['c2']


def test_post_with_an_exhausted_first_batch_has_no_continuation(tmp_path):
    result = Account(tmp_path).run('post', POST_URL, '--json', responses=opened(comment_page([comment_node('c1')])))
    assert result.code == 0 and result.ids == ['post-feedback', 'c1']
    assert 'next' not in result.data


def test_post_text_renders_the_post_then_its_comments(tmp_path):
    result = Account(tmp_path).run('post', POST_URL, responses=opened(
        comment_page([comment_node('c1'), comment_node('r1', 1, 'c1', text='Reply\nline')])))
    lines = result.stdout.splitlines()
    assert lines[0] == 'post · 2 shown · stopped=exhausted'
    assert lines[1].startswith('[p1] unavailable · undated · status')
    assert lines[4].startswith('[c1] Synthetic · undated · reactions=? replies=1')


def test_replies_render_indented_under_their_parent_label(tmp_path):
    result = Account(tmp_path).run('comments', POST_URL, '--replies', responses=opened(
        comment_page([comment_node('c1')]),
        comment_page([comment_node('r1', 1, 'c1', text='Reply\nline')], 'replies_connection')))
    assert result.code == 0
    assert '\n  [c2 reply-to=c1] Synthetic · ' in result.stdout
    assert 'text[10/10 chars, complete]: "Reply⏎line"' in result.stdout


def test_post_continuation_carries_only_the_comment_query_and_explicit_controls(tmp_path):
    result = Account(tmp_path).run('post', POST_URL, '--limit', '1', '--max-requests', '9', '--json',
                                   responses=opened(comment_page([comment_node('c1'), comment_node('c2')])))
    assert more_args(result.data['next']) == ['comments', POST_URL, '--sort', 'top', '--json', '--max-requests', '9',
                                              '--after', '1']


def test_post_continuation_serves_the_unshown_tail_of_a_cut_first_batch(tmp_path):
    account = Account(tmp_path)
    first = account.run('post', POST_URL, '--limit', '1', '--json', responses=opened(
        comment_page([comment_node('c1'), comment_node('c2')], cursor='page2')))
    # The continuation carries no page size: it serves the unshown c2, then reads on from the root cursor.
    rest = account.run(*more_args(first.data['next']), responses=[login(), comment_page([comment_node('c3')])])
    assert rest.code == 0 and rest.ids == ['c2', 'c3']
    assert rest.graphql()['variables']['commentsAfterCursor'] == 'page2'


def test_post_whose_comments_fail_keeps_the_post_and_offers_no_continuation(tmp_path):
    result = Account(tmp_path).run('post', POST_URL, '--json', responses=opened(FAILURE))
    assert result.code == 8
    assert result.ids == ['post-feedback'] and 'next' not in result.data
