import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

CLI = Path(__file__).resolve().parents[2] / '.claude/skills/facebook/scripts/facebook.py'


def run_cli(*args, env=None):
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True,
                          env=env, timeout=30)


@pytest.mark.parametrize('args', [
    ['feed', '--limit', '0'], ['comments'], ['feed', '--since', 'bad'],
    ['feed', '--since', '2026-09-05', '--until', '2026-09-01'],
    ['about', 'zuck', '--since', '2026-01-01'],
    ['post', 'https://facebook.com/zuck/posts/123', '--after', '1'],
    ['profile', 'zuck', '--sort', 'top'],
    ['search', 'hi', '--type', 'people', '--since', '2026-01-01'],
    ['feed', '--out', '/tmp/x', '--after', '1'],
])
def test_invalid_arguments_emit_one_json_error(args):
    completed = run_cli(*args)
    assert completed.returncode == 2
    error = json.loads(completed.stdout)
    assert error['ok'] is False
    assert error['error'] == 2
    assert error['message']


def test_help_explains_commands_and_resume():
    completed = run_cli('comments', '--help')
    assert completed.returncode == 0
    assert '--replies' in completed.stdout
    assert '--after' in completed.stdout
    assert 'parent' in completed.stdout.lower()


def fake_env(tmp_path, responses):
    path = tmp_path / 'responses.json'
    path.write_text(json.dumps(responses))
    return {**os.environ, 'FACEBOOK_ASIDE_BIN': str(CLI.parents[4] / 'tests/facebook/fake_aside/aside'),
            'FAKE_ASIDE_RESPONSES': str(path), 'FACEBOOK_HOME': str(tmp_path / 'state')}


def envelope(body):
    return {'status': 200, 'url': 'https://www.facebook.com/', 'body': body}


def login():
    return envelope('"USER_ID":"100" "DTSGInitialData",[],{"token":"synthetic"} '
                    '"LSD",[],{"token":"synthetic"} "__spin_r":123')


def feed_page(ids, cursor=None):
    return envelope(json.dumps({'data': {'viewer': {'news_feed': {
        'edges': [{'node': {'feedback': {'id': ident}, 'message': {'text': 'Synthetic ' + ident}}} for ident in ids],
        'page_info': {'has_next_page': cursor is not None, 'end_cursor': cursor}}}}}))


def test_feed_midpage_resume_has_no_loss(tmp_path):
    env = fake_env(tmp_path, [login(), feed_page(['p1', 'p2', 'p3'])])
    first = run_cli('feed', '--limit', '1', '--json', env=env)
    assert first.returncode == 0, first.stderr + first.stdout
    result = json.loads(first.stdout)
    assert [r['id'] for r in result['results']] == ['p1']
    import shlex
    more = shlex.split(result['next'])[2:]
    env = fake_env(tmp_path, [login()])
    second = run_cli(*more, env=env)
    assert second.returncode == 0, second.stderr + second.stdout
    assert [r['id'] for r in json.loads(second.stdout)['results']] == ['p2']


def post_response():
    return envelope(json.dumps({'data': {'node': {'feedback': {'id': 'post-feedback'},
                                                  'message': {'text': 'Complete synthetic post'}}}}))


def comment_node(ident, depth=0, parent=None):
    return {'id': ident, 'depth': depth, 'author': {'id': 'author', 'name': 'Synthetic'},
            'body': {'text': 'Synthetic comment ' + ident},
            'comment_direct_parent': {'id': parent} if parent else None,
            'feedback': {'id': ident + '-feedback', 'expansion_info': {'expansion_token': ident + '-token'},
                         'replies_fields': {'total_count': 1 if depth == 0 else 0}}}


def comment_page(nodes, key='comments'):
    return envelope(json.dumps({'data': {'node': {key: {'edges': [{'node': n} for n in nodes],
        'page_info': {'has_next_page': False, 'end_cursor': None}}}}}))


