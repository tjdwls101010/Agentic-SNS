"""schema: one JSON document per object, taken from the declarations the code runs on."""
import ast
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from facebook.graphql.records import SCHEMAS, about_fields, comment_page, post_page, search_page
from tests.facebook.helpers import SKILL, Account

NOW = datetime(2026, 9, 5, tzinfo=UTC)
FIXTURES = Path(__file__).with_name('fixtures')
OBJECTS = ['result', 'out', 'post', 'comment', 'entity', 'about']


def declared(path, name):
    """Keys of a module-level dict literal, read from source without importing it."""
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
    raise AssertionError(name)


def schema(tmp_path, *args):
    result = Account(tmp_path).run('schema', *args)
    assert result.code == 0 and result.calls == []
    return result.data['results']


def test_schema_without_an_object_lists_every_object_with_one_line(tmp_path):
    listed = schema(tmp_path)
    assert [entry['object'] for entry in listed] == OBJECTS
    assert all(isinstance(entry['description'], str) and '\n' not in entry['description'] for entry in listed)


def test_result_schema_carries_the_declared_stop_reasons_exit_codes_and_window_table(tmp_path):
    result = schema(tmp_path, 'result')[0]
    outcome = SKILL / 'scripts/facebook/outcome.py'
    cli = SKILL / 'scripts/cli.py'
    assert set(result['stop_reasons']) == {k.value for k in declared(outcome, 'STOP_REASONS').keys}
    assert [row['exit'] for row in result['exit_codes']] == [k.value for k in declared(cli, 'EXIT_CODES').keys]
    assert len(result['window_coverage']) == len(declared(outcome, 'COVERAGE').elts)
    kinds = {k.value for k in declared(outcome, 'KINDS').keys}
    assert {kind for row in result['exit_codes'] for kind in row['kinds']} == kinds
    assert {'?', 'unavailable', 'text[N of M chars shown, complete|truncated]', 'pinned', 'undated', 'incomplete',
            'sponsored', 'attachment='} <= set(result['text_markers'])
    assert result['text_header'].startswith('<command>')
    for value in [*result['fields'].values(), *result['stop_reasons'].values(), *result['text_markers'].values()]:
        assert isinstance(value, str) and '\n' not in value


def test_out_schema_names_its_control_records_and_format(tmp_path):
    out = schema(tmp_path, 'out')[0]
    assert out['format'] == 2
    assert set(out['control_records']) == {'header', 'page'}
    assert 'resume' in out


@pytest.mark.parametrize('name', ['post', 'comment', 'entity', 'about'])
def test_record_schemas_are_one_line_type_and_meaning_per_field(tmp_path, name):
    entry = schema(tmp_path, name)[0]
    assert entry['object'] == name and entry['fields'] == SCHEMAS[name]['fields']
    for description in entry['fields'].values():
        kind, meaning = description.split(' — ', 1)
        assert kind and meaning and '\n' not in description


def flat_keys(record, prefix=''):
    keys = set()
    for key, value in record.items():
        keys.add(prefix + key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            for item in value:
                keys |= flat_keys(item, prefix + key + '[].')
        elif key == 'shared_post' and isinstance(value, dict):
            keys |= flat_keys(value, prefix)
    return keys


def reachable():
    posts, comments = set(), set()
    for path in FIXTURES.glob('*.ndjson'):
        raw = path.read_bytes()
        for record in post_page(raw, source='newsfeed', connection_key='x', captured_at=NOW).records:
            posts |= flat_keys(record)
        for record in comment_page(raw, post_id='p', captured_at=NOW, parents_only=False).records:
            comments |= flat_keys(record)
    entity = json.dumps({'data': {'serpResponse': {'results': {'edges': [{'node': {
        '__typename': 'Page', 'id': '1', 'name': 'x', 'url': 'https://www.facebook.com/x', 'is_verified': True}}]}}}})
    entities = set().union(*(flat_keys(r) for r in search_page(entity.encode(), search_type='pages',
                                                               captured_at=NOW).records))
    section = json.dumps({'data': {'user': {'about_app_sections': {'nodes': [{
        'field_section_type': 'directory_work', 'profile_fields': {'nodes': [
            {'field_type': 'work', 'title': {'text': 'x'}, 'link_url': 'https://example.test'}]}}]}}}}).encode()
    about = set().union(*(flat_keys(r) for r in about_fields([section], profile_id='1', collection_names=[None],
                                                            captured_at=NOW)))
    return {'post': posts, 'comment': comments, 'entity': entities, 'about': about}


def test_every_emitted_field_is_described_and_every_description_is_reachable():
    keys = reachable()
    for name in ('post', 'comment', 'entity', 'about'):
        assert set(SCHEMAS[name]['fields']) == keys[name], name


def test_post_records_carry_no_raw_payload_and_no_duplicate_pinned_flag():
    record = post_page((FIXTURES / 'basic_status_post.ndjson').read_bytes(), source='newsfeed', connection_key='x',
                       captured_at=NOW).records[0]
    assert 'raw' not in record and 'is_pinned' not in record and 'pinned' in record


def test_media_urls_are_described_as_signed_and_expiring():
    assert SCHEMAS['post']['fields']['media[].url'] == ('string — signed, expiring, viewer-scoped; share only when '
                                                        'the user needs the media')


MAINTAINER = ('plan §', 'include_raw', 'fetch output', 'belongs to the caller', 'never raw captures', 'recon §')


def test_text_the_model_reads_carries_no_maintainer_notes(tmp_path):
    account = Account(tmp_path)
    texts = [account.run('--help').stdout]
    commands = ['feed', 'profile', 'group', 'post', 'comments', 'search', 'about', 'doctor', 'refresh', 'schema']
    texts += [account.run(command, '--help').stdout for command in commands]
    texts += [account.run('schema', *([name] if name else [])).stdout for name in [None, *OBJECTS]]
    fixes = declared(SKILL / 'scripts/facebook/outcome.py', 'FIXES')
    texts += [value.value for value in fixes.values]
    for text in texts:
        assert not [phrase for phrase in MAINTAINER if phrase in text], text[:200]
