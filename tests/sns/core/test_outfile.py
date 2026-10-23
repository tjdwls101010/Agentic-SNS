"""--out files (sns.outfile): whole pages committed, resumed, judged once, refused when foreign or unsafe."""
import json
import os

import pytest

from sns import outfile
from sns.errors import SnsError

CONTEXT = {'platform': 'reddit', 'command': 'sub', 'target': 'r/python', 'identity': {'sort': 'new'},
           'aside_account': 'u0'}


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_pages_are_committed_with_a_marker_and_resume_drops_an_unfinished_tail(tmp_path, data_dir):
    path = tmp_path / 'out.ndjson'
    out = outfile.OutFile(path, CONTEXT, viewer='alice')
    out.commit([{'id': 'a'}, {'id': 'b'}], {'cursor': 'C1'}, None)
    out.close()
    with open(path, 'a') as stream:
        stream.write('{"id": "c"}\n{"id": "d", "trunc')
    again = outfile.OutFile(path, CONTEXT, viewer='alice')
    assert again.count == 2 and again.ids == {'a', 'b'} and again.state == {'cursor': 'C1'} and not again.complete
    again.commit([{'id': 'b'}, {'id': 'c'}], None, 'exhausted')  # a saved id is never written twice
    again.close()
    records = [line for line in lines(path) if line.get('kind') not in ('header', 'page')]
    assert [r['id'] for r in records] == ['a', 'b', 'c']
    header = lines(path)[0]
    assert header['kind'] == 'header' and header['platform'] == 'reddit' and header['format'] == outfile.FORMAT


def test_a_final_marker_is_repeated_by_peek_and_an_interrupted_one_resumes(tmp_path, data_dir):
    path = tmp_path / 'out.ndjson'
    out = outfile.OutFile(path, CONTEXT)
    out.commit([{'id': 'a'}], {'cursor': 'C1'}, None)
    out.interrupt('time_limit')
    out.close()
    peeked = outfile.peek(path)
    assert peeked['complete'] is False and peeked['count'] == 1 and peeked['last_stop'] == 'time_limit'
    out = outfile.OutFile(path, CONTEXT)
    out.commit([{'id': 'b'}], None, None)
    out.conclude('exhausted', {'kind': 'partial', 'message': 'The listing ended before the window.', 'fix': 'x',
                               'reason': 'listing_ended'}, {'since': '2026-10-01'})
    out.close()
    peeked = outfile.peek(path)
    assert peeked['complete'] and peeked['count'] == 2 and peeked['conclusion']['verdict']['reason'] == 'listing_ended'
    assert peeked['conclusion']['window'] == {'since': '2026-10-01'} and peeked['context'] == CONTEXT


def test_a_file_of_another_query_or_version_is_refused_before_any_byte_changes(tmp_path, data_dir):
    path = tmp_path / 'out.ndjson'
    outfile.OutFile(path, CONTEXT).close()
    before = path.read_bytes()
    with pytest.raises(SnsError) as caught:
        outfile.OutFile(path, {**CONTEXT, 'target': 'r/rust'})
    assert caught.value.kind == 'argument'
    other = tmp_path / 'old.ndjson'
    other.write_text(json.dumps({'kind': 'header', 'format': 0, 'context': CONTEXT}) + '\n')
    with pytest.raises(SnsError) as caught:
        outfile.OutFile(other, CONTEXT)
    assert 'earlier version' in caught.value.message
    assert path.read_bytes() == before


def test_another_platform_account_is_a_changed_login(tmp_path, data_dir):
    path = tmp_path / 'out.ndjson'
    outfile.OutFile(path, CONTEXT, viewer='alice').close()
    with pytest.raises(SnsError) as caught:
        outfile.OutFile(path, CONTEXT, viewer='bob')
    assert caught.value.kind == 'login' and caught.value.reason == 'account_changed'


def test_a_damaged_committed_page_fails_the_integrity_check(tmp_path, data_dir):
    path = tmp_path / 'out.ndjson'
    out = outfile.OutFile(path, CONTEXT)
    out.commit([{'id': 'a'}, {'id': 'b'}], {'cursor': 'C1'}, None)
    out.close()
    text = path.read_text().replace('"id":"b"', '"id":"z"')
    path.write_text(text)
    with pytest.raises(SnsError) as caught:
        outfile.OutFile(path, CONTEXT)
    assert 'integrity' in caught.value.message


def test_links_are_refused_and_the_file_is_private_and_locked(tmp_path, data_dir):
    real = tmp_path / 'real.ndjson'
    real.write_text('')
    link = tmp_path / 'link.ndjson'
    link.symlink_to(real)
    with pytest.raises(SnsError):
        outfile.OutFile(link, CONTEXT)
    hard = tmp_path / 'hard.ndjson'
    os.link(real, hard)
    with pytest.raises(SnsError):
        outfile.OutFile(hard, CONTEXT)
    path = tmp_path / 'out.ndjson'
    first = outfile.OutFile(path, CONTEXT)
    assert path.stat().st_mode & 0o077 == 0
    with pytest.raises(SnsError):
        outfile.OutFile(path, CONTEXT)
    first.close()


def test_a_nested_record_cannot_be_saved(tmp_path, data_dir):
    out = outfile.OutFile(tmp_path / 'out.ndjson', CONTEXT)
    with pytest.raises(SnsError):
        out.commit([{'id': 'a', 'replies': [{'id': 'b'}]}], None, None)
    out.close()


def test_a_path_inside_data_or_in_a_missing_directory_is_refused_before_any_request(tmp_path, data_dir):
    with pytest.raises(SnsError) as caught:
        outfile.check_path(data_dir / 'x.ndjson')
    assert 'data/' in caught.value.message
    with pytest.raises(SnsError) as caught:
        outfile.check_path(tmp_path / 'missing' / 'x.ndjson')
    assert caught.value.kind == 'argument'
    outfile.check_path(tmp_path / 'fine.ndjson')


def test_peek_of_a_missing_or_empty_file_is_nothing(tmp_path, data_dir):
    assert outfile.peek(tmp_path / 'none.ndjson') is None
    (tmp_path / 'empty.ndjson').write_text('')
    assert outfile.peek(tmp_path / 'empty.ndjson') is None