def test_comments_limit_precedes_reply_expansion_and_resume_keeps_parent_handles(tmp_path):
    env = fake_env(tmp_path, [login(), envelope('"storyID":"story"'), post_response(),
        comment_page([comment_node('c1'), comment_node('c1'), comment_node('c2')]),
        comment_page([comment_node('r1', 1, 'c1')], 'replies_connection')])
    result = run_cli('comments', 'https://www.facebook.com/zuck/posts/123',
                     '--limit', '1', '--replies', '--json', env=env)
    assert result.returncode == 0, result.stderr + result.stdout
    data = json.loads(result.stdout)
    assert [r['id'] for r in data['results']] == ['c1', 'r1']
    assert '_reply_handle' not in result.stdout
    import shlex
    env = fake_env(tmp_path, [login(), comment_page([comment_node('r2', 1, 'c2')], 'replies_connection')])
    resumed = run_cli(*shlex.split(data['next'])[2:], env=env)
    assert resumed.returncode == 0, resumed.stderr + resumed.stdout
    assert [r['id'] for r in json.loads(resumed.stdout)['results']] == ['c2', 'r2']


def test_post_shows_full_text_and_preserves_it_when_comments_block(tmp_path):
    env = fake_env(tmp_path, [login(), envelope('"storyID":"story"'), post_response(),
                              {'status': 429, 'url': 'https://www.facebook.com/', 'body': '{}'}])
    result = run_cli('post', 'https://www.facebook.com/zuck/posts/123', '--json', env=env)
    assert result.returncode == 5, result.stderr + result.stdout
    data = json.loads(result.stdout)
    assert data['results'][0]['text'] == 'Complete synthetic post'
    assert data['ok'] is False


def test_output_file_commits_full_page_and_resumes_without_requery(tmp_path):
    env = fake_env(tmp_path, [login(), feed_page(['p1', 'p2', 'p3'])])
    path = str(tmp_path / 'posts.ndjson')
    first = run_cli('feed', '--limit', '1', '--out', path, '--json', env=env)
    assert first.returncode == 0, first.stderr + first.stdout
    env = fake_env(tmp_path, [login()])
    second = run_cli('feed', '--limit', '1', '--out', path, '--json', env=env)
    assert second.returncode == 0, second.stderr + second.stdout
    data = json.loads(second.stdout)
    assert data['stop_reason'] == 'exhausted'
    assert data['already_complete'] is True
    assert data['count'] == 3


def test_about_reports_partial_collection_failure_and_stops_on_block(tmp_path):
    section = {'field_section_type': 'directory_bio',
               'profile_fields': {'nodes': [{'title': {'text': 'Synthetic bio'}}]}}
    overview = envelope(json.dumps({'data': {'user': {
        'about_app_sections': {'nodes': [section]},
        'all_collections': {'nodes': [{'id': 'work', 'name': 'Work'}, {'id': 'education', 'name': 'Education'}]}}}}))
    env = fake_env(tmp_path, [login(), overview,
                             {'status': 429, 'url': 'https://www.facebook.com/', 'body': '{}'}])
    result = run_cli('about', '42', '--json', env=env)
    assert result.returncode == 5, result.stderr + result.stdout
    data = json.loads(result.stdout)
    assert data['results'][0]['section'] == 'directory_bio'
    assert data['failed_sections'][0]['section'] == 'Work'


@pytest.mark.parametrize('command,connection,target', [
    ('profile', 'timeline_list_feed_units', '42'), ('group', 'group_feed', '123')])
def test_numeric_targets_skip_resolution_and_keep_window_order(tmp_path, command, connection, target):
    from datetime import datetime
    def story(ident, day):
        return {'feedback': {'id': ident}, 'message': {'text': ident},
                'creation_time': int(datetime.fromisoformat(day).timestamp())}
    page = envelope(json.dumps({'data': {'node': {connection: {
        'edges': [{'node': story('inside', '2026-09-03T12:00:00')},
                  {'node': story('outside', '2026-08-01T12:00:00')}],
        'page_info': {'has_next_page': False, 'end_cursor': None}}}}}))
    env = fake_env(tmp_path, [login(), page])
    result = run_cli(command, target, '--since', '2026-09-01', '--until', '2026-09-05', '--json', env=env)
    assert result.returncode == 0, result.stderr + result.stdout
    assert [r['id'] for r in json.loads(result.stdout)['results']] == ['inside']


