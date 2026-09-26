"""Collections (--out) and numbered continuation handles, as files a later invocation resumes."""
import json

from tests.facebook.helpers import (POST_URL, Account, comment_node, comment_page, envelope, feed_page, login,
                                    more_args, post_response, search_page, entity, story, story_id_page, timeline_page)


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_output_file_commits_full_page_and_resumes_without_requery(tmp_path):
    account = Account(tmp_path)
    path = tmp_path / 'posts.ndjson'
    first = account.run('feed', '--limit', '1', '--out', str(path), '--json', responses=[login(), feed_page(['p1', 'p2', 'p3'])])
    assert first.code == 0 and first.data['count'] == 3
    second = account.run('feed', '--limit', '1', '--out', str(path), '--json', responses=[login()])
    assert second.code == 0
    assert second.data['stop_reason'] == 'exhausted' and second.data['already_complete'] is True
    assert second.data['count'] == 3 and second.snippets == ['tokens']


def test_text_summary_names_the_file_and_the_count(tmp_path):
    path = tmp_path / 'posts.ndjson'
    result = Account(tmp_path).run('feed', '--out', str(path), responses=[login(), feed_page(['p1'])])
    assert result.stdout == f'feed · 1 saved · stopped=exhausted · {json.dumps(str(path))}\n'


def test_page_limit_keeps_whole_page_and_skips_ids_already_saved(tmp_path):
    account = Account(tmp_path)
    path = tmp_path / 'posts.ndjson'
    assert account.run('feed', '--limit', '1', '--out', str(path), responses=[
        login(), feed_page(['1', '2', '3'], 'b')]).code == 0
    second = account.run('feed', '--limit', '5', '--out', str(path), '--json', responses=[
        login(), feed_page(['3', '4'])])
    assert second.code == 0 and second.ids == ['4']
    saved = rows(path)
    assert [r['id'] for r in saved if r.get('kind') not in ('header', 'page')] == ['1', '2', '3', '4']
    assert saved[0]['kind'] == 'header'
    assert [(r['n'], r['ids']) for r in saved if r.get('kind') == 'page'] == [(3, ['1', '2', '3']), (1, ['4'])]


def test_interrupted_page_is_discarded_and_replayed_without_loss_or_duplicates(tmp_path):
    account = Account(tmp_path)
    path = tmp_path / 'posts.ndjson'
    assert account.run('feed', '--out', str(path), '--limit', '1', responses=[login(), feed_page(['1'], 'next')]).code == 0
    with path.open('ab') as stream:
        stream.write(b'{"id":"2","text":"uncommitted"}\n{"id":')
    resumed = account.run('feed', '--out', str(path), '--limit', '5', '--json', responses=[
        login(), feed_page(['1', '2'])])
    assert resumed.code == 0 and resumed.data['count'] == 2
    assert resumed.graphql()['variables']['cursor'] == 'next'
    assert [r['id'] for r in rows(path) if 'id' in r and r.get('kind') != 'page'] == ['1', '2']


def test_out_limit_is_cumulative_and_satisfied_limit_does_not_query(tmp_path):
    account = Account(tmp_path)
    path = str(tmp_path / 'cumulative.ndjson')
    assert account.run('feed', '--limit', '3', '--out', path, responses=[login(), feed_page(['p1', 'p2', 'p3'], 'page2')]).code == 0
    second = account.run('feed', '--limit', '6', '--out', path, '--json', responses=[login(), feed_page(['p4', 'p5', 'p6'], 'page3')])
    assert second.code == 0 and second.data['count'] == 6
    third = account.run('feed', '--limit', '6', '--out', path, '--json', responses=[login()])
    assert third.code == 0 and third.data['count'] == 6 and third.snippets == ['tokens']


def test_comments_out_limit_counts_saved_parents_not_replies(tmp_path):
    account = Account(tmp_path)
    path = str(tmp_path / 'comments.ndjson')
    first = account.run('comments', POST_URL, '--replies', '--limit', '1', '--out', path, '--json', responses=[
        login(), story_id_page(), post_response(), comment_page([comment_node('c1')], cursor='page2'),
        comment_page([comment_node('r1', 1, 'c1')], 'replies_connection')])
    assert first.code == 0, first.stdout
    second = account.run('comments', POST_URL, '--replies', '--limit', '2', '--out', path, '--json', responses=[
        login(), comment_page([comment_node('c2')], cursor='page3'),
        comment_page([comment_node('r2', 1, 'c2')], 'replies_connection')])
    assert second.code == 0
    assert second.data['count'] == 4 and second.ids == ['c2', 'r2']
    third = account.run('comments', POST_URL, '--replies', '--limit', '2', '--out', path, '--json', responses=[login()])
    assert third.code == 0 and third.data['request_count'] == 1


def test_retryable_reply_failure_leaves_the_comment_page_uncommitted(tmp_path):
    account = Account(tmp_path)
    path = tmp_path / 'comments.ndjson'
    failed = account.run('comments', POST_URL, '--replies', '--out', str(path), '--json', responses=[
        login(), story_id_page(), post_response(), comment_page([comment_node('c1')]),
        envelope('{"errors":[{"message":"Synthetic failure"}]}')])
    assert failed.code == 8
    assert [r for r in rows(path) if r.get('kind') != 'header'] == []
    resumed = account.run('comments', POST_URL, '--replies', '--out', str(path), '--json', responses=[
        login(), story_id_page(), post_response(), comment_page([comment_node('c1')]),
        comment_page([comment_node('r1', 1, 'c1')], 'replies_connection')])
    assert resumed.code == 0
    assert [r['id'] for r in rows(path) if r.get('kind') is None] == ['c1', 'r1']


