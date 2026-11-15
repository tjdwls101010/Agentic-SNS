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


def age(path, seconds):
    """Make a saved handle `seconds` old (its record's own clock and the file's)."""
    import os
    record = json.loads(path.read_text())
    record['created_at'] -= seconds
    path.write_text(json.dumps(record))
    past = time.time() - seconds
    os.utime(path, (past, past))


def test_an_expired_handle_names_the_command_that_made_it(data_dir):
    """L1: a handle lasts a day; the next day its more: line fails — and says what to run instead, word for word."""
    remake = 'uv run "/skill/scripts/cli.py" threads replies https://www.threads.com/@a/post/B --sort top'
    number = handles.save(CONTEXT, {'cursor': 'a'}, remake=remake)
    age(data_dir / 'handles' / f'{number}.json', handles.TTL_SECONDS + 10)
    with pytest.raises(SnsError) as caught:
        handles.load(number, CONTEXT)
    assert caught.value.kind == 'argument' and 'expired' in caught.value.message and '24 hours' in caught.value.message
    assert caught.value.fix.endswith(remake)


def test_an_expired_handle_keeps_only_its_command_for_a_week_then_goes(data_dir):
    """Past its day a handle keeps no cursor (other people's ids), only the command that remakes it, for 7 more days;
    the counter is never touched."""
    remake = 'uv run "/skill/scripts/cli.py" threads replies X'
    number = handles.save(CONTEXT, {'cursor': 'a'}, remake=remake)
    old = data_dir / 'handles' / f'{number}.json'
    age(old, handles.TTL_SECONDS + 10)
    handles.save(CONTEXT, {'cursor': 'b'})  # saving prunes
    kept = json.loads(old.read_text())
    assert 'state' not in kept and kept['remake'] == remake
    with pytest.raises(SnsError) as caught:
        handles.load(number, CONTEXT)
    assert caught.value.fix.endswith(remake)
    age(old, 7 * 24 * 3600)
    handles.save(CONTEXT, {'cursor': 'c'})
    assert not old.exists() and (data_dir / 'handles' / 'counter').exists()


def test_handle_files_are_private(data_dir):
    number = handles.save(CONTEXT, {'cursor': 'a'})
    assert (data_dir / 'handles' / f'{number}.json').stat().st_mode & 0o077 == 0


@pytest.mark.parametrize('argv,options,expected', [
    (('x', 'search', '--out', 'F', '--', '--o', 'next'), {'out': 'F'}, 'x search -- --o next'),
    (('threads', 'search', '--after', '7', '--', '--af', 'x'), {'after': 7}, 'threads search -- --af x'),
    (('facebook', 'comments', 'U', '--ou=F', '--limit', '5'), {'out': 'F'}, 'facebook comments U --limit 5'),
])
def test_the_command_that_starts_a_reading_again_keeps_every_word_after_a_double_dash(argv, options, expected):
    """A handle's remake drops the --out file and the --after handle (however abbreviated) but nothing after `--`,
    where a search text may itself look like an option."""
    from types import SimpleNamespace
    from sns.reading import Connection
    connection = SimpleNamespace(remake=None, options=options,
                                 invocation=SimpleNamespace(argv=argv, cli_path='/skill/scripts/cli.py'))
    assert Connection.start_over(connection).endswith(' ' + expected)
