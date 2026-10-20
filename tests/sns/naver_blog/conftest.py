import time

import pytest

from tests.sns.naver_blog.scene import Scene


@pytest.fixture
def naver(tmp_path, monkeypatch, capsys, data_dir):
    """A scripted Naver Blog behind the fake Aside; time zone UTC (Naver's days are KST whatever the computer says)."""
    monkeypatch.setenv('SNS_IDLE_SECONDS', 'off')
    monkeypatch.setenv('TZ', 'UTC')
    time.tzset()
    yield Scene(tmp_path / 'scene', monkeypatch, capsys, data_dir)
    monkeypatch.undo()
    time.tzset()
