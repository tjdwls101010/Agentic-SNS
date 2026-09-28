"""The command surface: help, argument refusals before any request, doctor, schema against real results."""
import json
import os
import sys
from pathlib import Path

import pytest

from .fixtures.builders import collections, envelope, preloader, route
from .helpers import POST, calls, data, run_cli, run_more

COMMANDS = ('home', 'user', 'about', 'post', 'graph', 'search', 'me', 'doctor', 'refresh', 'schema')


def test_help_names_every_command_and_each_command_explains_itself():
    result = run_cli('--help')
    assert result.returncode == 0
    for command in COMMANDS:
        assert command in result.stdout
        assert run_cli(command, '--help').returncode == 0
    assert '--unblock' in run_cli('doctor', '--help').stdout


def test_invalid_arguments_are_one_json_document_without_browser(fake_aside):
    result = run_cli('user', '/activity', '--json')
    assert result.returncode == 2
    assert data(result)['error'] == 'arguments'
    assert result.stderr == ''
    assert calls(fake_aside) == []


@pytest.mark.parametrize('arguments', [
    ('search', 'python', '--type', 'users', '--tag'),
    ('search', 'python', '--type', 'users', '--sort', 'recent'),
    ('home', '--since', '2026-01-01'),
    ('user', '@fixture_user', '--since', '2026-02-01', '--until', '2026-01-01'),
    ('user', '@fixture_user', '--since', 'yesterday'),
    ('home', '--chars', '-1'),
    ('post', 'https://example.com/@fixture_user/post/FIX_2'),
])
def test_refused_arguments_make_no_request(fake_aside, arguments):
    result = run_cli(*arguments, '--json')
    assert result.returncode == 2, result.stdout
    assert calls(fake_aside) == []


def test_doctor_through_a_separate_aside_process(tmp_path, monkeypatch):
    page = route([preloader('BarcelonaProfilePageDirectQuery', userID='42', flag={'nested': 'a}b'})])
    binary = tmp_path / 'aside'
    binary.write_text('#!' + sys.executable + '\nimport json\nprint(' + repr(json.dumps(page)) + ')\n')
    binary.chmod(0o700)
    monkeypatch.setenv('THREADS_ASIDE_BIN', str(binary))
    result = run_cli('doctor', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    body = data(result)
    assert body['viewer'] == 'fixture_viewer' and body['budget']['used'] == 1
    assert 'synthetic-csrf' not in result.stdout
    assert os.stat(Path(os.environ['THREADS_HOME']) / 'budget.json').st_mode & 0o777 == 0o600


@pytest.mark.parametrize('body,code,error', [
    ('<html><title>Threads</title></html>', 6, 'transient'),
    ('<script>"DTSGInitialData",[],{}</script>', 4, 'login'),
    ('<script>"DTSGInitialData",[],{"csrf_token":"fixture","NON_FACEBOOK_USER_ID":"42","username":"fixture"}</script>',
     6, 'envelope_drift'),
], ids=['shell', 'logged-out', 'no-relay'])
def test_doctor_tells_a_logged_out_page_from_an_unrecognised_one(routes, body, code, error):
    routes.set('/', envelope(body, url='https://www.threads.com/')).write()
    result = run_cli('doctor')
    assert (result.returncode, data(result)['error']) == (code, error)


def test_account_search_more_command_is_executable(routes):
    collections(routes).write()
    first = data(run_cli('search', 'python', '--type', 'users', '--limit', '1', '--json'))
    next_page = run_more(first['next'])
    assert next_page.returncode == 0, next_page.stdout + next_page.stderr
    assert [u['id'] for u in data(next_page)['results']] == ['43', '44']


def test_schema_describes_every_field_a_post_read_returns(fake_aside):
    schema = data(run_cli('schema'))['$defs']['Post']
    for post in data(run_cli('post', POST, '--json'))['results']:
        assert set(post) <= schema['properties'].keys()
    assert schema['properties']['reply_to_id']['anyOf'] == [{'type': 'string'}, {'type': 'null'}]
