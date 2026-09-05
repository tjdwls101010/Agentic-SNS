"""Isolate runtime state; only explicitly selected live tests use the account."""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / '.claude/skills/facebook/scripts'
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path, request):
    if request.node.get_closest_marker('live') is None:
        monkeypatch.setenv('FACEBOOK_HOME', str(tmp_path / 'state'))
