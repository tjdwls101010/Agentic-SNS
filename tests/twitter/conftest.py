import json
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
SKILL = REPO / '.claude/skills/twitter'
CLI = SKILL / 'scripts/cli.py'
FIXTURES = TESTS / 'fixtures'


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    path = tmp_path / 'data'
    monkeypatch.setenv('TWITTER_DATA_DIR', str(path))
    return path
