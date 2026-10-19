"""collection: --out files on the real filesystem (fixtures/stores.json, collection)."""
import fcntl
import json

import pytest

from twitter import collection
from twitter.errors import TwitterError

X = {'command': 'feed', 'target': None, 'sort': 'recent', 'account_id': '111'}
Y = {'command': 'search', 'target': 'ai', 'type': 'posts', 'account_id': '111'}


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def committed(path, context, *pages):
    out = collection.OutFile(path, context)
    for records, state, reason in pages:
        out.commit(records, state, reason)
    out.close()


def test_new_file_gets_a_header(tmp_path):
    path = tmp_path / 'out.ndjson'
    collection.OutFile(path, X).close()
    [header] = lines(path)
    assert header['kind'] == 'header' and header['format'] == collection.FORMAT
    assert header['context'] == X and 'started_at' in header


def test_page_commit_writes_records_then_a_marker(tmp_path):
    path = tmp_path / 'out.ndjson'
    committed(path, X, ([{'id': 'A'}, {'id': 'B'}], {'cursor': 'CUR1'}, None))
    header, a, b, marker = lines(path)
    assert (a, b) == ({'id': 'A'}, {'id': 'B'})
    assert marker == {'kind': 'page', 'state': {'cursor': 'CUR1'}, 'ids': ['A', 'B'], 'n': 2, 'stop_reason': None}


def test_interrupted_tail_is_dropped_and_replayed(tmp_path):
    path = tmp_path / 'out.ndjson'
    committed(path, X, ([{'id': 'A'}, {'id': 'B'}], {'cursor': 'CUR1'}, None))
    with path.open('a') as f:
        f.write(json.dumps({'id': 'C'}) + '\n')
    out = collection.OutFile(path, X)
    assert out.state == {'cursor': 'CUR1'} and out.ids == {'A', 'B'} and out.count == 2
    out.close()
    assert [r.get('id') for r in lines(path)][-1] is None  # the marker is last again


def test_partial_line_is_dropped(tmp_path):
    path = tmp_path / 'out.ndjson'
    committed(path, X, ([{'id': 'A'}], {'cursor': 'C'}, None))
    with path.open('a') as f:
        f.write('{"id":"B"')
    collection.OutFile(path, X).close()
    assert [r.get('kind') for r in lines(path)] == ['header', None, 'page']


@pytest.mark.parametrize('first_line', [
    None,  # another query's header
    {'kind': 'header', 'format': collection.FORMAT - 1, 'context': X},
    {'kind': 'header', 'format': 2, 'command': 'feed', 'target': None, 'sort': 'recent', 'account_id': '111',
     'started_at': 'x', 'limit_unit': 'page'},  # the previous skill version's header
    {'id': 'not a header'},
])
def test_foreign_or_older_files_are_refused_byte_identical(tmp_path, first_line):
    path = tmp_path / 'out.ndjson'
    if first_line is None:
        committed(path, Y, ([{'id': 'A'}], {'cursor': 'C'}, None))
    else:
        path.write_text(json.dumps(first_line) + '\n' + json.dumps({'id': 'A'}) + '\n')
    before = path.read_bytes()
    with pytest.raises(TwitterError) as error:
        collection.OutFile(path, X)
    assert error.value.code == 2
    assert path.read_bytes() == before


def test_integrity_failure_is_refused_byte_identical(tmp_path):
    path = tmp_path / 'out.ndjson'
    committed(path, X, ([{'id': 'A'}, {'id': 'B'}], {'cursor': 'C'}, None))
    text = path.read_text().replace('"ids":["A","B"],"n":2', '"ids":["A"],"n":1')
    path.write_text(text)
    before = path.read_bytes()
    with pytest.raises(TwitterError) as error:
        collection.OutFile(path, X)
    assert error.value.code == 2 and 'integrity' in error.value.message
    assert path.read_bytes() == before


def test_complete_file_is_reported_complete(tmp_path):
    path = tmp_path / 'out.ndjson'
    committed(path, X, ([{'id': 'A'}], {'cursor': None}, 'exhausted'))
    out = collection.OutFile(path, X)
    assert out.complete and out.count == 1
    out.close()


