import json
import os
from pathlib import Path

import pytest

from .test_cli import run_cli


@pytest.fixture
def collections(fake_aside, tmp_path, monkeypatch):
    rows = [json.loads(line) for line in Path(os.environ['THREADS_FIXTURES']).read_text().splitlines()]
    tab = json.loads(next(r['envelope']['body'] for r in rows if r['key'] == 'BarcelonaProfileThreadsTabDirectQuery'))['data']['mediaData']
    search = {'edges': [{'node': {'thread': edge['node']}} for edge in tab['edges']], 'page_info': tab['page_info']}
    for key, payload in [
        ('BarcelonaSearchResultsQuery', {'data': {'searchResults': search}}),
        ('useBarcelonaAccountSearchGraphQLDataSourceQuery', {'data': {'xdt_api__v1__users__search_connection': {'edges': [
            {'node': {'pk': str(i), 'username': 'fixture_user'}} for i in (42, 43, 44)]}}, 'errors': [{'message': 'field_exception', 'path': ['users', 4]}]}),
        ('BarcelonaLikedPageViewerQuery', {'data': {'xdt_text_app_viewer': {'liked_media': tab}}}),
        ('BarcelonaSavedPageViewerQuery', {'data': {'xdt_text_app_viewer': {}}}),
    ]:
        rows.append({'key': key, 'envelope': {'status': 200, 'url': 'https://www.threads.com/graphql/query', 'body': json.dumps(payload)}})
    path = tmp_path / 'collections.ndjson'
    path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
    monkeypatch.setenv('THREADS_FIXTURES', str(path))
    return fake_aside


@pytest.mark.parametrize('options,surface,recent', [([], 'default', 0), (['--tag'], 'tags', 0), (['--sort', 'recent'], 'default', 1)])
def test_post_search_surface_and_sort_are_query_variables(collections, options, surface, recent):
    result = run_cli('search', 'python', '--limit', '3', '--json', *options)
    assert result.returncode == 0, result.stdout + result.stderr
    query = json.loads(collections.read_text().splitlines()[-1])['variables']
    assert (query['search_surface'], query['recent']) == (surface, recent)


def test_account_search_accepts_partial_optional_fields_and_is_one_batch(collections):
    result = run_cli('search', 'python', '--type', 'users', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['stop_reason'] == 'not_paginable'


def test_liked_pending_tail_can_resume_but_never_requests_a_second_server_batch(collections):
    result = json.loads(run_cli('me', 'liked', '--limit', '3', '--json').stdout)
    resumed = run_cli('me', 'liked', '--after', str(result['next_handle']), '--limit', '10', '--json')
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    body = json.loads(resumed.stdout)
    assert [p['id'] for p in body['results']] == ['4']
    assert body['budget']['used'] == 1 and body['stop_reason'] == 'not_paginable'


def test_unknown_saved_shape_is_not_claimed_to_be_empty(collections):
    result = run_cli('me', 'saved', '--json')
    assert result.returncode == 6
    assert json.loads(result.stdout)['error'] == 'envelope_drift'


def test_date_window_file_completion_is_zero_request_on_repeat(fake_aside, tmp_path):
    path = tmp_path / 'window.ndjson'
    first = run_cli('user', '@fixture_user', '--since', '2027-01-01', '--out', str(path), '--json')
    body = json.loads(first.stdout)
    assert body['stop_reason'] == 'window_reached', body
    second = run_cli('user', '@fixture_user', '--since', '2027-01-01', '--out', str(path), '--json')
    assert second.returncode == 0, second.stdout + second.stderr
    assert json.loads(second.stdout)['budget']['used'] == 0


def test_search_users_rejects_post_only_options_before_network(fake_aside):
    result = run_cli('search', 'python', '--type', 'users', '--tag', '--json')
    assert result.returncode == 2
    assert not fake_aside.exists()


def test_account_search_more_command_is_executable(collections):
    import shlex
    import subprocess
    first = json.loads(run_cli('search', 'python', '--type', 'users', '--limit', '1', '--json').stdout)
    next_page = subprocess.run(shlex.split(first['next']), capture_output=True, text=True)
    assert next_page.returncode == 0, next_page.stdout + next_page.stderr
    assert [u['id'] for u in json.loads(next_page.stdout)['results']] == ['43', '44']
