import json
import sys
import pytest
from twitter_skill._aside import run_snippet
from twitter_skill._errors import TwitterError


@pytest.mark.parametrize('chunked', [False, True])
def test_real_subprocess_contract_and_chunk_reassembly(tmp_path, monkeypatch, chunked):
    body = '{"data":{"message":"synthetic ⏎ body"}}'
    envelope = {'status': 200, 'url': 'https://x.com/', 'body': body}
    records = [envelope]
    if chunked:
        records = [{'kind': 'body_chunk', 'index': 0, 'body': body[:10]},
                   {'kind': 'body_chunk', 'index': 1, 'body': body[10:]},
                   {'status': 200, 'url': 'https://x.com/', 'body_chunks': 2}]
    binary = tmp_path / 'aside'
    binary.write_text('#!' + sys.executable + '\nimport sys\n'
                      'assert sys.argv[1:4] == ["--account", "u0", "repl"]\n'
                      'assert "twitter-snippet: graphql" in sys.argv[4]\n'
                      'print(' + repr('\n'.join(json.dumps(record) for record in records)) + ')\n')
    binary.chmod(0o700)
    monkeypatch.setenv('TWITTER_ASIDE_BIN', str(binary))
    assert run_snippet('graphql', {})['body'] == body


@pytest.mark.parametrize('records', [
    [{'status': 200, 'url': 'https://x.com/', 'body_file': '/etc/passwd'}],
    [{'kind': 'body_chunk', 'index': 1, 'body': 'x'}, {'status': 200, 'url': 'https://x.com/', 'body_chunks': 1}],
    [{'status': True, 'url': 'https://x.com/', 'body': ''}],
])
def test_untrusted_envelope_is_rejected_without_raw_output(tmp_path, monkeypatch, records):
    binary = tmp_path / 'aside'
    binary.write_text('#!' + sys.executable + '\nprint(' + repr('\n'.join(json.dumps(r) for r in records)) + ')\n')
    binary.chmod(0o700)
    monkeypatch.setenv('TWITTER_ASIDE_BIN', str(binary))
    with pytest.raises(TwitterError) as exc:
        run_snippet('graphql', {})
    assert exc.value.code == 3
    assert '/etc/passwd' not in str(exc.value)