def test_search_page_kind_and_context_mismatch(tmp_path):
    page = envelope(json.dumps({'data': {'serpResponse': {'results': {
        'edges': [{'node': {'__typename': 'Page', 'id': ident, 'name': 'Synthetic page',
                            'url': 'https://www.facebook.com/' + ident}} for ident in ('p1', 'p2')],
        'page_info': {'has_next_page': False, 'end_cursor': None}}}}}))
    env = fake_env(tmp_path, [login(), page])
    first = run_cli('search', 'synthetic', '--type', 'pages', '--limit', '1', '--json', env=env)
    assert first.returncode == 0, first.stderr + first.stdout
    data = json.loads(first.stdout)
    assert data['results'][0]['kind'] == 'page'
    import shlex
    args = shlex.split(data['next'])[2:]
    args[args.index('pages')] = 'people'
    env = fake_env(tmp_path, [login()])
    resumed = run_cli(*args, env=env)
    assert resumed.returncode == 2
    assert json.loads(resumed.stdout)['ok'] is False


def test_post_text_output_is_not_clipped_by_chars(tmp_path):
    env = fake_env(tmp_path, [login(), envelope('"storyID":"story"'), post_response(), comment_page([])])
    result = run_cli('post', 'https://www.facebook.com/zuck/posts/123', '--chars', '1', env=env)
    assert result.returncode == 0, result.stderr + result.stdout
    assert 'Complete synthetic post' in result.stdout
    assert 'comments starts from' not in result.stdout


def test_nonempty_connection_with_unreadable_posts_is_failure_not_empty(tmp_path):
    page = envelope(json.dumps({'data': {'viewer': {'news_feed': {
        'edges': [{'node': {'unknown_shape': 'synthetic'}}],
        'page_info': {'has_next_page': False, 'end_cursor': None}}}}}))
    result = run_cli('feed', '--limit', '1', '--json', env=fake_env(tmp_path, [login(), page]))
    assert result.returncode == 6, result.stderr + result.stdout


def test_top_search_preserves_mixed_server_order(tmp_path):
    nodes = [
        {'__typename': 'Group', 'id': 'group-first', 'name': 'Synthetic group', 'url': 'https://www.facebook.com/groups/123/'},
        {'__typename': 'Story', 'feedback': {'id': 'post-second'}, 'message': {'text': 'Synthetic post'}},
    ]
    page = envelope(json.dumps({'data': {'serpResponse': {'results': {
        'edges': [{'node': n} for n in nodes],
        'page_info': {'has_next_page': False, 'end_cursor': None}}}}}))
    result = run_cli('search', 'synthetic', '--type', 'top', '--limit', '2', '--json',
                     env=fake_env(tmp_path, [login(), page]))
    assert result.returncode == 0, result.stderr + result.stdout
    assert [r['id'] for r in json.loads(result.stdout)['results']] == ['group-first', 'post-second']


def test_schema_is_local_and_doctor_checks_login(tmp_path):
    result = run_cli('schema', '--json')
    assert result.returncode == 0, result.stderr + result.stdout
    assert {row['title'] for row in json.loads(result.stdout)['results']} == {
        'Post', 'Comment', 'Entity', 'ProfileField'}
    doctor = run_cli('doctor', '--json', env=fake_env(tmp_path, [login()]))
    assert doctor.returncode == 0, doctor.stderr + doctor.stdout
    assert json.loads(doctor.stdout)['results'][0]['account_id'] == '100'


