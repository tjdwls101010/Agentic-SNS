"""Persistence seam: transactions survive continuations and bound local cache."""
import pytest

from reddit_skill._target import Target
from reddit_skill._thread import ThreadStateStore, create_state, select_batch


def state():
    return create_state([
        {'kind': 'Listing', 'data': {'children': [{'kind': 't3', 'data': {'id': 'p'}}]}},
        {'kind': 'Listing', 'data': {'children': [
            {'kind': 't1', 'data': {'id': name, 'body': name, 'parent_id': 't3_p'}} for name in ['a', 'b', 'c']]}},
    ], Target('post', post_id='p'))


def test_transaction_saves_continuation_and_rolls_back_failed_work():
    store = ThreadStateStore()
    key = store.save(state())
    with store.transaction(key) as current:
        assert select_batch(current, limit=1)['records'][0]['fullname'] == 't1_a'
    with pytest.raises(RuntimeError):
        with store.transaction(key) as current:
            select_batch(current, limit=1)
            raise RuntimeError('fetch failed')
    with store.transaction(key) as current:
        assert select_batch(current, limit=1)['records'][0]['fullname'] == 't1_b'
    assert store.load(key)['nodes']['t1_b']['shown'] is True
    assert key != store.key(Target('comment', post_id='p', comment_id='a'), 'best')
    assert key != store.key(Target('post', post_id='p'), 'new')


def test_next_write_expires_threads_and_cursors_then_evicts_oldest_for_capacity(tmp_path):
    import json
    import os
    import time
    home = tmp_path / 'cache'
    now = time.time()
    store = ThreadStateStore(home, clock=lambda: now)
    old = state()
    old['context']['sort'] = 'old'
    old_key = store.save(old)
    cursor = home / 'cursors' / '1.json'
    cursor.parent.mkdir()
    cursor.write_text(json.dumps({'thread': old_key}))
    for path in (home / 'threads' / (old_key + '.json'), cursor):
        os.utime(path, (now - 86401, now - 86401))
    key = store.save(state())
    assert store.load(old_key) is None
    assert not cursor.exists()
    assert not (home / 'threads' / (old_key + '.json')).exists()
    first_path = home / 'threads' / (key + '.json')
    os.utime(first_path, (now - 10, now - 10))
    small = ThreadStateStore(home, max_bytes=first_path.stat().st_size + 30, clock=lambda: now)
    newer = state()
    newer['context']['sort'] = 'new'
    newer_key = small.save(newer)
    assert small.load(key) is None
    assert small.load(newer_key) is not None
    assert small.cleanup()['bytes'] <= small.max_bytes


def test_invalid_key_and_oversized_state_cannot_replace_saved_data(tmp_path):
    from reddit_skill._errors import RedditError
    store = ThreadStateStore(tmp_path)
    key = store.save(state())
    with pytest.raises(RedditError):
        store.load('../../outside')
    tiny = ThreadStateStore(tmp_path, max_bytes=1)
    with pytest.raises(RedditError):
        tiny.save(state())
    assert store.load(key) is not None


def _read_in_process(home, key, entered, release, result):
    store = ThreadStateStore(home)
    with store.transaction(key) as current:
        entered.set()
        release.wait(5)
        result.put(select_batch(current, limit=1)['records'][-1]['fullname'])


def test_transaction_lock_covers_selection_and_save_across_processes(tmp_path):
    import multiprocessing
    ctx = multiprocessing.get_context('fork')
    store = ThreadStateStore(tmp_path)
    key = store.save(state())
    entered1, entered2, release1, release2 = [ctx.Event() for _ in range(4)]
    result = ctx.Queue()
    first = ctx.Process(target=_read_in_process, args=(tmp_path, key, entered1, release1, result))
    second = ctx.Process(target=_read_in_process, args=(tmp_path, key, entered2, release2, result))
    first.start()
    try:
        assert entered1.wait(3)
        second.start()
        assert not entered2.wait(0.2)
        release1.set()
        assert entered2.wait(3)
        release2.set()
        first.join(3)
        second.join(3)
        assert first.exitcode == second.exitcode == 0
        assert {result.get(timeout=2), result.get(timeout=2)} == {'t1_a', 't1_b'}
    finally:
        release1.set()
        release2.set()
        for process in (first, second):
            if process.pid:
                process.join(3)
                if process.is_alive():
                    process.terminate()
                    process.join()


