import json

from facebook.collect import OutFile

CONTEXT = dict(command='profile', target='4', sort='recent',
               window={'since': None, 'until': None}, account_id='100')


def test_interrupted_page_is_discarded_and_replayed_without_loss_or_duplicates(tmp_path):
    path = tmp_path / 'posts.ndjson'
    out = OutFile(path, CONTEXT)
    out.commit([{'id': '1', 'text': 'first'}], 'next', None)
    out.close()
    with path.open('ab') as stream:
        stream.write(b'{"id":"2","text":"uncommitted"}\n{"id":')
    out = OutFile(path, CONTEXT)
    assert out.cursor == 'next'
    assert out.ids == {'1'}
    out.commit([{'id': '1', 'text': 'duplicate'}, {'id': '2', 'text': 'second'}],
               {'exhausted': True}, 'exhausted')
    out.close()
    out = OutFile(path, CONTEXT)
    assert out.complete
    assert out.count == 2
    out.close()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r['id'] for r in rows if 'id' in r] == ['1', '2']
    assert rows[0]['kind'] == 'header'


def test_wrong_context_never_truncates_an_existing_file(tmp_path):
    import pytest
    from facebook.errors import FacebookError
    path = tmp_path / 'posts.ndjson'
    out = OutFile(path, CONTEXT)
    out.commit([{'id': '1'}], 'next', None)
    out.close()
    before = path.read_bytes()
    with pytest.raises(FacebookError) as error:
        OutFile(path, dict(CONTEXT, target='5'))
    assert error.value.code == 2
    assert path.read_bytes() == before


def test_cursor_ids_increase_and_context_is_validated():
    import pytest
    from facebook.errors import FacebookError
    from facebook.cursors import CursorStore
    store = CursorStore()
    first = store.save(CONTEXT, 'long-cursor', pending=[{'id': '1'}])
    second = store.save(CONTEXT, 'next')
    assert second > first
    assert store.load(first, CONTEXT)['pending'] == [{'id': '1'}]
    with pytest.raises(FacebookError):
        store.load(first, dict(CONTEXT, sort='top'))
    with pytest.raises(FacebookError):
        store.load('../blocked', CONTEXT)


def test_json_emits_one_document_and_partial_exit_code(tmp_path):
    # Without --limit the read budget is 25 requests: the home page plus 24 feed pages, then the 25th page stops.
    import subprocess
    import sys
    from test_cli import CLI, feed_page, fake_env, login
    pages = [feed_page(['p%d' % i], 'c%d' % i) for i in range(24)]
    # Account pacing keeps 1-2 s between requests, so 25 requests need more than run_cli's timeout.
    result = subprocess.run([sys.executable, str(CLI), 'feed', '--json'], capture_output=True, text=True,
                            env=fake_env(tmp_path, [login(), *pages]), timeout=120)
    assert result.returncode == 8, result.stdout
    printed = json.loads(result.stdout)
    assert [r['id'] for r in printed['results']] == ['p%d' % i for i in range(24)]
    assert printed['stop_reason'] == 'budget'
    assert printed['ok'] is False
    assert printed['request_count'] == 25


def test_honest_empty_result_and_blocked_partial_have_distinct_exits(tmp_path):
    from test_cli import feed_page, fake_env, login, run_cli
    empty = run_cli('feed', '--json', env=fake_env(tmp_path, [login(), feed_page([])]))
    assert empty.returncode == 7, empty.stdout
    assert json.loads(empty.stdout)['error'] == 'empty'
    limited = {'status': 429, 'url': 'https://www.facebook.com/', 'body': '{}'}
    blocked = run_cli('feed', '--json', env=fake_env(tmp_path, [login(), feed_page(['p1'], 'next'), limited]))
    assert blocked.returncode == 5, blocked.stdout
    assert json.loads(blocked.stdout)['stop_reason'] == 'blocked'
    assert [r['id'] for r in json.loads(blocked.stdout)['results']] == ['p1']


def test_page_limit_on_last_full_page_is_already_complete(tmp_path):
    path = tmp_path / 'last.ndjson'
    output = OutFile(path, CONTEXT)
    output.commit([{'id': '1'}, {'id': '2'}], {'exhausted': True}, 'limit_reached')
    output.close()
    output = OutFile(path, CONTEXT)
    assert output.complete
    output.close()


def test_page_entity_is_a_record_not_a_page_commit_marker(tmp_path):
    path = tmp_path / 'entities.ndjson'
    output = OutFile(path, CONTEXT)
    output.commit([{'id': '123', 'kind': 'page', 'name': 'Example'}], {'exhausted': True}, 'exhausted')
    output.close()
    output = OutFile(path, CONTEXT)
    assert output.count == 1
    assert output.ids == {'123'}
    output.close()


def test_non_object_header_is_a_safe_argument_error_without_modifying_file(tmp_path):
    import pytest
    from facebook.errors import FacebookError
    path = tmp_path / 'broken.ndjson'
    path.write_text('[]\n')
    with pytest.raises(FacebookError) as error:
        OutFile(path, CONTEXT)
    assert error.value.code == 2
    assert path.read_text() == '[]\n'


def test_public_read_stop_reasons_use_the_documented_vocabulary(tmp_path):
    from test_cli import comment_node, comment_page, envelope, feed_page, fake_env, login, run_cli
    path = str(tmp_path / 'done.ndjson')
    assert run_cli('feed', '--out', path, env=fake_env(tmp_path, [login(), feed_page(['p1'])])).returncode == 0
    done = run_cli('feed', '--out', path, '--json', env=fake_env(tmp_path, [login()]))
    assert json.loads(done.stdout)['stop_reason'] == 'exhausted'
    replies = json.loads(comment_page([comment_node('r1', 1, 'c1')], 'replies_connection')['body'])
    replies['data']['node']['replies_connection']['page_info'] = {'has_next_page': True, 'end_cursor': 'more'}
    limited = run_cli('comments', 'https://www.facebook.com/zuck/posts/123', '--replies', '--json',
                      env=fake_env(tmp_path, [login(), envelope('"storyID":"story"'),
                                              envelope(json.dumps({'data': {'node': {'feedback': {'id': 'f'}}}})),
                                              comment_page([comment_node('c1')]), envelope(json.dumps(replies))]))
    assert limited.returncode == 8, limited.stdout
    assert json.loads(limited.stdout)['stop_reason'] == 'query_failure'
