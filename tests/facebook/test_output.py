import json

from _output import OutFile

CONTEXT = dict(command='profile', target='4', sort='recent',
               window={'since': None, 'until': None}, account_id='100')


def test_interrupted_page_is_discarded_and_replayed_without_loss_or_duplicates(tmp_path):
    path = tmp_path / 'posts.ndjson'
    out = OutFile(path, CONTEXT)
    out.commit([{'id': '1', 'text': 'first'}], 'next', None)
    out.close()
    with path.open('ab') as stream:
        stream.write(b'{"id":"2","text":"uncommitted"}\n{"id":')
    out = OutFile(path, CONTEXT)
    assert out.cursor == 'next'
    assert out.ids == {'1'}
    out.commit([{'id': '1', 'text': 'duplicate'}, {'id': '2', 'text': 'second'}],
               {'exhausted': True}, 'exhausted')
    out.close()
    out = OutFile(path, CONTEXT)
    assert out.complete
    assert out.count == 2
    out.close()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r['id'] for r in rows if 'id' in r] == ['1', '2']
    assert rows[0]['kind'] == 'header'


def test_wrong_context_never_truncates_an_existing_file(tmp_path):
    import pytest
    from _errors import FacebookError
    path = tmp_path / 'posts.ndjson'
    out = OutFile(path, CONTEXT)
    out.commit([{'id': '1'}], 'next', None)
    out.close()
    before = path.read_bytes()
    with pytest.raises(FacebookError) as error:
        OutFile(path, dict(CONTEXT, target='5'))
    assert error.value.code == 2
    assert path.read_bytes() == before


def test_cursor_ids_increase_and_context_is_validated():
    import pytest
    from _errors import FacebookError
    from _output import CursorStore
    store = CursorStore()
    first = store.save(CONTEXT, 'long-cursor', pending=[{'id': '1'}])
    second = store.save(CONTEXT, 'next')
    assert second > first
    assert store.load(first, CONTEXT)['pending'] == [{'id': '1'}]
    with pytest.raises(FacebookError):
        store.load(first, dict(CONTEXT, sort='top'))
    with pytest.raises(FacebookError):
        store.load('../blocked', CONTEXT)


def test_json_emits_one_document_and_partial_exit_code(capsys):
    from _output import emit
    result = dict(ok=False, results=[{'id': '1'}], stop_reason='budget',
                  message='Request budget reached.', fix='Continue later.', code=8)
    assert emit(result, json_mode=True, command='feed') == 8
    printed = json.loads(capsys.readouterr().out)
    assert printed['results'] == [{'id': '1'}]
    assert printed['stop_reason'] == 'budget'
    assert printed['ok'] is False


def test_honest_empty_result_and_blocked_partial_have_distinct_exits(capsys):
    from _output import emit
    assert emit(dict(ok=True, results=[], stop_reason='exhausted'), json_mode=True) == 7
    assert json.loads(capsys.readouterr().out)['error'] == 'empty'
    assert emit(dict(ok=False, results=[{'id': '1'}], stop_reason='blocked', code=5), json_mode=True) == 5
    assert json.loads(capsys.readouterr().out)['stop_reason'] == 'blocked'


def test_page_limit_on_last_full_page_is_already_complete(tmp_path):
    path = tmp_path / 'last.ndjson'
    output = OutFile(path, CONTEXT)
    output.commit([{'id': '1'}, {'id': '2'}], {'exhausted': True}, 'limit_reached')
    output.close()
    output = OutFile(path, CONTEXT)
    assert output.complete
    output.close()


def test_page_entity_is_a_record_not_a_page_commit_marker(tmp_path):
    path = tmp_path / 'entities.ndjson'
    output = OutFile(path, CONTEXT)
    output.commit([{'id': '123', 'kind': 'page', 'name': 'Example'}], {'exhausted': True}, 'exhausted')
    output.close()
    output = OutFile(path, CONTEXT)
    assert output.count == 1
    assert output.ids == {'123'}
    output.close()


def test_non_object_header_is_a_safe_argument_error_without_modifying_file(tmp_path):
    import pytest
    from _errors import FacebookError
    path = tmp_path / 'broken.ndjson'
    path.write_text('[]\n')
    with pytest.raises(FacebookError) as error:
        OutFile(path, CONTEXT)
    assert error.value.code == 2
    assert path.read_text() == '[]\n'


def test_public_read_stop_reasons_use_the_documented_vocabulary(capsys):
    from _output import emit
    emit(dict(ok=True, results=[], out='synthetic.ndjson', count=6,
              already_complete=True, stop_reason='already_complete'), json_mode=True, command='profile')
    assert json.loads(capsys.readouterr().out)['stop_reason'] == 'exhausted'
    emit(dict(ok=False, results=[{'id': '1'}], code=8, stop_reason='reply_batch_limit'),
         json_mode=True, command='comments')
    assert json.loads(capsys.readouterr().out)['stop_reason'] == 'query_failure'