def test_failed_atomic_replace_preserves_previous_continuation(tmp_path, monkeypatch):
    import os
    store = ThreadStateStore(tmp_path)
    key = store.save(state())
    def fail_replace(*args):
        raise OSError('disk failure')
    monkeypatch.setattr(os, 'replace', fail_replace)
    with pytest.raises(OSError):
        with store.transaction(key) as current:
            select_batch(current, limit=1)
    assert store.load(key)['nodes']['t1_a']['shown'] is False
    assert list((tmp_path / 'threads').glob('*.tmp')) == []


@pytest.mark.parametrize('failure_phase', ['before_commit', 'after_commit'])
def test_cleanup_failure_cannot_report_failed_selection_after_commit(tmp_path, monkeypatch, failure_phase):
    import os
    import time
    from pathlib import Path
    store = ThreadStateStore(tmp_path)
    key = store.save(state())
    cursor = tmp_path / 'cursors' / 'expired.json'
    cursor.parent.mkdir()
    cursor.write_text('{}')
    os.utime(cursor, (time.time() - 90000,) * 2)
    replace, unlink = os.replace, Path.unlink
    committed = False
    def track_replace(*args, **kwargs):
        nonlocal committed
        result = replace(*args, **kwargs)
        committed = True
        return result
    def fail_cleanup(path, *args, **kwargs):
        if path == cursor and (failure_phase == 'before_commit' or committed):
            raise PermissionError('maintenance denied')
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(os, 'replace', track_replace)
    monkeypatch.setattr(Path, 'unlink', fail_cleanup)
    if failure_phase == 'before_commit':
        with pytest.raises(PermissionError):
            with store.transaction(key) as current:
                select_batch(current, limit=1)
        assert store.load(key)['nodes']['t1_a']['shown'] is False
    else:
        with store.transaction(key) as current:
            select_batch(current, limit=1)
        assert store.load(key)['nodes']['t1_a']['shown'] is True
        assert store.cleanup()['bytes'] <= store.max_bytes


@pytest.mark.parametrize('entry', ['home', 'threads', 'cursors', 'file', 'lock'])
def test_cache_symlinks_cannot_read_or_delete_external_files(tmp_path, entry):
    import os
    import time
    from reddit_skill._errors import RedditError
    external = tmp_path / 'external'
    external.mkdir()
    keep = external / 'keep.json'
    keep.write_text('private external data')
    os.utime(keep, (time.time() - 90000,) * 2)
    home = tmp_path / 'home'
    if entry == 'home':
        home.symlink_to(external, target_is_directory=True)
    elif entry in ('threads', 'cursors'):
        home.mkdir()
        (home / entry).symlink_to(external, target_is_directory=True)
    else:
        store = ThreadStateStore(home)
        key = store.key(Target('post', post_id='p'))
        link = home / ('threads/' + key + '.json' if entry == 'file' else 'threads.lock')
        link.symlink_to(keep)
    with pytest.raises(RedditError) as error:
        store = ThreadStateStore(home)
        if entry == 'file':
            store.load(key)
        else:
            store.cleanup()
    assert error.value.code == 2
    assert keep.read_text() == 'private external data'


def test_private_modes_and_directory_replacement_are_checked_on_each_operation(tmp_path):
    import stat
    from reddit_skill._errors import RedditError
    home = tmp_path / 'home'
    store = ThreadStateStore(home)
    key = store.save(state())
    for path in (home, home / 'threads'):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    for path in (home / 'threads.lock', home / 'threads' / (key + '.json')):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    (home / 'threads').rename(home / 'original')
    (home / 'threads').symlink_to(home / 'original', target_is_directory=True)
    with pytest.raises(RedditError):
        store.save(state())


def test_crash_temporary_files_obey_ttl_and_capacity_on_next_write(tmp_path):
    import os
    import time
    store = ThreadStateStore(tmp_path)
    key = store.save(state())
    expired = tmp_path / 'threads' / 'crashed.tmp'
    expired.write_bytes(b'x' * 50)
    os.utime(expired, (time.time() - 90000,) * 2)
    store.save(state())
    assert not expired.exists()
    fresh = tmp_path / 'threads' / 'recent-crash.tmp'
    fresh.write_bytes(b'x' * 10000)
    os.utime(fresh, (time.time() - 10,) * 2)
    cap = (tmp_path / 'threads' / (key + '.json')).stat().st_size + 30
    bounded = ThreadStateStore(tmp_path, max_bytes=cap)
    bounded.save(state())
    assert not fresh.exists()
    assert bounded.load(key) is not None
    assert sum(p.stat().st_size for p in (tmp_path / 'threads').iterdir()) <= cap
    assert bounded.cleanup()['bytes'] <= cap
