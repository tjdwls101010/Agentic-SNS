from pathlib import Path

import pytest

from _errors import FacebookError


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setenv('FACEBOOK_ASIDE_BIN', str(Path(__file__).with_name('fake_aside') / 'aside'))


def test_process_returns_one_envelope():
    from _aside import run_snippet
    assert run_snippet('tokens', {}) == {'status': 200, 'url': 'https://www.facebook.com/', 'body': 'synthetic'}


@pytest.mark.parametrize('mode', ['fail', 'timeout', 'malformed', 'duplicate'])
def test_process_failures_never_disclose_source_or_arguments(monkeypatch, mode):
    from _aside import run_snippet
    monkeypatch.setenv('FAKE_ASIDE_MODE', mode)
    with pytest.raises(FacebookError) as error:
        run_snippet('tokens.js', {'token': 'SECRET-&+한'})
    assert error.value.code == 3
    assert 'SECRET' not in str(error.value)
    assert 'ARGS' not in str(error.value)
    assert error.value.__cause__ is None
