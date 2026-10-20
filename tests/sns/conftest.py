import os

import pytest

# Variables of the sns skill and of the five skills it replaces: a value left in the shell must never reach a test.
_SCRUBBED = ('SNS_', 'TWITTER_', 'THREADS_', 'REDDIT_', 'FACEBOOK_', 'NAVER_BLOG_')


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith(_SCRUBBED) and not name.startswith(('SNS_LIVE', 'SNS_WORK')):  # set on purpose by a run
            monkeypatch.delenv(name)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    path = tmp_path / 'data'
    monkeypatch.setenv('SNS_DATA_DIR', str(path))
    return path


def pytest_collection_modifyitems(config, items):
    """A live test runs only when SNS_LIVE names its platform (or says all)."""
    wanted = {name.strip() for name in os.environ.get('SNS_LIVE', '').split(',') if name.strip()}
    for item in items:
        marker = item.get_closest_marker('live')
        if marker is None:
            continue
        platform = marker.args[0] if marker.args else None
        if not wanted or ('all' not in wanted and platform not in wanted):
            item.add_marker(pytest.mark.skip(reason='live: set SNS_LIVE=<platform>[,…] or all'))