def test_later_parent_block_keeps_block_exit_after_earlier_reply_failure(tmp_path):
    first_page = json.loads(comment_page([comment_node('c1')])['body'])
    first_page['data']['node']['comments']['page_info'] = {'has_next_page': True, 'end_cursor': 'second'}
    env = fake_env(tmp_path, [login(), envelope('"storyID":"story"'), post_response(),
        envelope(json.dumps(first_page)), envelope('{"errors":[{"message":"synthetic failure"}]}'),
        {'status': 429, 'url': 'https://www.facebook.com/', 'body': '{}'}])
    result = run_cli('comments', 'https://www.facebook.com/zuck/posts/123', '--limit', '2',
                     '--replies', '--json', env=env)
    assert result.returncode == 5, result.stderr + result.stdout
    assert json.loads(result.stdout)['stop_reason'] == 'blocked'


def test_out_limit_is_cumulative_and_satisfied_limit_does_not_query(tmp_path):
    path = str(tmp_path / 'cumulative.ndjson')
    first = run_cli('feed', '--limit', '3', '--out', path, '--json',
                    env=fake_env(tmp_path, [login(), feed_page(['p1', 'p2', 'p3'], 'page2')]))
    assert first.returncode == 0, first.stdout
    second = run_cli('feed', '--limit', '6', '--out', path, '--json',
                     env=fake_env(tmp_path, [login(), feed_page(['p4', 'p5', 'p6'], 'page3')]))
    assert second.returncode == 0, second.stdout
    assert json.loads(second.stdout)['count'] == 6
    third = run_cli('feed', '--limit', '6', '--out', path, '--json',
                    env=fake_env(tmp_path, [login()]))
    assert third.returncode == 0, third.stdout
    assert json.loads(third.stdout)['count'] == 6


def test_post_keeps_deferred_updates_and_incomplete_marker_on_requested_root(tmp_path):
    body = '\n'.join(json.dumps(chunk) for chunk in [
        {'data': {'unrelated': {'feedback': {'id': 'decoy'}, 'message': {'text': 'Wrong post'}},
                  'node': {'feedback': {'id': 'post-feedback'}, 'message': None}}},
        {'path': ['node'], 'data': {'feedback': {'id': 'post-feedback'}, 'message': {'text': 'Deferred full post'}}},
        {'path': ['node', 'message'], 'data': {'text': 'Unsupported partial patch'}},
    ])
    result = run_cli('post', 'https://www.facebook.com/zuck/posts/123', '--json',
                    env=fake_env(tmp_path, [login(), envelope('"storyID":"story"'), envelope(body), comment_page([])]))
    assert result.returncode == 0, result.stdout
    post = json.loads(result.stdout)['results'][0]
    assert post['id'] == 'post-feedback'
    assert post['text'] == 'Deferred full post'
    assert post['incomplete'] is True


def test_failed_reply_at_end_can_retry_without_repeating_shown_records(tmp_path):
    import shlex
    result = run_cli('comments', 'https://www.facebook.com/zuck/posts/123', '--limit', '2', '--replies', '--json',
        env=fake_env(tmp_path, [login(), envelope('"storyID":"story"'), post_response(),
            comment_page([comment_node('c1'), comment_node('c2')]),
            comment_page([comment_node('r1', 1, 'c1')], 'replies_connection'),
            envelope('{"errors":[{"message":"Synthetic failure"}]}')]))
    assert result.returncode == 8, result.stdout
    data = json.loads(result.stdout)
    assert [r['id'] for r in data['results']] == ['c1', 'r1', 'c2']
    assert data.get('next')
    retried = run_cli(*shlex.split(data['next'])[2:], env=fake_env(tmp_path, [
        login(), comment_page([comment_node('r2', 1, 'c2')], 'replies_connection')]))
    assert retried.returncode == 0, retried.stdout
    retry_data = json.loads(retried.stdout)
    assert [r['id'] for r in retry_data['results']] == ['r2']
    assert not retry_data.get('next')


