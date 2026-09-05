import json

import pytest

from threads_skill._output import CursorStore, OutFile
from threads_skill._errors import ThreadsError


def test_cursor_binds_context_and_preserves_pending_without_credentials():
    store = CursorStore()
    context = {'command': 'home', 'feed': 'following', 'account': 'u0'}
    number = store.save(context, {'after': 'A', 'pending': [{'id': '2'}], 'actor': '42'})
    assert store.load(number, context)['cursor']['pending'] == [{'id': '2'}]
    with pytest.raises(ThreadsError):
        store.load(number, context | {'feed': 'foryou'})
    with pytest.raises(ThreadsError):
        store.load('../1', context)


def test_corrupt_cursor_state_is_rejected_before_the_reader_uses_it():
    store = CursorStore()
    number = store.save({'command': 'home'}, {'after': 'A', 'pending': []})
    path = store.directory / f'{number}.json'
    record = json.loads(path.read_text())
    record['cursor'] = 42
    path.write_text(json.dumps(record))
    with pytest.raises(ThreadsError) as error:
        store.load(number, {'command': 'home'})
    assert error.value.code == 2


def test_output_discards_uncommitted_tail_and_does_not_claim_ssr_is_exhausted(tmp_path):
    path = tmp_path / 'posts.ndjson'
    file = OutFile(path, {'command': 'post'})
    state = {'completeness': {'reported_direct': 10, 'received_direct': 2}}
    file.commit([{'id': '1'}], state, 'ssr_complete')
    file.close()
    with path.open('a') as stream:
        stream.write('{"id":"uncommitted"}\n')
    file = OutFile(path, {'command': 'post'})
    assert file.count == 1 and not file.complete
    assert file.cursor['completeness']['received_direct'] == 2
    file.close()
    assert 'uncommitted' not in path.read_text()
    assert json.loads(path.read_text().splitlines()[-1])['stop_reason'] == 'ssr_complete'


def test_output_rejects_symlink_without_touching_target(tmp_path):
    original = tmp_path / 'original'
    original.write_text('valuable data')
    link = tmp_path / 'link'
    link.symlink_to(original)
    with pytest.raises(ThreadsError):
        OutFile(link, {})
    assert original.read_text() == 'valuable data'


def test_file_continuation_keeps_path_and_rejects_a_handle_advanced_without_the_file(fake_aside, tmp_path):
    from .test_cli import run_cli
    file = tmp_path / 'collection.ndjson'
    first = json.loads(run_cli('home', '--limit', '1', '--out', str(file), '--json').stdout)
    assert '--out' in first['next'] and str(file) in first['next']
    second = json.loads(run_cli('home', '--limit', '1', '--after', str(first['next_handle']), '--json').stdout)
    before = file.read_bytes()
    conflict = run_cli('home', '--after', str(second['next_handle']), '--out', str(file), '--json')
    assert conflict.returncode == 2, conflict.stdout + conflict.stderr
    assert file.read_bytes() == before
