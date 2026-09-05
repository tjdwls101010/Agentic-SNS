"""Observed Aside process output contracts, independent of canned API responses."""
import json
import sys


def test_aside_ok_footer_is_not_mistaken_for_response_json(tmp_path, monkeypatch):
    from _aside import run_snippet
    executable = tmp_path / 'aside'
    envelope = {'status': 200, 'url': 'https://www.facebook.com/', 'body': 'synthetic'}
    executable.write_text('#!' + sys.executable + '\nprint(' + repr(json.dumps(envelope))
                          + ')\nprint("\\x1b[2m[ok | 10ms]\\x1b[0m")\n')
    executable.chmod(0o700)
    monkeypatch.setenv('FACEBOOK_ASIDE_BIN', str(executable))
    assert run_snippet('tokens', {}) == envelope


def test_chunked_envelope_is_reassembled_without_writing_a_response_file(tmp_path, monkeypatch):
    from _aside import run_snippet
    executable = tmp_path / 'aside'
    records = [{'kind': 'body_chunk', 'index': 0, 'body': 'synthetic '},
               {'kind': 'body_chunk', 'index': 1, 'body': 'large response'},
               {'status': 200, 'url': 'https://www.facebook.com/api/graphql/', 'body': '', 'body_chunks': 2}]
    executable.write_text('#!' + sys.executable + '\n' +
                          '\n'.join('print(' + repr(json.dumps(record)) + ')' for record in records) + '\n')
    executable.chmod(0o700)
    monkeypatch.setenv('FACEBOOK_ASIDE_BIN', str(executable))
    assert run_snippet('graphql', {})['body'] == 'synthetic large response'


def test_unexpected_file_envelope_cannot_read_local_files(tmp_path, monkeypatch):
    import pytest
    from _aside import run_snippet
    from _errors import FacebookError
    body_file = tmp_path / 'facebook-response-private.ndjson'
    body_file.write_text('private')
    executable = tmp_path / 'aside'
    envelope = {'status': 200, 'url': 'https://www.facebook.com/api/graphql/', 'body': '',
                'body_file': str(body_file)}
    executable.write_text('#!' + sys.executable + '\nprint(' + repr(json.dumps(envelope)) + ')\n')
    executable.chmod(0o700)
    monkeypatch.setenv('FACEBOOK_ASIDE_BIN', str(executable))
    with pytest.raises(FacebookError):
        run_snippet('graphql', {})
    assert body_file.read_text() == 'private'


def test_browser_operation_status_lines_do_not_hide_a_valid_envelope(tmp_path, monkeypatch):
    from _aside import run_snippet
    executable = tmp_path / 'aside'
    envelope = {'status': 200, 'url': 'https://www.facebook.com/', 'body': '{}'}
    executable.write_text('#!' + sys.executable + '\nprint("Opened tab synthetic")\nprint('
                          + repr(json.dumps(envelope)) + ')\nprint("[ok | 1m 2s]")\n')
    executable.chmod(0o700)
    monkeypatch.setenv('FACEBOOK_ASIDE_BIN', str(executable))
    assert run_snippet('capture', {}) == envelope