def test_reply_batch_limit_is_reported_without_retrying_first_batch_forever(tmp_path):
    replies = json.loads(comment_page([comment_node('r1', 1, 'c1')], 'replies_connection')['body'])
    replies['data']['node']['replies_connection']['page_info'] = {'has_next_page': True, 'end_cursor': 'reply2'}
    result = run_cli('comments', 'https://www.facebook.com/zuck/posts/123', '--limit', '1', '--replies', '--json',
        env=fake_env(tmp_path, [login(), envelope('"storyID":"story"'), post_response(),
                               comment_page([comment_node('c1')]), envelope(json.dumps(replies))]))
    data = json.loads(result.stdout)
    assert data['stop_reason'] == 'query_failure'
    assert data['replies_incomplete'][0]['reason'] == 'batch_limit'
    assert data['replies_incomplete'][0]['retryable'] is False
    assert not data.get('next')


@pytest.mark.parametrize('deferred', [False, True])
def test_top_search_nodes_and_deferred_result_positions_keep_server_order(tmp_path, deferred):
    group = {'__typename': 'Group', 'id': 'first-group', 'name': 'Synthetic group',
             'url': 'https://www.facebook.com/groups/123/'}
    post = {'__typename': 'Story', 'feedback': {'id': 'second-post'}, 'message': {'text': 'Synthetic post'}}
    connection = {'nodes': [group, post], 'page_info': {'has_next_page': False, 'end_cursor': None}}
    if deferred:
        connection['nodes'] = [{}]
        chunks = [
            {'data': {'serpResponse': {'results': connection}}},
            {'path': ['serpResponse', 'results', 'nodes', 1], 'data': post},
            {'path': ['serpResponse', 'results', 'nodes', 0], 'data': group},
        ]
    else:
        chunks = [{'data': {'serpResponse': {'results': connection}}}]
    result = run_cli('search', 'synthetic', '--type', 'top', '--limit', '2', '--json',
                    env=fake_env(tmp_path, [login(), envelope('\n'.join(map(json.dumps, chunks)))]))
    assert result.returncode == 0, result.stdout
    assert [r['id'] for r in json.loads(result.stdout)['results']] == ['first-group', 'second-post']


def test_comments_out_limit_counts_saved_parents_not_replies(tmp_path):
    path = str(tmp_path / 'comments.ndjson')
    url = 'https://www.facebook.com/zuck/posts/123'
    page = json.loads(comment_page([comment_node('c1')])['body'])
    page['data']['node']['comments']['page_info'] = {'has_next_page': True, 'end_cursor': 'page2'}
    first = run_cli('comments', url, '--replies', '--limit', '1', '--out', path, '--json',
        env=fake_env(tmp_path, [login(), envelope('"storyID":"story"'), post_response(),
            envelope(json.dumps(page)), comment_page([comment_node('r1', 1, 'c1')], 'replies_connection')]))
    assert first.returncode == 0, first.stdout
    page = json.loads(comment_page([comment_node('c2')])['body'])
    page['data']['node']['comments']['page_info'] = {'has_next_page': True, 'end_cursor': 'page3'}
    second = run_cli('comments', url, '--replies', '--limit', '2', '--out', path, '--json',
        env=fake_env(tmp_path, [login(), envelope(json.dumps(page)),
            comment_page([comment_node('r2', 1, 'c2')], 'replies_connection')]))
    assert second.returncode == 0, second.stdout
    assert json.loads(second.stdout)['count'] == 4
    assert [r['id'] for r in json.loads(second.stdout)['results']] == ['c2', 'r2']
    third = run_cli('comments', url, '--replies', '--limit', '2', '--out', path, '--json',
                    env=fake_env(tmp_path, [login()]))
    assert third.returncode == 0, third.stdout
    assert json.loads(third.stdout)['request_count'] == 1


