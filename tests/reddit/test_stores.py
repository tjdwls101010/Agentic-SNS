"""Local state on a real filesystem (fixture stores.json): --out collections, handles, comment-tree snapshots, and the
scrub of diagnostics."""
import json
import os
import time

import pytest

from conftest import fixture
from reddit import collection, handles, snapshots
from reddit.errors import RedditError, scrub

STORES = fixture('stores.json')
X = {'command': 'sub', 'target': 'r/example', 'sort': 'new', 'aside_account': 'u0', 'reddit_account': 'viewer'}
Y = {**X, 'sort': 'hot'}


def scenario(section, name):
    return next(s for s in STORES[section]['scenarios'] if s['name'] == name)


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def records(*ids):
    return [{'kind': 'post', 'id': i} for i in ids]


# --- collection


def test_new_file_gets_header_and_is_private(tmp_path):
    assert scenario('collection', 'new-file-gets-header')
    path = tmp_path / 'out.ndjson'
    collection.OutFile(path, X).close()
    header, = lines(path)
    assert header['kind'] == 'header' and header['format'] == collection.FORMAT and header['context'] == X
    assert oct(path.stat().st_mode & 0o777) == '0o600'


def test_page_commit_and_tail_replay(tmp_path):
    path = tmp_path / 'out.ndjson'
    out = collection.OutFile(path, X)
    out.commit(records('t3_a', 't3_b'), {'after': 't3_b'}, None)
    out.close()
    with path.open('a') as stream:
        stream.write(json.dumps({'kind': 'post', 'id': 't3_c'}) + '\n{"kind": "post", "id": "t3_d"')
    out = collection.OutFile(path, X)
    assert out.ids == {'t3_a', 't3_b'} and out.state == {'after': 't3_b'} and out.count == 2
    out.commit(records('t3_b', 't3_c'), {'after': 't3_c'}, 'exhausted')
    out.close()
    kept = lines(path)
    assert [r.get('id') for r in kept] == [None, 't3_a', 't3_b', None, 't3_c', None]
    assert kept[3] == {'kind': 'page', 'state': {'after': 't3_b'}, 'ids': ['t3_a', 't3_b'], 'n': 2, 'stop_reason': None}
    assert collection.peek(path) == (X, True, 3)


@pytest.mark.parametrize('content', [
    json.dumps({'kind': 'header', 'format': collection.FORMAT, 'context': Y}) + '\n',
    json.dumps({'kind': 'header', 'format': 0, 'context': X}) + '\n',
    # the old skill's header: the context fields at the top level, no format
    json.dumps({'command': 'sub', 'target': 'r/example', 'kind': 'header', 'started_at': 'x', 'limit_unit': 'page'}) + '\n',
    json.dumps({'kind': 'header', 'format': collection.FORMAT, 'context': X}) + '\n' + json.dumps({'kind': 'post', 'id': 'A'})
    + '\n' + json.dumps({'kind': 'post', 'id': 'B'}) + '\n' + json.dumps({'kind': 'page', 'ids': ['A'], 'n': 1}) + '\n',
])
def test_foreign_old_or_damaged_files_are_refused_byte_identical(tmp_path, content):
    path = tmp_path / 'out.ndjson'
    path.write_text(content)
    with pytest.raises(RedditError) as caught:
        collection.OutFile(path, X)
    assert caught.value.code == 2
    assert path.read_text() == content


def test_another_reddit_account_is_a_login_error(tmp_path):
    path = tmp_path / 'out.ndjson'
    collection.OutFile(path, X).close()
    before = path.read_bytes()
    with pytest.raises(RedditError) as caught:
        collection.OutFile(path, {**X, 'reddit_account': 'someone_else'})
    assert caught.value.code == 4 and caught.value.reason == 'account_changed' and path.read_bytes() == before


def test_final_symlink_and_hard_link_refused(tmp_path):
    target = tmp_path / 'target.ndjson'
    target.write_text('')
    link = tmp_path / 'link.ndjson'
    link.symlink_to(target)
    with pytest.raises(RedditError):
        collection.OutFile(link, X)
    assert target.read_text() == ''
    hard = tmp_path / 'hard.ndjson'
    os.link(target, hard)
    with pytest.raises(RedditError):
        collection.OutFile(hard, X)


def test_existing_file_forced_private(tmp_path):
    path = tmp_path / 'out.ndjson'
    path.write_text('')
    path.chmod(0o644)
    collection.OutFile(path, X).close()
    assert oct(path.stat().st_mode & 0o777) == '0o600'


