import json
from pathlib import Path
import pytest
from reddit_skill._aside import run_snippet
from reddit_skill._errors import RedditError

FAKE = str(Path(__file__).parent / 'fake_aside/aside')


def test_real_process_envelope_and_chunks(monkeypatch):
    monkeypatch.setenv('REDDIT_ASIDE_BIN', FAKE)
    assert run_snippet('fetch', {'path': '/hot.json'})['status'] == 200
    records = [{'kind': 'body_chunk', 'index': 0, 'body': '{"x":'},
               {'kind': 'body_chunk', 'index': 1, 'body': '1}'},
               {'status': 200, 'url': 'https://www.reddit.com/hot.json', 'body': '',
                'body_chunks': 2, 'ratelimit': {'remaining': '0', 'used': '100', 'reset': '10'}}]
    monkeypatch.setenv('REDDIT_FAKE_OUTPUT', '\n'.join(map(json.dumps, records)))
    assert run_snippet('fetch', {'path': '/hot.json'})['body'] == '{"x":1}'


@pytest.mark.parametrize('output', ['{}', 'not json', '{"status":true}',
    '{"status":200,"url":"x","body":"x","ratelimit":[]}',
    '{"status":200,"url":"x","body":"x","ratelimit":{},"location":42}',
    '{"status":200,"url":"x","body":"","ratelimit":{},"body_chunks":1}'])
def test_malformed_bridge_is_safe_error(monkeypatch, output):
    monkeypatch.setenv('REDDIT_ASIDE_BIN', FAKE)
    monkeypatch.setenv('REDDIT_FAKE_OUTPUT', output)
    with pytest.raises(RedditError) as caught:
        run_snippet('fetch', {'path': '/hot.json'})
    assert caught.value.code == 3


def test_process_failure_never_exposes_diagnostics(monkeypatch):
    monkeypatch.setenv('REDDIT_ASIDE_BIN', FAKE)
    monkeypatch.setenv('REDDIT_FAKE_EXIT', '1')
    with pytest.raises(RedditError) as caught:
        run_snippet('fetch', {'path': '/hot.json'})
    assert caught.value.code == 3
    assert 'secret' not in str(caught.value.as_dict())


def test_invalid_snippet_cannot_escape_directory():
    with pytest.raises(RedditError):
        run_snippet('../_errors.py', {})


def test_timeout_is_translated_at_external_process_boundary(monkeypatch):
    import subprocess
    monkeypatch.setenv('REDDIT_ASIDE_BIN', FAKE)
    def timeout(*args, **kwargs):
        assert kwargs['timeout'] == 125
        raise subprocess.TimeoutExpired('aside', 125, output='cookie=secret')
    monkeypatch.setattr(subprocess, 'run', timeout)
    with pytest.raises(RedditError) as caught:
        run_snippet('fetch', {'path': '/hot.json'})
    assert caught.value.code == 3
    assert '120-second' in caught.value.message
    assert 'secret' not in str(caught.value.as_dict())


def test_misordered_chunks_are_rejected(monkeypatch):
    monkeypatch.setenv('REDDIT_ASIDE_BIN', FAKE)
    monkeypatch.setenv('REDDIT_FAKE_OUTPUT', '\n'.join(map(json.dumps, [
        {'kind': 'body_chunk', 'index': 1, 'body': 'secret'},
        {'status': 200, 'url': 'https://www.reddit.com/hot.json', 'body': '', 'body_chunks': 1, 'ratelimit': {}}])))
    with pytest.raises(RedditError) as caught:
        run_snippet('fetch', {'path': '/hot.json'})
    assert caught.value.code == 3
    assert 'secret' not in str(caught.value.as_dict())