def test_page_limit_on_the_last_full_page_is_already_complete(tmp_path):
    account = Account(tmp_path)
    path = str(tmp_path / 'last.ndjson')
    assert account.run('feed', '--limit', '1', '--out', path, responses=[login(), feed_page(['1', '2'])]).code == 0
    again = account.run('feed', '--limit', '1', '--out', path, '--json', responses=[login()])
    assert again.data['already_complete'] is True and again.data['count'] == 2


def test_an_entity_of_kind_page_is_a_record_not_a_page_marker(tmp_path):
    account = Account(tmp_path)
    path = str(tmp_path / 'entities.ndjson')
    assert account.run('search', 'synthetic', '--type', 'pages', '--limit', '1', '--out', path, responses=[
        login(), search_page([entity('123', 'Page')], 'next')]).code == 0
    resumed = account.run('search', 'synthetic', '--type', 'pages', '--limit', '2', '--out', path, '--json',
                          responses=[login(), search_page([entity('456', 'Page')])])
    assert resumed.code == 0 and resumed.data['count'] == 2 and resumed.ids == ['456']


def test_wrong_context_never_truncates_an_existing_file(tmp_path):
    account = Account(tmp_path)
    path = tmp_path / 'posts.ndjson'
    assert account.run('feed', '--out', str(path), '--limit', '1', responses=[login(), feed_page(['1'], 'next')]).code == 0
    before = path.read_bytes()
    other = account.run('feed', '--sort', 'recent', '--out', str(path), responses=[login()])
    assert other.code == 2 and path.read_bytes() == before
    profile = tmp_path / 'profile.ndjson'
    assert account.run('profile', '4', '--out', str(profile), '--limit', '1', responses=[
        login(), timeline_page([story('p1')], 'next')]).code == 0
    before = profile.read_bytes()
    another = account.run('profile', '5', '--out', str(profile), responses=[login()])
    assert another.code == 2 and profile.read_bytes() == before


def test_non_object_header_is_an_argument_error_that_keeps_the_file(tmp_path):
    path = tmp_path / 'broken.ndjson'
    path.write_text('[]\n')
    result = Account(tmp_path).run('feed', '--out', str(path), responses=[login()])
    assert result.code == 2 and path.read_text() == '[]\n'


def test_output_file_is_locked_while_one_invocation_writes_it(tmp_path):
    import fcntl
    path = tmp_path / 'locked.ndjson'
    with path.open('w') as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        result = Account(tmp_path).run('feed', '--out', str(path), responses=[login()])
    assert result.code == 2
    assert result.data['message'] == 'Cannot open or lock the output file.'


def test_continuation_handles_increase_and_are_bound_to_their_query(tmp_path):
    account = Account(tmp_path)
    first = account.run('feed', '--limit', '1', '--json', responses=[login(), feed_page(['a', 'b', 'c'])])
    second = account.run('feed', '--limit', '1', '--json', responses=[login(), feed_page(['x', 'y'])])
    assert int(more_args(second.data['next'])[-1]) > int(more_args(first.data['next'])[-1])
    handle = more_args(first.data['next'])[-1]
    assert account.run('feed', '--sort', 'recent', '--after', handle, responses=[login()]).code == 2
    assert account.run('feed', '--after', '999', responses=[login()]).code == 2
    assert account.run('feed', '--after', '../blocked', responses=[login()]).code == 2
    assert account.run(*more_args(first.data['next']), '--json', responses=[login()]).ids == ['b']


def test_search_continuation_rejects_a_changed_type(tmp_path):
    account = Account(tmp_path)
    first = account.run('search', 'synthetic', '--type', 'pages', '--limit', '1', '--json',
                        responses=[login(), search_page([entity('p1', 'Page'), entity('p2', 'Page')])])
    assert first.code == 0 and first.data['results'][0]['kind'] == 'page'
    args = more_args(first.data['next'])
    args[args.index('pages')] = 'people'
    resumed = account.run(*args, responses=[login()])
    assert resumed.code == 2 and resumed.data['ok'] is False


def test_a_continuation_handle_from_an_earlier_version_is_refused_untouched(tmp_path):
    account = Account(tmp_path)
    first = account.run('feed', '--limit', '1', '--json', responses=[login(), feed_page(['a', 'b'])])
    handle = more_args(first.data['next'])[-1]
    path = account.home / 'cursors' / f'{handle}.json'
    old = json.loads(path.read_text())
    old.pop('format')
    path.write_text(json.dumps(old))
    before = path.read_bytes()
    result = account.run(*more_args(first.data['next']), responses=[login()])
    assert result.code == 2 and 'earlier version' in result.data['message']
    assert path.read_bytes() == before


def test_an_output_file_from_an_earlier_version_is_refused_before_any_write(tmp_path):
    account = Account(tmp_path)
    path = tmp_path / 'old.ndjson'
    assert account.run('feed', '--out', str(path), '--limit', '1', responses=[login(), feed_page(['1'], 'next')]).code == 0
    lines = path.read_text().splitlines()
    header = json.loads(lines[0])
    header.pop('format')
    path.write_text('\n'.join([json.dumps(header), *lines[1:]]) + '\n{"id": "torn')
    before = path.read_bytes()
    result = account.run('feed', '--out', str(path), '--limit', '5', responses=[login()])
    assert result.code == 2 and 'earlier version' in result.data['message']
    assert 'new --out path' in result.data['fix']
    assert path.read_bytes() == before