def test_records_already_saved_are_not_written_again(tmp_path):
    path = tmp_path / 'out.ndjson'
    committed(path, X, ([{'id': 'A'}], {'cursor': 'C1'}, None), ([{'id': 'A'}, {'id': 'B'}], {'cursor': 'C2'}, None))
    assert [r['id'] for r in lines(path) if 'id' in r] == ['A', 'B']


def test_a_concurrent_writer_is_refused_at_once(tmp_path):
    path = tmp_path / 'out.ndjson'
    collection.OutFile(path, X).close()
    with open(path, 'r+b') as other:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(TwitterError) as error:
            collection.OutFile(path, X)
    assert error.value.code == 2


def test_parents_are_counted_apart_from_replies(tmp_path):
    path = tmp_path / 'out.ndjson'
    context = {'command': 'comments', 'target': 'u', 'sort': 'all', 'account_id': '1'}
    committed(path, context, ([{'id': 'P1', 'depth': 0}, {'id': 'R1', 'depth': 1}, {'id': 'P2', 'depth': 0}],
                              {'cursor': 'C'}, None))
    out = collection.OutFile(path, context)
    assert out.count == 3 and out.parent_count == 2
    out.close()


def test_skipped_ids_are_remembered(tmp_path):
    path = tmp_path / 'out.ndjson'
    out = collection.OutFile(path, X)
    out.commit([{'id': 'A'}], {'cursor': 'C'}, None, skipped=['AD1'], notes=['a note'])
    out.close()
    marker = lines(path)[-1]
    assert marker['skipped'] == ['AD1'] and marker['coverage'] == ['a note']
    reopened = collection.OutFile(path, X)
    assert reopened.skipped == {'AD1'}
    reopened.close()


def test_unwritable_location_is_an_argument_error(tmp_path):
    with pytest.raises(TwitterError) as error:
        collection.OutFile(tmp_path / 'missing-dir' / 'out.ndjson', X)
    assert error.value.code == 2


def test_a_corrupted_line_inside_a_committed_page_is_refused_unchanged(tmp_path):
    """Review finding 4: only a tail after the last page marker may be dropped."""
    path = tmp_path / 'out.ndjson'
    committed(path, X, ([{'id': 'A'}], {'cursor': 'C1'}, None), ([{'id': 'B'}], {'cursor': 'C2'}, None))
    text = path.read_text().replace('{"id":"B"}', '{"id":"B"')
    path.write_text(text)
    before = path.read_bytes()
    with pytest.raises(TwitterError) as error:
        collection.OutFile(path, X)
    assert error.value.code == 2 and 'integrity' in error.value.message
    assert path.read_bytes() == before


def test_peek_reads_a_files_query_and_completeness_without_changing_it(tmp_path):
    path = tmp_path / 'out.ndjson'
    committed(path, X, ([{'id': 'A'}], {'cursor': None}, 'exhausted'))
    before = path.read_bytes()
    assert collection.peek(path) == (X, True, 1)
    assert collection.peek(tmp_path / 'missing.ndjson') == (None, False, 0)
    assert path.read_bytes() == before


def test_a_symlinked_out_path_is_refused_and_its_target_untouched(tmp_path):
    target = tmp_path / 'elsewhere.txt'
    target.write_text('')  # an empty target would otherwise receive a header through the link
    link = tmp_path / 'out.ndjson'
    link.symlink_to(target)
    with pytest.raises(TwitterError) as error:
        collection.OutFile(link, X)
    assert error.value.code == 2
    assert target.read_text() == ''


def test_a_file_from_the_previous_twitter_skill_is_refused_byte_identical(tmp_path):
    # the previous skill's header: {"kind": "header", "format": 2, ...the query context flat, viewer_id}
    path = tmp_path / 'old.ndjson'
    old = (json.dumps({'kind': 'header', 'format': 2, 'command': 'user', 'target': 'example_user', 'tab': 'posts',
                       'viewer_id': '1000000099'}) + '\n'
           + json.dumps({'id': '1850000000000000001', 'kind': 'tweet'}) + '\n'
           + json.dumps({'kind': 'page', 'ids': ['1850000000000000001'], 'n': 1, 'state': {}, 'stop_reason': 'exhausted'})
           + '\n')
    path.write_text(old)
    with pytest.raises(TwitterError) as error:
        collection.OutFile(path, X)
    assert error.value.code == 2 and 'earlier version' in error.value.message
    assert path.read_text() == old
