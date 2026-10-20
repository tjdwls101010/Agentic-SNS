"""Numbered handles (sns.handles): one counter for the whole skill, never reused, bound to the query they continue."""
import json
import time

import pytest

from sns import handles
from sns.errors import SnsError

CONTEXT = {'platform': 'threads', 'command': 'replies', 'target': 'https://www.threads.com/@a/post/B',
           'identity': {'sort': 'top'}, 'aside_account': 'u0'}


def test_the_first_handle_is_1000_and_numbers_only_grow(data_dir):
    first = handles.save(CONTEXT, {'cursor': 'a'}, viewer='111')
    second = handles.save(CONTEXT, {'cursor': 'b'}, viewer='111')
    assert (first, second) == (1000, 1001)
    for path in (data_dir / 'handles').glob('*.json'):
        path.unlink()
    assert handles.save(CONTEXT, {'cursor': 'c'}) == 1002


def test_a_handle_gives_back_its_state_and_the_account_it_was_read_with(data_dir):
    number = handles.save(CONTEXT, {'cursor': 'a'}, viewer='111')
    assert handles.load(number, CONTEXT) == ({'cursor': 'a'}, '111')
    assert handles.load(str(number), CONTEXT) == ({'cursor': 'a'}, '111')


def test_a_handle_of_another_platform_or_command_names_where_it_belongs(data_dir):
    number = handles.save(CONTEXT, {'cursor': 'a'})
    with pytest.raises(SnsError) as caught:
        handles.load(number, {**CONTEXT, 'platform': 'x', 'command': 'replies'})
    assert caught.value.kind == 'argument' and 'threads replies' in caught.value.message
    with pytest.raises(SnsError) as caught:
        handles.load(number, {**CONTEXT, 'identity': {'sort': 'recent'}})
    assert caught.value.kind == 'argument'


def test_an_expired_missing_or_older_handle_is_an_argument_error(data_dir):
    number = handles.save(CONTEXT, {'cursor': 'a'})
    path = data_dir / 'handles' / f'{number}.json'
    record = json.loads(path.read_text())
    record['created_at'] = time.time() - handles.TTL_SECONDS - 1
    path.write_text(json.dumps(record))
    with pytest.raises(SnsError) as caught:
        handles.load(number, CONTEXT)
    assert caught.value.kind == 'argument' and 'expired' in caught.value.message
    record['format'] = 0
    record['created_at'] = time.time()
    path.write_text(json.dumps(record))
    with pytest.raises(SnsError) as caught:
        handles.load(number, CONTEXT)
    assert 'earlier version' in caught.value.message
    for bad in (99999, 'abc', 0, -1, True):
        with pytest.raises(SnsError) as caught:
            handles.load(bad, CONTEXT)
        assert caught.value.kind == 'argument'


def test_saving_prunes_handles_past_their_ttl_but_keeps_the_counter(data_dir):
    import os
    number = handles.save(CONTEXT, {'cursor': 'a'})
    old = data_dir / 'handles' / f'{number}.json'
    past = time.time() - handles.TTL_SECONDS - 10
    os.utime(old, (past, past))
    handles.save(CONTEXT, {'cursor': 'b'})
    assert not old.exists() and (data_dir / 'handles' / 'counter').exists()


def test_handle_files_are_private(data_dir):
    number = handles.save(CONTEXT, {'cursor': 'a'})
    assert (data_dir / 'handles' / f'{number}.json').stat().st_mode & 0o077 == 0
