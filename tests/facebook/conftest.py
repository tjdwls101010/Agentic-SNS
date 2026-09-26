"""Isolate runtime state; only explicitly selected live tests use the account."""
import pytest


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path, request):
    if request.node.get_closest_marker('live') is None:
        monkeypatch.setenv('FACEBOOK_HOME', str(tmp_path / 'state'))
