import json
from pathlib import Path

from .test_cli import run_cli


def test_refresh_keeps_unobserved_operations_and_never_saves_instance_variables(fake_aside, tmp_path, monkeypatch):
    import os
    rows = [json.loads(line) for line in Path(os.environ['THREADS_FIXTURES']).read_text().splitlines()]
    for row in list(rows):
        if row['key'] == '/@fixture_user':
            rows.append(dict(row, key='/@fixture_viewer'))
    fixture = tmp_path / 'refresh.ndjson'
    fixture.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    monkeypatch.setenv('THREADS_FIXTURES', str(fixture))
    result = run_cli('refresh', '--json')
    assert result.returncode == 8, result.stdout + result.stderr
    body = json.loads(result.stdout)
    assert 'BarcelonaProfileThreadsTabDirectQuery' in body['updated']
    assert 'BarcelonaSavedPageViewerQuery' in body['missing']
    saved = json.loads((Path(os.environ['THREADS_HOME']) / 'registry.json').read_text())
    assert 'synthetic-csrf' not in json.dumps(saved)
    assert saved['operations']['BarcelonaProfileThreadsTabDirectQuery']['variables_template']['userID'] == '<pk>'
    assert saved['operations']['BarcelonaProfileThreadsTabDirectQuery']['doc_id'] == '1001'


def test_capture_requires_its_seed_before_spending_a_request(fake_aside):
    result = run_cli('refresh', '--capture', '--json')
    assert result.returncode == 2
    assert not fake_aside.exists()


def test_refresh_only_checks_that_a_post_route_still_decodes(fake_aside, tmp_path, monkeypatch):
    import os
    rows = [json.loads(line) for line in Path(os.environ['THREADS_FIXTURES']).read_text().splitlines()]
    rows += [dict(row, key='/@fixture_viewer') for row in rows if row['key'] == '/@fixture_user']
    fixture = tmp_path / 'refresh.ndjson'
    fixture.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    monkeypatch.setenv('THREADS_FIXTURES', str(fixture))
    body = json.loads(run_cli('refresh', '--post', 'https://www.threads.com/@fixture_user/post/FIX_2', '--json').stdout)
    assert body['post_route'] == 'decoded'
    assert 'post_route' not in body['failed']
    assert not [name for name in [*body['missing'], *body['updated']] if name.startswith('BarcelonaPostPage')]
    broken = [dict(row, envelope=dict(row['envelope'], body=row['envelope']['body'].replace('direct_replies', 'x')))
              if row['key'].startswith('/@fixture_user/post/') else row for row in rows]
    fixture.write_text(''.join(json.dumps(row) + '\n' for row in broken))
    result = run_cli('refresh', '--post', 'https://www.threads.com/@fixture_user/post/FIX_2', '--json')
    assert result.returncode == 8
    assert json.loads(result.stdout)['post_route'] == 'failed'
