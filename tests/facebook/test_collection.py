"""collection: --out files on the real filesystem (fixtures/stores.json, collection)."""
import fcntl
import json

import pytest

from facebook import collection
from facebook.errors import FacebookError

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
    with pytest.raises(FacebookError) as error:
        collection.OutFile(path, X)
    assert error.value.code == 2
    assert path.read_bytes() == before


def test_integrity_failure_is_refused_byte_identical(tmp_path):
    path = tmp_path / 'out.ndjson'
    committed(path, X, ([{'id': 'A'}, {'id': 'B'}], {'cursor': 'C'}, None))
    text = path.read_text().replace('"ids":["A","B"],"n":2', '"ids":["A"],"n":1')
    path.write_text(text)
    before = path.read_bytes()
    with pytest.raises(FacebookError) as error:
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
        with pytest.raises(FacebookError) as error:
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
    with pytest.raises(FacebookError) as error:
        collection.OutFile(tmp_path / 'missing-dir' / 'out.ndjson', X)
    assert error.value.code == 2
