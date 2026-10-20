import time

import pytest

from tests.sns.reddit.scene import Scene


@pytest.fixture
def reddit(tmp_path, monkeypatch, capsys, data_dir):
    """A scripted Reddit behind the fake Aside; time zone UTC unless a test names another."""
    monkeypatch.setenv('SNS_IDLE_SECONDS', 'off')
    monkeypatch.setenv('TZ', 'UTC')
    time.tzset()
    yield Scene(tmp_path / 'scene', monkeypatch, capsys)
    monkeypatch.undo()
    time.tzset()
