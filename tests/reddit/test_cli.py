"""Only the public subprocess interface is required to discover and use commands."""
import json
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / '.claude/skills/reddit/scripts/reddit.py'


def run(*args):
    return subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True)


def test_help_and_errors_are_self_describing_without_aside():
    result = run('--help')
    assert result.returncode == 0 and 'comments' in result.stdout and 'doctor' in result.stdout
    result = run('about', 'python', '--json')
    assert result.returncode == 2
    assert 'r/' in json.loads(result.stdout)['fix']
    result = run('sub', 'r/python', '--sort', 'hot', '--since', '2026-01-01')
    assert result.returncode == 2 and 'new' in json.loads(result.stdout)['message']


def test_schema_is_one_offline_document_with_nullable_counts():
    result = run('schema', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    schema = json.loads(result.stdout)['schema']
    assert 'null' in schema['Post']['properties']['score']['type']
    assert schema['Comment']['properties']['parent']['type'] == 'string'


def configure(monkeypatch, tmp_path, bodies):
    source = tmp_path / 'responses.json'
    source.write_text(json.dumps(bodies))
    log = tmp_path / 'requests.ndjson'
    monkeypatch.setenv('REDDIT_ASIDE_BIN', str(Path(__file__).with_name('fake_cli.py')))
    monkeypatch.setenv('REDDIT_CLI_RESPONSES', str(source))
    monkeypatch.setenv('REDDIT_FAKE_LOG', str(log))
    return log


def listing(ids, after=None, kind='t3'):
    return {'kind': 'Listing', 'data': {'modhash': 'synthetic', 'after': after, 'children': [
        {'kind': kind, 'data': {'id': name, 'name': kind + '_' + name, 'title': 'Synthetic post', 'subreddit': 'example', 'author': 'synthetic'}} for name in ids]}}


def test_listing_continuation_drains_cache_then_uses_server_after(monkeypatch, tmp_path):
    import shlex
    log = configure(monkeypatch, tmp_path, {'/r/example/new.json': [
        {'body': listing(['a', 'b', 'c'], 't3_c')}, {'body': listing(['c', 'd'])}]})
    first = run('sub', 'r/example', '--sort', 'new', '--limit', '2', '--json')
    assert first.returncode == 0, first.stdout + first.stderr
    body = json.loads(first.stdout)
    assert [item['fullname'] for item in body['results']] == ['t3_a', 't3_b']
    next_args = shlex.split(body['next'])[2:] + ['--limit', '2', '--json']
    second = run(*next_args)
    assert second.returncode == 0, second.stdout + second.stderr
    assert [item['fullname'] for item in json.loads(second.stdout)['results']] == ['t3_c', 't3_d']
    requests = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(requests) == 2 and requests[1]['query']['after'] == 't3_c'


def test_thread_opens_once_and_continues_without_a_request(monkeypatch, tmp_path):
    import shlex
    comments = [{'kind': 't1', 'data': {'id': name, 'name': 't1_' + name, 'parent_id': 't3_post', 'link_id': 't3_post', 'body': 'Reply', 'author': 'synthetic', 'replies': ''}} for name in ('a', 'b', 'c')]
    pair = [listing(['post']), {'kind': 'Listing', 'data': {'children': comments}}]
    log = configure(monkeypatch, tmp_path, {'/comments/post.json': {'body': pair}})
    result = run('post', 'post', '--limit', '1', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    first = json.loads(result.stdout)
    assert first['requests'] == 1 and len(first['results']) == 2
    second = run(*shlex.split(first['next'])[2:], '--limit', '1', '--json')
    assert second.returncode == 0, second.stdout + second.stderr
    assert json.loads(second.stdout)['requests'] == 0
    assert len(log.read_text().splitlines()) == 1


def test_search_retries_empty_once_and_output_rerun_is_local(monkeypatch, tmp_path):
    log = configure(monkeypatch, tmp_path, {'/search.json': [{'body': listing([])}, {'body': listing(['a'])}]})
    output = tmp_path / 'saved.ndjson'
    first = run('search', 'synthetic', '--out', str(output), '--json')
    assert first.returncode == 0, first.stdout + first.stderr
    assert json.loads(first.stdout)['count'] == 1
    second = run('search', 'synthetic', '--out', str(output), '--json')
    assert second.returncode == 0 and json.loads(second.stdout)['already_complete']
    assert len(log.read_text().splitlines()) == 2


def test_thread_output_recovers_progress_after_cache_loss(monkeypatch, tmp_path):
    import shutil
    comments = [{'kind': 't1', 'data': {'id': name, 'name': 't1_' + name, 'parent_id': 't3_post', 'link_id': 't3_post', 'body': 'Reply', 'replies': ''}} for name in ('a', 'b', 'c')]
    pair = [listing(['post']), {'kind': 'Listing', 'data': {'children': comments}}]
    log = configure(monkeypatch, tmp_path, {'/comments/post.json': {'body': pair}})
    output = tmp_path / 'thread.ndjson'
    first = run('post', 'post', '--limit', '1', '--out', str(output), '--json')
    assert first.returncode == 0, first.stdout + first.stderr
    shutil.rmtree(tmp_path / 'reddit' / 'threads')
    second = run('post', 'post', '--out', str(output), '--json')
    assert second.returncode == 0, second.stdout + second.stderr
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert {record['fullname'] for record in records if 'fullname' in record} == {'t3_post', 't1_a', 't1_b', 't1_c'}
    assert len(log.read_text().splitlines()) == 1


def test_date_window_compares_instants_across_timezones():
    from reddit_skill.reddit import parser, validate
    args = parser().parse_args(['sub', 'r/example', '--since', '2026-01-01T00:00:00+09:00', '--until', '2025-12-31T20:00:00Z'])
    validate(args)
    assert args.sort == 'new'


def test_logged_in_thread_file_carries_captured_account(monkeypatch, tmp_path):
    pair = [listing(['post']), {'kind': 'Listing', 'data': {'children': []}}]
    configure(monkeypatch, tmp_path, {'/api/me.json': {'body': {'kind': 't2', 'data': {'name': 'synthetic'}}}, '/comments/post.json': {'body': pair}})
    assert run('doctor').returncode == 0
    output = tmp_path / 'thread.ndjson'
    result = run('post', 'post', '--out', str(output), '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(output.read_text().splitlines()[0])['account'] == 'synthetic'


def test_unreached_empty_date_window_is_partial_not_confirmed_empty(monkeypatch, tmp_path):
    page = listing(['a'])
    page['data']['children'][0]['data']['created_utc'] = 1767225600
    configure(monkeypatch, tmp_path, {'/r/example/new.json': {'body': page}})
    result = run('sub', 'r/example', '--since', '2000-01-01', '--until', '2001-01-01', '--json')
    assert result.returncode == 8, result.stdout + result.stderr
    assert json.loads(result.stdout)['stop_reason'] == 'exhausted'


def test_thread_cursor_with_missing_state_does_not_silently_refetch(monkeypatch, tmp_path):
    import shlex
    import shutil
    comments = [{'kind': 't1', 'data': {'id': name, 'name': 't1_' + name, 'parent_id': 't3_post', 'body': 'Reply', 'replies': ''}} for name in ('a', 'b')]
    configure(monkeypatch, tmp_path, {'/comments/post.json': {'body': [listing(['post']), {'kind': 'Listing', 'data': {'children': comments}}]}})
    first = json.loads(run('post', 'post', '--limit', '1', '--json').stdout)
    shutil.rmtree(tmp_path / 'reddit' / 'threads')
    result = run(*shlex.split(first['next'])[2:], '--json')
    assert result.returncode == 2, result.stdout


def test_unwritable_thread_cache_is_a_single_json_error(monkeypatch, tmp_path):
    occupied = tmp_path / 'occupied'
    occupied.write_text('not a directory')
    monkeypatch.setenv('REDDIT_HOME', str(occupied))
    result = run('comments', 'post', '--json')
    assert result.returncode == 8 and json.loads(result.stdout)['error'] == 8
    assert 'Traceback' not in result.stderr


def test_thread_text_header_counts_new_comments_and_uses_readable_capture_time(monkeypatch, tmp_path):
    comments = [{'kind': 't1', 'data': {'id': 'a', 'name': 't1_a', 'parent_id': 't3_post', 'body': 'Reply', 'replies': ''}}]
    configure(monkeypatch, tmp_path, {'/comments/post.json': {'body': [listing(['post']), {'kind': 'Listing', 'data': {'children': comments}}]}})
    result = run('post', 'post', '--limit', '1')
    assert result.returncode == 0
    header = result.stdout.splitlines()[0]
    assert '1 comments shown' in header
    assert 'fetched=' in header and 'T' in header.split('fetched=', 1)[1]
