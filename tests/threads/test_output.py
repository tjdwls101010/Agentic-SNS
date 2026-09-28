"""Continuation handles and --out files through the CLI: bound to one query, never trusted when damaged."""
import json
import os
from pathlib import Path

import pytest

from .fixtures.builders import feed, envelope, listed_post, preloader, route
from .helpers import calls, data, run_cli


def handles():
    return Path(os.environ['THREADS_HOME']) / 'cursors'


def test_file_continuation_keeps_path_and_rejects_a_handle_advanced_without_the_file(fake_aside, tmp_path):
    file = tmp_path / 'collection.ndjson'
    first = data(run_cli('home', '--limit', '1', '--out', str(file), '--json'))
    assert '--out' in first['next'] and str(file) in first['next']
    second = data(run_cli('home', '--limit', '1', '--after', str(first['next_handle']), '--json'))
    before = file.read_bytes()
    conflict = run_cli('home', '--after', str(second['next_handle']), '--out', str(file), '--json')
    assert conflict.returncode == 2, conflict.stdout + conflict.stderr
    assert file.read_bytes() == before


def test_a_handle_only_continues_the_query_that_made_it(routes):
    routes.set('BarcelonaFeedDirectQuery', envelope(feed([listed_post(1), listed_post(2)], 'A'))).write()
    handle = data(run_cli('home', '--feed', 'following', '--limit', '1', '--json'))['next_handle']
    before = len(calls(routes.path.parent / 'requests.ndjson'))
    other = run_cli('home', '--feed', 'foryou', '--after', str(handle), '--json')
    assert other.returncode == 2
    assert len(calls(routes.path.parent / 'requests.ndjson')) == before


@pytest.mark.parametrize('handle', ['0', '../1', '999'])
def test_a_handle_that_is_not_a_saved_number_is_refused(fake_aside, handle):
    result = run_cli('home', '--after', handle, '--json')
    assert result.returncode == 2
    assert calls(fake_aside) == []


def test_a_damaged_handle_is_refused_before_any_request(fake_aside):
    handle = data(run_cli('home', '--limit', '1', '--json'))['next_handle']
    path = handles() / f'{handle}.json'
    record = json.loads(path.read_text())
    record['cursor'] = 42
    path.write_text(json.dumps(record))
    before = len(calls(fake_aside))
    result = run_cli('home', '--limit', '1', '--after', str(handle), '--json')
    assert result.returncode == 2
    assert len(calls(fake_aside)) == before


def test_a_continuation_made_by_another_account_is_refused(routes):
    handle = data(run_cli('home', '--limit', '1', '--json'))['next_handle']
    routes.set('/', route([preloader('BarcelonaFeedDirectQuery', variant='for_you')], actor='200')).write()
    result = run_cli('home', '--limit', '1', '--after', str(handle), '--json')
    assert result.returncode == 2
    assert 'different logged-in' in data(result)['message']


def test_an_interrupted_page_is_dropped_and_read_again(fake_aside, tmp_path):
    file = tmp_path / 'collection.ndjson'
    run_cli('home', '--limit', '1', '--out', str(file), '--json')
    with file.open('a') as stream:
        stream.write('{"id":"uncommitted"}\n')
    resumed = data(run_cli('home', '--limit', '1', '--out', str(file), '--json'))
    assert 'uncommitted' not in file.read_text()
    saved = [json.loads(line) for line in file.read_text().splitlines()]
    assert [r['id'] for r in saved if 'id' in r and r.get('kind') != 'page'] == ['1', '2']
    assert resumed['count'] == 2


def test_output_refuses_a_symlink_without_touching_its_target(fake_aside, tmp_path):
    original = tmp_path / 'original'
    original.write_text('valuable data')
    link = tmp_path / 'link.ndjson'
    link.symlink_to(original)
    result = run_cli('home', '--out', str(link), '--json')
    assert result.returncode == 2
    assert original.read_text() == 'valuable data'


def test_an_output_file_of_another_query_is_refused(fake_aside, tmp_path):
    file = tmp_path / 'collection.ndjson'
    run_cli('home', '--limit', '1', '--out', str(file), '--json')
    before = file.read_bytes()
    result = run_cli('user', '@fixture_user', '--out', str(file), '--json')
    assert result.returncode == 2
    assert file.read_bytes() == before