def test_a_symlinked_parent_is_followed_and_reported(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    (tmp_path / 'via').symlink_to(real, target_is_directory=True)
    out = collection.OutFile(tmp_path / 'via' / 'out.ndjson', X)
    out.close()
    assert out.path == real.resolve() / 'out.ndjson' and out.path.exists()


def test_nested_records_are_refused(tmp_path):
    out = collection.OutFile(tmp_path / 'out.ndjson', X)
    with pytest.raises(RedditError):
        out.commit([{'kind': 'comment', 'id': 't1_a', 'replies': []}], None, None)
    out.close()


# --- handles


CONTEXT = {'command': 'sub', 'target': 'r/example', 'sort': 'new', 'reddit_account': 'viewer'}


def test_handle_numbers_increase_and_survive_cleaning(data_dir):
    first = handles.save('u0', CONTEXT, {'after': 't3_a'})
    second = handles.save('u0', CONTEXT, {'after': 't3_b'})
    assert second == first + 1
    for path in (data_dir / 'handles/u0').glob('*.json'):
        path.unlink()
    assert handles.save('u0', CONTEXT, {}) == second + 1
    assert handles.load('u0', second + 1, CONTEXT) == ({}, 'viewer')


def test_handle_bound_to_its_query(data_dir):
    number = handles.save('u0', CONTEXT, {'after': 't3_a'})
    assert handles.load('u0', number, CONTEXT) == ({'after': 't3_a'}, 'viewer')
    with pytest.raises(RedditError) as caught:
        handles.load('u0', number, {**CONTEXT, 'sort': 'hot'})
    assert caught.value.code == 2 and 'another' in caught.value.message
    with pytest.raises(RedditError) as caught:
        handles.load('u1', number, CONTEXT)
    assert caught.value.code == 2, 'another Aside account has its own handles'


def test_a_handle_names_the_reddit_account_that_read_it(data_dir):
    number = handles.save('u0', CONTEXT, {})
    assert handles.load('u0', number, {**CONTEXT, 'reddit_account': None}) == ({}, 'viewer')


def test_expired_and_old_format_handles(data_dir):
    number = handles.save('u0', CONTEXT, {})
    path = data_dir / f'handles/u0/{number}.json'
    record = json.loads(path.read_text())
    path.write_text(json.dumps({**record, 'created_at': time.time() - handles.TTL_SECONDS - 5}))
    with pytest.raises(RedditError) as caught:
        handles.load('u0', number, CONTEXT)
    assert 'expired' in caught.value.message
    path.write_text(json.dumps({**record, 'format': 0}))
    with pytest.raises(RedditError) as caught:
        handles.load('u0', number, CONTEXT)
    assert 'earlier version' in caught.value.message
    for bad in ('0', '-1', 'x', True):
        with pytest.raises(RedditError):
            handles.load('u0', bad, CONTEXT)


# --- snapshots


KEY = ['t3_aaa1', None, 'confidence']


def test_a_new_generation_leaves_the_old_one_alone(data_dir):
    store = snapshots.Snapshots('u0')
    with store.locked():
        first = store.new(KEY)
        store.save(first, {'observed_at': 1, 'shown': ['t1_a']})
        time.sleep(0.002)
        second = store.new(KEY)
        store.save(second, {'observed_at': 2, 'shown': []})
    assert first != second and store.latest(KEY) == second
    assert store.load(first) == {'observed_at': 1, 'shown': ['t1_a']}
    assert store.latest(['t3_bbb2', None, 'confidence']) is None


def test_expired_generation_is_gone(data_dir):
    store = snapshots.Snapshots('u0')
    generation = store.new(KEY)
    store.save(generation, {})
    path = data_dir / f'snapshots/u0/{generation}.json'
    old = time.time() - snapshots.TTL_SECONDS - 5
    os.utime(path, (old, old))
    assert store.load(generation) is None and store.latest(KEY) is None


def test_size_cap_evicts_the_oldest_others(data_dir, monkeypatch):
    store = snapshots.Snapshots('u0')
    monkeypatch.setattr(snapshots, 'MAX_BYTES', 2500)
    made = []
    for index in range(3):
        generation = store.new(['t3_x%d' % index, None, 'new'])
        store.save(generation, {'pad': 'x' * 1000})
        made.append(generation)
        time.sleep(0.01)
    assert store.load(made[0]) is None and store.load(made[2]) is not None


def test_corrupt_or_foreign_snapshot_reference(data_dir):
    store = snapshots.Snapshots('u0')
    generation = store.new(KEY)
    (data_dir / f'snapshots/u0/{generation}.json').write_text('{')
    with pytest.raises(RedditError) as caught:
        store.load(generation)
    assert caught.value.code == 2 and 'post again' in caught.value.fix
    with pytest.raises(RedditError):
        store.load('../../etc/passwd')


# --- scrub


@pytest.mark.parametrize('case', STORES['scrub']['cases'], ids=lambda c: str(c['input'])[:30])
def test_scrub(case):
    got = scrub(case['input'])
    if 'output' in case:
        assert got == case['output']
    else:
        assert not [x for x in case['output_excludes'] if x in json.dumps(got)]
