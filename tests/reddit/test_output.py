"""Durable output and continuation contracts against real private files."""
import json
import os
import time
import pytest
from reddit_skill._errors import RedditError
from reddit_skill._output import OutFile, CursorStore, cleanup_cache

CONTEXT = {'target': 'r/python', 'sort': 'new', 'account': 'alice'}


def test_output_recovers_full_thread_snapshot_and_replays_uncommitted_tail(tmp_path):
    path = tmp_path / 'out.ndjson'
    state = {'nodes': {'t1_x': {'data': {'fullname': 't1_x', 'body': 'hello'}, 'shown': True}},
             'pending_more': [{'parent': 't1_x', 'ids': ['y']}], 'requested_ids': ['x'],
             'received_ids': ['x'], 'orphans': {}, 'root_children': ['t1_x'], 'account': 'alice'}
    records = [{'kind': 'post', 'fullname': 't3_x'}, {'kind': 'comment', 'fullname': 't1_x', 'parent': 't3_x', 'depth': 0}]
    with OutFile(path, CONTEXT) as out:
        out.commit(records, {'thread_path': 'cache-gone.json'}, 'limit_reached', state=state)
        assert out.count == 2
    with path.open('ab') as stream:
        stream.write(b'{"kind":"comment","fullname":"t1_y"}\n{"kind":')
    with OutFile(path, CONTEXT) as out:
        assert out.state == state
        assert out.ids == {'t3_x', 't1_x'}
        assert not out.complete
        out.commit(records + [{'kind': 'comment', 'fullname': 't1_y'}], None, 'exhausted', state=state)
        assert out.count == 3
    with OutFile(path, CONTEXT) as out:
        assert out.count == 3
        assert out.complete
    assert len([r for r in map(json.loads, path.read_text().splitlines()) if r['kind'] == 'comment']) == 2
    assert path.stat().st_mode & 0o777 == 0o600


def test_committed_corruption_is_not_silently_truncated(tmp_path):
    path = tmp_path / 'out'
    with OutFile(path, CONTEXT) as out:
        out.commit([{'kind': 'post', 'fullname': 't3_a'}], None, 'exhausted')
    data = path.read_bytes().replace(b'"fullname":"t3_a"', b'"fullname":BROKEN')
    path.write_bytes(data)
    with pytest.raises(RedditError) as error:
        OutFile(path, CONTEXT)
    assert error.value.code == 2
    assert path.read_bytes() == data


def test_output_context_lock_and_nested_reply_guards(tmp_path):
    path = tmp_path / 'out'
    with OutFile(path, CONTEXT) as out:
        with pytest.raises(RedditError):
            OutFile(path, CONTEXT)
        with pytest.raises(RedditError):
            out.commit([{'kind': 'comment', 'fullname': 't1_a', 'replies': [{'body': 'nested'}]}], None, 'exhausted')
    with pytest.raises(RedditError):
        OutFile(path, dict(CONTEXT, account='bob'))


@pytest.mark.parametrize('parent_link', [False, True])
def test_output_refuses_symlink_destinations(tmp_path, parent_link):
    real = tmp_path / 'real'
    real.mkdir()
    target = real / 'out'
    target.write_text('preserve')
    link = tmp_path / 'link'
    link.symlink_to(real if parent_link else target)
    with pytest.raises(RedditError):
        OutFile(link / 'out' if parent_link else link, CONTEXT)
    assert target.read_text() == 'preserve'


def test_cursor_roundtrip_account_expiry_and_shared_cleanup(tmp_path):
    root = tmp_path / 'cache'
    store = CursorStore(root / 'cursors')
    number = store.save(CONTEXT, {'after': 't3_a'}, [{'fullname': 't1_a'}])
    assert store.load(number, CONTEXT)['pending'] == [{'fullname': 't1_a'}]
    assert store.save(CONTEXT, None) > number
    with pytest.raises(RedditError):
        store.load(number, dict(CONTEXT, account='bob'))
    path = store.directory / f'{number}.json'
    data = json.loads(path.read_text())
    data['created_at'] = '2000-01-01T00:00:00+00:00'
    path.write_text(json.dumps(data))
    with pytest.raises(RedditError):
        store.load(number, CONTEXT)
    assert store.directory.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    threads = root / 'threads'
    threads.mkdir()
    old, fresh = threads / 'old.json', threads / 'fresh.json'
    old.write_bytes(b'old')
    fresh.write_bytes(b'new')
    now = time.time()
    os.utime(old, (now - 86401, now - 86401))
    os.utime(fresh, (now + 1, now + 1))
    assert cleanup_cache(root, now=now, max_bytes=3) == 3
    assert not old.exists() and fresh.exists()
    assert (store.directory / 'counter').exists()
    assert store.save(CONTEXT, None) > number


@pytest.mark.parametrize('path', ['../outside.json', '/tmp/escape.json', '../../threads/a.json', 'a.txt'])
def test_cursor_rejects_untrusted_cached_paths(tmp_path, path):
    store = CursorStore(tmp_path / 'cursors')
    with pytest.raises(RedditError):
        store.save(CONTEXT, {'thread_path': path})
    number = store.save(CONTEXT, {'thread_path': 't3_a-new.json'})
    file = store.directory / f'{number}.json'
    data = json.loads(file.read_text())
    data['cursor']['thread_path'] = path
    file.write_text(json.dumps(data))
    with pytest.raises(RedditError):
        store.load(number, CONTEXT)


def test_failed_disk_commit_does_not_advance_in_memory_progress(tmp_path, monkeypatch):
    with OutFile(tmp_path / 'out', CONTEXT) as out:
        def disk_full(fd):
            raise OSError('disk full')
        monkeypatch.setattr(os, 'fsync', disk_full)
        with pytest.raises(RedditError) as error:
            out.commit([{'kind': 'post', 'fullname': 't3_a'}], None, 'exhausted')
        assert error.value.code == 8
        assert out.count == 0 and not out.complete


def test_cursor_rejects_non_list_pending_and_counter_corruption(tmp_path):
    store = CursorStore(tmp_path / 'cursors')
    with pytest.raises(RedditError):
        store.save(CONTEXT, None, pending={'bad': 'shape'})
    (store.directory / 'counter').write_text('-2')
    with pytest.raises(RedditError):
        store.save(CONTEXT, None)


def test_symlink_cursor_files_and_thread_references_are_rejected(tmp_path):
    store = CursorStore(tmp_path / 'cursors')
    external = tmp_path / 'private'
    external.write_text('preserve')
    (store.directory / '1.json').symlink_to(external)
    with pytest.raises(RedditError):
        store.load(1, CONTEXT)
    threads = tmp_path / 'threads'
    threads.mkdir()
    (threads / 'a.json').symlink_to(external)
    with pytest.raises(RedditError):
        store.save(CONTEXT, {'thread_path': 'a.json'})
    assert external.read_text() == 'preserve'


def test_cleanup_does_not_delete_during_thread_transaction(tmp_path):
    import fcntl
    root = tmp_path / 'cache'
    threads = root / 'threads'
    threads.mkdir(parents=True)
    path = threads / 'active.json'
    path.write_text('{}')
    with (root / 'threads.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RedditError) as error:
            cleanup_cache(root, max_bytes=0)
        assert error.value.code == 8
        assert path.exists()
    assert cleanup_cache(root, max_bytes=0) == 0
