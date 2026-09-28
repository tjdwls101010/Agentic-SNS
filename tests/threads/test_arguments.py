"""Each command takes only the arguments that change what it does; combinations that cannot mean anything are refused
before any request, and the continuation keeps what the caller chose."""
import json
import os
import shutil
from pathlib import Path

import pytest

from .fixtures.builders import envelope, listed_post, tab
from .helpers import POST, calls, data, more_args, run_cli, run_more

LEGACY = Path(__file__).with_name('fixtures') / 'legacy'
REPLIES = 'BarcelonaProfileRepliesTabDirectQuery'


@pytest.mark.parametrize('arguments', [
    ('about', '@fixture_user', '--limit', '3'), ('about', '@fixture_user', '--chars', '50'),
    ('about', '@fixture_user', '--out', 'x.ndjson'), ('about', '@fixture_user', '--after', '1'),
    ('post', POST, '--out', 'x.ndjson'), ('post', POST, '--after', '1'),
    ('graph', '@fixture_user', 'followers', '--chars', '50'),
    ('doctor', '--json'), ('refresh', '--json'), ('schema', '--json'),
    ('home', '--tab', 'replies'), ('me', 'liked', '--since', '2026-01-01'),
    ('search', 'python', '--type', 'users', '--chars', '50'),
    ('user', 'https://www.threads.com/@fixture_user/replies', '--tab', 'media'),
    ('home', '--max-requests', '41'), ('home', '--max-requests', '0'),
])
def test_an_argument_that_cannot_apply_is_refused_before_any_request(fake_aside, arguments):
    result = run_cli(*arguments)
    assert result.returncode == 2, result.stdout
    assert calls(fake_aside) == []


@pytest.mark.parametrize('arguments', [
    ('user', 'https://www.threads.com/@fixture_user/replies', '--tab', 'replies', '--json'),
    ('home', '--chars', '50', '--json'),
    ('about', '@fixture_user', '--max-requests', '3', '--json'),
])
def test_a_combination_that_means_something_is_accepted(routes, arguments):
    routes.set('BarcelonaProfileRepliesTabDirectQuery', envelope({'data': {'mediaData': {
        'edges': [], 'page_info': {'has_next_page': False, 'end_cursor': None}}}})).write()
    result = run_cli(*arguments)
    assert result.returncode in (0, 7), result.stdout + result.stderr


def test_a_tab_url_reads_that_tab(routes):
    routes.set('BarcelonaProfileRepliesTabDirectQuery', envelope({'data': {'mediaData': {
        'edges': [], 'page_info': {'has_next_page': False, 'end_cursor': None}}}})).write()
    run_cli('user', 'https://www.threads.com/@fixture_user/replies', '--json')
    assert calls(routes.path.parent / 'requests.ndjson')[-1]['name'] == 'BarcelonaProfileRepliesTabDirectQuery'


def test_the_request_cap_is_ten_unless_the_caller_names_another(routes):
    routes.set(REPLIES, envelope(tab([listed_post(1)], 'c1')))
    for n in range(1, 60):
        routes.set(f'{REPLIES}:after=c{n}', envelope(tab([listed_post(n + 1)], f'c{n + 1}')))
    routes.write()
    for extra in ([], ['--limit', '30'], ['--since', '2020-01-01'], ['--until', '2030-01-01'], ['--out', 'f.ndjson']):
        extra = [part.replace('f.ndjson', str(routes.path.parent / f'f{len(extra)}.ndjson')) for part in extra]
        body = data(run_cli('user', '@fixture_user', '--tab', 'replies', '--json', *extra))
        assert body['budget']['limit'] == 10, extra
    assert data(run_cli('user', '@fixture_user', '--tab', 'replies', '--limit', '30', '--max-requests', '25', '--json'))['budget']['limit'] == 25


def test_more_keeps_the_display_and_cost_choices(fake_aside):
    first = data(run_cli('home', '--limit', '2', '--chars', '30', '--max-requests', '5', '--json'))
    words = more_args(first['next'])
    for option in (['--limit', '2'], ['--chars', '30'], ['--max-requests', '5']):
        assert any(words[i:i + 2] == option for i in range(len(words))), words
    assert '--json' in words
    second = data(run_more(first['next']))
    assert len(second['results']) == 2 and second['budget']['limit'] == 5
    text = run_cli('home', '--limit', '1').stdout.splitlines()
    more = next(line for line in text if line.startswith('more: ')).removeprefix('more: ')
    assert '--json' not in more_args(more) and '--limit' in more_args(more)


