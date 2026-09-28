"""Keep independently distributed skills in separate Python namespaces."""
import importlib.util
import sys
from pathlib import Path

import pytest

from .fixtures.builders import Routes

SCRIPTS = Path(__file__).resolve().parents[2] / '.claude/skills/threads/scripts'
spec = importlib.util.spec_from_file_location('threads_skill', SCRIPTS / '__init__.py',
                                            submodule_search_locations=[str(SCRIPTS)])
module = importlib.util.module_from_spec(spec)
sys.modules['threads_skill'] = module
spec.loader.exec_module(module)


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path, request):
    if request.node.get_closest_marker('live') is None:
        monkeypatch.setenv('THREADS_HOME', str(tmp_path / 'threads'))
        monkeypatch.setenv('TZ', 'UTC')


@pytest.fixture
def fake_aside(monkeypatch, tmp_path):
    """The fake Aside over the base fixture set; returns its call log."""
    base = Path(__file__).parent
    monkeypatch.setenv('THREADS_ASIDE_BIN', str(base / 'fake_aside/aside'))
    monkeypatch.setenv('THREADS_FIXTURES', str(base / 'fixtures/routes.ndjson'))
    log = tmp_path / 'requests.ndjson'
    monkeypatch.setenv('THREADS_FAKE_LOG', str(log))
    return log


@pytest.fixture
def routes(fake_aside, monkeypatch, tmp_path):
    """A private copy of the fixture set the fake reads; edit it, then call write()."""
    copy = Routes(tmp_path)
    copy.write()
    monkeypatch.setenv('THREADS_FIXTURES', str(copy.path))
    return copy