def test_reply_retry_and_unshown_parent_tail_resume_independently(tmp_path):
    import shlex
    first = run_cli('comments', 'https://www.facebook.com/zuck/posts/123', '--limit', '1', '--replies', '--json',
        env=fake_env(tmp_path, [login(), envelope('"storyID":"story"'), post_response(),
            comment_page([comment_node('c1'), comment_node('c2')]),
            envelope('{"errors":[{"message":"Synthetic failure"}]}')]))
    assert first.returncode == 8, first.stdout
    data = json.loads(first.stdout)
    assert [r['id'] for r in data['results']] == ['c1']
    second = run_cli(*shlex.split(data['next'])[2:], env=fake_env(tmp_path, [
        login(), comment_page([comment_node('r1', 1, 'c1')], 'replies_connection'),
        comment_page([comment_node('r2', 1, 'c2')], 'replies_connection')]))
    assert second.returncode == 0, second.stdout
    assert [r['id'] for r in json.loads(second.stdout)['results']] == ['r1', 'c2', 'r2']
    assert not json.loads(second.stdout).get('next')


def test_post_continues_comments_with_the_measured_compatible_root_cursor(tmp_path):
    import shlex
    url = 'https://www.facebook.com/zuck/posts/123'
    root = json.loads(comment_page([comment_node('c1')])['body'])
    root['data']['node']['comments']['page_info'] = {'has_next_page': True, 'end_cursor': 'page2'}
    first = run_cli('post', url, '--json', env=fake_env(tmp_path, [login(),
        envelope('"storyID":"story"'), post_response(), envelope(json.dumps(root))]))
    assert first.returncode == 0
    data = json.loads(first.stdout)
    assert '--after' in data['next']
    command = shlex.split(data['next'])
    next_page = run_cli(*command[2:], env=fake_env(tmp_path, [login(), comment_page([comment_node('c2')])]))
    assert next_page.returncode == 0, next_page.stdout
    assert [r['id'] for r in json.loads(next_page.stdout)['results']] == ['c2']


def test_verbose_keeps_one_stdout_document_and_only_safe_diagnostic_metadata(tmp_path):
    result = run_cli('feed', '--limit', '1', '--json', '--verbose',
                     env=fake_env(tmp_path, [login(), feed_page(['p1'])]))
    assert result.returncode == 0
    assert json.loads(result.stdout)['results'][0]['id'] == 'p1'
    diagnostics = [json.loads(line) for line in result.stderr.splitlines()]
    assert [r['stage'] for r in diagnostics] == ['request', 'request']
    assert 'fb_dtsg' not in result.stderr and 'ARGS' not in result.stderr


def test_refresh_does_not_report_success_when_no_queries_were_found(tmp_path):
    result = run_cli('refresh', '--json', env=fake_env(tmp_path, [login(),
        *[envelope('<html><body>No eager query scripts</body></html>') for _ in range(5)]]))
    assert result.returncode == 8
    data = json.loads(result.stdout)
    assert data['ok'] is False and data['updated'] == []
    assert data['stop_reason'] == 'query_failure'


def test_empty_feed_page_with_a_next_cursor_continues_to_real_results(tmp_path):
    result = run_cli('feed', '--limit', '1', '--json', env=fake_env(tmp_path,
                     [login(), feed_page([], 'next'), feed_page(['p1'])]))
    assert result.returncode == 0, result.stdout
    assert [r['id'] for r in json.loads(result.stdout)['results']] == ['p1']


def test_parent_fragments_merge_before_limit_and_reply_expansion(tmp_path):
    first = comment_node('c1')
    first['body'] = None
    first['feedback']['replies_fields']['total_count'] = None
    result = run_cli('comments', 'https://www.facebook.com/zuck/posts/123', '--limit', '1', '--replies', '--json',
        env=fake_env(tmp_path, [login(), envelope('"storyID":"story"'), post_response(),
            comment_page([first, comment_node('c1')]), comment_page([comment_node('r1', 1, 'c1')], 'replies_connection')]))
    assert result.returncode == 0, result.stdout
    rows = json.loads(result.stdout)['results']
    assert [r['id'] for r in rows] == ['c1', 'r1']
    assert rows[0]['text'] == 'Synthetic comment c1'