def test_handles_and_files_from_before_this_interface_still_resume(fake_aside, tmp_path):
    home = Path(os.environ['THREADS_HOME'])
    shutil.copytree(LEGACY / 'cursors', home / 'cursors')
    handle = run_cli('user', '@fixture_user', '--after', '1', '--json')
    assert handle.returncode == 0, handle.stdout + handle.stderr
    assert [p['id'] for p in data(handle)['results']][:2] == ['3', '4']
    file = tmp_path / 'home.ndjson'
    file.write_bytes((LEGACY / 'home.ndjson').read_bytes())
    header = file.read_text().splitlines()[0]
    resumed = run_cli('home', '--feed', 'following', '--limit', '1', '--after', '2', '--out', str(file), '--json')
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert data(resumed)['count'] == 2
    assert file.read_text().splitlines()[0] == header
    saved = [json.loads(line) for line in file.read_text().splitlines()]
    assert [r['id'] for r in saved if r.get('kind') is None] == ['1', '2']
    # The old handle now lags the file it was saved with: the file's committed progress wins, the handle is refused.
    before = file.read_bytes()
    stale = run_cli('home', '--feed', 'following', '--after', '2', '--out', str(file), '--json')
    assert stale.returncode == 2 and file.read_bytes() == before


def test_more_names_the_profile_as_a_handle(fake_aside):
    more = data(run_cli('user', 'https://www.threads.com/@fixture_user', '--limit', '2', '--json'))['next']
    words = more_args(more)
    assert words[:2] == ['user', '--tab'] and '@fixture_user' in words and '/@fixture_user' not in words


# --- date windows: filtered locally; the result says whether the whole window was read --------------------------

OLD, NEW = 1780000000, 1790000000   # 2026-05-28 and 2026-09-21


def test_a_newest_first_tab_ends_at_the_window_start_and_says_the_window_is_complete(fake_aside):
    body = data(run_cli('user', '@fixture_user', '--since', '2027-01-01', '--json'))
    assert body['stop_reason'] == 'window_reached'
    assert body['window'] == {'since': '2027-01-01', 'until': None, 'complete': True}
    last = run_cli('user', '@fixture_user', '--since', '2027-01-01').stdout.splitlines()[-1]
    assert last.startswith('window: since 2027-01-01 · complete')


def test_a_tab_not_ordered_by_writing_time_never_claims_its_window_start(routes):
    routes.set('BarcelonaProfileRepostsTabDirectQuery',
               envelope({'data': {'mediaData': {'edges': [{'node': {'thread_items': [{'post': listed_post(1, taken_at=OLD)}]}}],
                                                'page_info': {'has_next_page': True, 'end_cursor': 'R'}}}}))
    routes.set('BarcelonaProfileRepostsTabDirectQuery:after=R',
               envelope({'data': {'mediaData': {'edges': [{'node': {'thread_items': [{'post': listed_post(2, taken_at=NEW)}]}}],
                                                'page_info': {'has_next_page': False, 'end_cursor': None}}}})).write()
    body = data(run_cli('user', '@fixture_user', '--tab', 'reposts', '--since', '2026-09-01', '--json'))
    assert [p['id'] for p in body['results']] == ['2']
    assert body['stop_reason'] == 'exhausted' and body['window']['complete'] is True


def test_a_window_cut_short_says_it_is_partial_and_how_to_continue(routes):
    routes.set(REPLIES, envelope(tab([listed_post(1, taken_at=NEW)], 'c1')))
    routes.set(REPLIES + ':after=c1', envelope(tab([listed_post(2, taken_at=NEW)], 'c2'))).write()
    body = data(run_cli('user', '@fixture_user', '--tab', 'replies', '--since', '2026-09-01', '--limit', '1', '--json'))
    assert body['window']['complete'] is False and body['next']
    last = run_cli('user', '@fixture_user', '--tab', 'replies', '--since', '2026-09-01', '--limit', '1').stdout.splitlines()[-1]
    assert last.startswith('window: since 2026-09-01 · partial') and 'more:' in last
