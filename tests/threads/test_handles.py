"""handles: numbered continuation handles on the real filesystem (fixtures/stores.json, handles)."""
import json
import os
import stat
import time

import pytest

from threads import handles
from threads.errors import ThreadsError

X = {'command': 'feed', 'target': None, 'sort': 'recent', 'account_id': '111'}
Y = {'command': 'feed', 'target': None, 'sort': 'top', 'account_id': '111'}


def test_numbers_increase(data_dir):
    numbers = [handles.save(X, {'cursor': str(i)}) for i in range(3)]
    assert numbers == [numbers[0], numbers[0] + 1, numbers[0] + 2]
    assert handles.load(numbers[1], X) == {'cursor': '1'}


def test_counter_survives_deleting_handle_files(data_dir):
    first = [handles.save(X, {}) for _ in range(3)]
    for path in (data_dir / 'handles').glob('*.json'):
        path.unlink()
    assert handles.save(X, {}) == first[-1] + 1


def test_seeded_counter_continues_above_the_seed(data_dir):
    (data_dir / 'handles').mkdir(parents=True)
    (data_dir / 'handles/counter').write_text('1064')
    assert handles.save(X, {}) == 1065


@pytest.mark.parametrize('context', [Y, {**X, 'account_id': '222'}])
def test_other_query_or_account_is_refused(data_dir, context):
    number = handles.save(X, {})
    with pytest.raises(ThreadsError) as error:
        handles.load(number, context)
    assert error.value.code == 2 and 'another' in error.value.message


def test_expired_handle_is_refused(data_dir):
    number = handles.save(X, {})
    path = data_dir / 'handles' / f'{number}.json'
    record = json.loads(path.read_text())
    record['created_at'] = time.time() - handles.TTL_SECONDS - 1
    path.write_text(json.dumps(record))
    with pytest.raises(ThreadsError) as error:
        handles.load(number, X)
    assert error.value.code == 2 and 'expired' in error.value.message


def test_older_format_is_refused(data_dir):
    number = handles.save(X, {})
    path = data_dir / 'handles' / f'{number}.json'
    record = json.loads(path.read_text())
    record['format'] = 0
    path.write_text(json.dumps(record))
    with pytest.raises(ThreadsError) as error:
        handles.load(number, X)
    assert error.value.code == 2 and 'earlier version' in error.value.message


def test_missing_handle_is_refused(data_dir):
    with pytest.raises(ThreadsError) as error:
        handles.load(99, X)
    assert error.value.code == 2


@pytest.mark.parametrize('number', ['../x', '0', '-1', '1.5', '', None, True])
def test_malformed_number_is_refused_before_the_filesystem(data_dir, number):
    with pytest.raises(ThreadsError) as error:
        handles.load(number, X)
    assert error.value.code == 2
    assert not (data_dir / 'handles').exists()


def test_files_are_private(data_dir):
    number = handles.save(X, {})
    assert stat.S_IMODE(os.stat(data_dir / 'handles').st_mode) == 0o700
    assert stat.S_IMODE(os.stat(data_dir / 'handles' / f'{number}.json').st_mode) == 0o600


def test_clean_removes_handle_files_but_not_the_counter(data_dir):
    numbers = [handles.save(X, {}) for _ in range(2)]
    handles.clean()
    assert not list((data_dir / 'handles').glob('*.json'))
    assert handles.save(X, {}) == numbers[-1] + 1


def test_a_handle_from_the_previous_threads_skill_is_refused(data_dir):
    (data_dir / 'handles').mkdir(parents=True, exist_ok=True)
    (data_dir / 'handles/7.json').write_text(json.dumps({'context': X, 'cursor': {}, 'pending': [],
                                                        'created_at': '2026-09-29T00:00:00+00:00'}))
    with pytest.raises(ThreadsError) as error:
        handles.load(7, X)
    assert error.value.code == 2 and 'earlier version' in error.value.message
