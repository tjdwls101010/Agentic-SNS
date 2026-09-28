"""schema describes what the CLI actually prints and writes: every result kind, every error, every --out line."""
import json
import re

import pytest

from .fixtures.builders import ERRORS, collections, envelope, person, users
from .helpers import POST, data, run_cli

TYPES = {'object': dict, 'array': list, 'string': str, 'boolean': bool, 'null': type(None)}


def problems(value, rule, root, where='$'):
    """Where `value` breaks `rule`, for the JSON Schema subset schema uses."""
    if '$ref' in rule:
        return problems(value, root['$defs'][rule['$ref'].rsplit('/', 1)[1]], root, where)
    if 'anyOf' in rule:
        return [] if any(not problems(value, option, root, where) for option in rule['anyOf']) else [f'{where}: no anyOf']
    found = []
    kinds = rule.get('type')
    if kinds is not None:
        kinds = kinds if isinstance(kinds, list) else [kinds]
        ok = any((kind == 'integer' and type(value) is int) or (kind != 'integer' and type(value) is TYPES[kind]
                                                                  if kind != 'boolean' else type(value) is bool)
                 for kind in kinds)
        if not ok:
            return [f'{where}: {type(value).__name__} is not {kinds}']
    if 'const' in rule and value != rule['const']:
        found.append(f'{where}: {value!r} is not {rule["const"]!r}')
    if 'enum' in rule and value not in rule['enum']:
        found.append(f'{where}: {value!r} not in enum')
    if isinstance(value, dict):
        properties = rule.get('properties', {})
        found += [f'{where}: missing {key}' for key in rule.get('required', []) if key not in value]
        for key, child in value.items():
            if key in properties:
                found += problems(child, properties[key], root, f'{where}.{key}')
            elif rule.get('additionalProperties') is False:
                found.append(f'{where}: unexpected {key}')
            elif isinstance(rule.get('additionalProperties'), dict):
                found += problems(child, rule['additionalProperties'], root, f'{where}.{key}')
    if isinstance(value, list) and 'items' in rule:
        for index, child in enumerate(value):
            found += problems(child, rule['items'], root, f'{where}[{index}]')
    return found


@pytest.fixture
def schema():
    return data(run_cli('schema'))


def check(schema, name, value):
    assert problems(value, {'$ref': f'#/$defs/{name}'}, schema) == []


@pytest.mark.parametrize('arguments', [
    ('home', '--limit', '3'), ('home', '--feed', 'following'), ('user', '@fixture_user', '--since', '2027-01-01'),
    ('about', '@fixture_user'), ('post', POST), ('graph', '@fixture_user', 'following'),
    ('search', 'python', '--limit', '2'), ('search', 'python', '--type', 'users'), ('me', 'liked'),
])
def test_every_read_result_fits_the_read_result_schema(routes, schema, arguments):
    collections(routes)
    routes.set('BarcelonaFriendshipsFollowingTabQuery',
               envelope(users('following', [person(60)], counts={'following': 1}))).write()
    result = run_cli(*arguments, '--json')
    assert result.returncode in (0, 7), result.stdout
    check(schema, 'ReadResult', data(result))


@pytest.mark.parametrize('setup,arguments,kind', [
    (lambda r: r.set('BarcelonaProfileRepliesTabDirectQuery', ERRORS['rotated']), ('user', '@fixture_user', '--tab', 'replies'), 'ReadResult'),
    (lambda r: r.set('/@fixture_user/post/FIX_2', ERRORS['rotated']), ('post', POST), 'Error'),
    (lambda r: r.set('BarcelonaProfileRepliesTabDirectQuery', ERRORS['checkpoint']), ('user', '@fixture_user', '--tab', 'replies'), 'ReadResult'),
    (lambda r: None, ('user', '/activity'), 'Error'),
    (lambda r: r.set('BarcelonaSavedPageViewerQuery', envelope({'data': {'xdt_text_app_viewer': {}}})), ('me', 'saved'),
     'ReadResult'),
])
def test_every_failure_fits_its_schema_and_names_a_documented_kind(routes, schema, setup, arguments, kind):
    setup(routes)
    routes.write()
    body = data(run_cli(*arguments, '--json'))
    check(schema, kind, body)
    assert body['error'] in schema['$defs']['ErrorKind']['enum']


def test_doctor_and_refresh_fit_their_schemas(routes, schema):
    routes.copy('/@fixture_user', '/@fixture_viewer').write()
    check(schema, 'Doctor', data(run_cli('doctor')))
    check(schema, 'Refresh', data(run_cli('refresh', '--post', POST)))


def test_every_line_of_an_out_file_fits_the_out_schema(fake_aside, tmp_path, schema):
    file = tmp_path / 'home.ndjson'
    run_cli('home', '--limit', '2', '--out', str(file), '--json')
    lines = [json.loads(line) for line in file.read_text().splitlines()]
    check(schema, 'OutHeader', lines[0])
    for line in lines[1:]:
        check(schema, 'OutPage' if line.get('kind') == 'page' else 'Post', line)


def test_the_exit_codes_in_schema_are_the_ones_help_lists(schema):
    help_text = run_cli('--help').stdout
    listed = dict(re.findall(r'^  (\d)  (.+)$', help_text, re.M))
    assert listed == schema['exit_codes']


def test_descriptions_say_what_a_field_means_not_its_name_again(schema):
    for name, definition in schema['$defs'].items():
        for key, rule in definition.get('properties', {}).items():
            description = rule.get('description', '')
            assert 'null means unavailable when nullable' not in description, (name, key)
            assert description.lower().rstrip('.') != key.replace('_', ' '), (name, key)
