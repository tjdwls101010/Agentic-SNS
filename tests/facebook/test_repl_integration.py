"""Aside's own stdout framing and failures, as the CLI receives them from the aside process."""
import json
import shutil

import pytest

from tests.facebook.helpers import CLI, Account, feed_page, login


def raw(*lines, exit=0):
    return {'raw_stdout': ''.join(line + '\n' for line in lines), 'exit': exit}


def test_aside_ok_footer_is_not_mistaken_for_response_json(tmp_path):
    result = Account(tmp_path).run('doctor', responses=[raw(json.dumps(login()), '\x1b[2m[ok | 10ms]\x1b[0m')])
    assert result.code == 0, result.stdout


def test_browser_operation_status_lines_do_not_hide_a_valid_envelope(tmp_path):
    result = Account(tmp_path).run('doctor', responses=[raw('Opened tab synthetic', json.dumps(login()),
                                                            '[ok | 1m 2s]')])
    assert result.code == 0, result.stdout


def test_chunked_envelope_is_reassembled_without_writing_a_response_file(tmp_path):
    body = feed_page(['p1'])['body']
    middle = len(body) // 2
    records = [{'kind': 'body_chunk', 'index': 0, 'body': body[:middle]},
               {'kind': 'body_chunk', 'index': 1, 'body': body[middle:]},
               {'status': 200, 'url': 'https://www.facebook.com/api/graphql/', 'body': '', 'body_chunks': 2}]
    result = Account(tmp_path).run('feed', '--json', responses=[login(), raw(*map(json.dumps, records))])
    assert result.code == 0 and result.ids == ['p1']


@pytest.mark.parametrize('records', [
    [{'kind': 'body_chunk', 'index': 1, 'body': 'x'}, {'status': 200, 'url': 'https://www.facebook.com/', 'body': '',
                                                        'body_chunks': 1}],
    [{'kind': 'body_chunk', 'index': 0, 'body': 'x'}, {'status': 200, 'url': 'https://www.facebook.com/', 'body': '',
                                                        'body_chunks': 2}],
    [{'status': 200, 'url': 'https://www.facebook.com/', 'body': 'a'},
     {'status': 200, 'url': 'https://www.facebook.com/', 'body': 'b'}],
    [{'status': 'ok', 'url': 'https://www.facebook.com/', 'body': 'a'}],
])
def test_inconsistent_envelopes_are_rejected_as_an_aside_failure(tmp_path, records):
    result = Account(tmp_path).run('feed', responses=[login(), raw(*map(json.dumps, records))])
    assert result.code == 3
    assert result.data['message'] == 'Aside returned an invalid response envelope.'


def test_unexpected_file_envelope_cannot_read_local_files(tmp_path):
    body_file = tmp_path / 'facebook-response-private.ndjson'
    body_file.write_text('private')
    envelope = {'status': 200, 'url': 'https://www.facebook.com/api/graphql/', 'body': '', 'body_file': str(body_file)}
    result = Account(tmp_path).run('feed', responses=[login(), raw(json.dumps(envelope))])
    assert result.code == 3
    assert 'private' not in result.stdout
    assert body_file.read_text() == 'private'


@pytest.mark.parametrize('mode,message', [
    ('fail', 'Aside request failed.'),
    ('timeout', 'Aside request ended at the REPL time limit or lost its connection.'),
    ('malformed', 'Aside returned an invalid response envelope.'),
    ('duplicate', 'Aside returned an invalid response envelope.'),
])
def test_process_failures_never_disclose_source_or_arguments(tmp_path, mode, message):
    result = Account(tmp_path).run('feed', responses=[login(dtsg='SECRET-&+한'), {**feed_page(['p1']), 'mode': mode}])
    assert result.code == 3
    assert result.data['message'] == message
    assert 'SECRET' not in result.stdout + result.stderr
    assert 'ARGS' not in result.stdout + result.stderr and 'fetch(' not in result.stdout + result.stderr


def test_missing_aside_executable_is_an_aside_failure(tmp_path):
    result = Account(tmp_path).run('doctor', env={'FACEBOOK_ASIDE_BIN': str(tmp_path / 'absent')})
    assert result.code == 3 and result.data['message'] == 'Aside could not run.'


def test_missing_bundled_snippet_fails_before_contacting_aside(tmp_path):
    skill = tmp_path / 'copy' / 'facebook'
    shutil.copytree(CLI.parents[1], skill, ignore=shutil.ignore_patterns('__pycache__'))
    (skill / 'scripts/facebook/graphql/snippets/graphql.js').unlink()
    result = Account(tmp_path, skill / 'scripts/cli.py').run('feed', responses=[login(), feed_page(['p1'])])
    assert result.code == 3
    assert result.data['message'] == 'Browser snippet is missing or invalid.'
    assert result.snippets == ['tokens'] and result.left == 1
