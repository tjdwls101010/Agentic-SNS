import json
import pytest

from .test_cli import run_cli


def test_home_reuses_ssr_and_continuation_keeps_tail(fake_aside):
    first = run_cli('home', '--limit', '3', '--json')
    assert first.returncode == 0, first.stdout + first.stderr
    result = json.loads(first.stdout)
    assert [p['id'] for p in result['results']] == ['1', '2', '3']
    assert result['budget']['used'] == 1
    second = run_cli('home', '--limit', '3', '--after', str(result['next_handle']), '--json')
    assert second.returncode == 0, second.stdout + second.stderr
    continuation = json.loads(second.stdout)
    assert [p['id'] for p in continuation['results']] == ['4', '5', '6']
    assert continuation['budget']['used'] == 2


def test_following_feed_does_not_reuse_for_you_ssr(fake_aside):
    result = run_cli('home', '--feed', 'following', '--limit', '3', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    calls = [json.loads(line) for line in fake_aside.read_text().splitlines()]
    assert len(calls) == 2
    assert calls[-1]['variables']['variant'] == 'following'
    assert calls[-1]['variables']['data']['pagination_source'] == 'text_post_feed_following'


def test_profile_uses_matching_ssr_cursor_then_direct_and_about_zero_is_valid(fake_aside):
    user = run_cli('user', '@fixture_user', '--limit', '6', '--json')
    assert user.returncode == 0, user.stdout + user.stderr
    body = json.loads(user.stdout)
    assert [p['id'] for p in body['results']] == ['1', '2', '3', '4', '5', '6']
    about = run_cli('about', '@fixture_user', '--json')
    assert about.returncode == 0, about.stdout + about.stderr
    assert json.loads(about.stdout)['results'][0]['counts']['following'] == 0


def test_about_output_file_stores_the_actual_card(fake_aside, tmp_path):
    path = tmp_path / 'about.ndjson'
    result = run_cli('about', '@fixture_user', '--out', str(path), '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    assert path.exists()
    assert json.loads(path.read_text().splitlines()[1])['counts']['following'] == 0


def test_null_ssr_profile_uses_verified_profile_query(fake_aside, tmp_path, monkeypatch):
    import os
    from pathlib import Path
    source = Path(os.environ['THREADS_FIXTURES'])
    rows = [json.loads(line) for line in source.read_text().splitlines()]
    for row in rows:
        if row['key'] == '/@fixture_user':
            body = row['envelope']['body']
            profile = {'pk': '42', 'username': 'fixture_user', 'full_name': 'Synthetic Person', 'follower_count': 1000}
            row['envelope']['body'] = body.replace(json.dumps({'user': profile}), json.dumps({'user': None}))
    rows.append({'key': 'BarcelonaProfilePageDirectQuery', 'envelope': {'status': 200,
        'url': 'https://www.threads.com/graphql/query', 'body': json.dumps({'data': {'user': profile}})}})
    fixture = tmp_path / 'null-profile.ndjson'
    fixture.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    monkeypatch.setenv('THREADS_FIXTURES', str(fixture))
    result = run_cli('about', '@fixture_user', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)['budget']['used'] == 3


@pytest.mark.parametrize('tab', ['replies', 'reposts', 'media'])
def test_private_tabs_are_unavailable_even_when_profile_ssr_is_null(fake_aside, tmp_path, monkeypatch, tab):
    import os
    from pathlib import Path
    rows = [json.loads(line) for line in Path(os.environ['THREADS_FIXTURES']).read_text().splitlines()]
    profile = {'pk': '42', 'username': 'fixture_user', 'full_name': 'Synthetic Person', 'follower_count': 1000}
    for row in rows:
        if row['key'] == '/@fixture_user':
            row['envelope']['body'] = row['envelope']['body'].replace(json.dumps({'user': profile}), json.dumps({'user': None}))
    for operation, data in [('BarcelonaProfilePageDirectQuery', {'user': profile | {'text_post_app_is_private': True, 'friendship_status': {'following': False}}}),
                            ('BarcelonaProfile' + tab.capitalize() + 'TabDirectQuery', {'mediaData': {'edges': [], 'page_info': {'has_next_page': False}}})]:
        rows.append({'key': operation, 'envelope': {'status': 200, 'url': 'https://www.threads.com/graphql/query', 'body': json.dumps({'data': data})}})
    path = tmp_path / 'private.ndjson'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    monkeypatch.setenv('THREADS_FIXTURES', str(path))
    result = run_cli('user', '@fixture_user', '--tab', tab, '--json')
    assert result.returncode == 9, result.stdout + result.stderr


def test_incompatible_ssr_cursor_restarts_direct_once_and_deduplicates(fake_aside, tmp_path, monkeypatch):
    import os
    from pathlib import Path
    from .test_models import raw_post
    rows = [json.loads(line) for line in Path(os.environ['THREADS_FIXTURES']).read_text().splitlines()]
    for row in rows:
        if row['key'] == 'BarcelonaProfileThreadsTabDirectQuery:after':
            row['envelope']['body'] = json.dumps({'data': None, 'errors': [{'message': 'execution error', 'severity': 'CRITICAL'}]})
        elif row['key'] == 'BarcelonaProfileThreadsTabDirectQuery':
            row['envelope']['body'] = json.dumps({'data': {'mediaData': {'edges': [{'node': {'thread_items': [{'post': raw_post(str(i))}]}} for i in range(1, 8)],
                                                                      'page_info': {'has_next_page': True, 'end_cursor': 'B'}}}})
    path = tmp_path / 'cursor-fallback.ndjson'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    monkeypatch.setenv('THREADS_FIXTURES', str(path))
    result = run_cli('user', '@fixture_user', '--limit', '6', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    body = json.loads(result.stdout)
    assert [p['id'] for p in body['results']] == ['1', '2', '3', '4', '5', '6']
    assert body['budget']['used'] == 3
