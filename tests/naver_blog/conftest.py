"""Keep independently distributed skills in separate Python namespaces."""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / '.claude/skills/naver-blog/scripts'
PLAN = ROOT / '.claude/plans/naver-blog 스킬 구현 계획.md'

spec = importlib.util.spec_from_file_location('naver_blog_skill', SCRIPTS / '__init__.py',
                                              submodule_search_locations=[str(SCRIPTS)])
module = importlib.util.module_from_spec(spec)
sys.modules['naver_blog_skill'] = module
spec.loader.exec_module(module)


@pytest.fixture(scope='session')
def snapshot():
    """The approved plan owns the endpoint ledger; _api.py is a transcription of it."""
    text = PLAN.read_text(encoding='utf-8')
    block = text.rsplit('```json', 1)[1].split('```', 1)[0]
    return json.loads(block)


@pytest.fixture(scope='session')
def path_table():
    """One allow/deny table shared with the JavaScript snippet test."""
    return json.loads((Path(__file__).parent / 'fixtures/paths.json').read_text(encoding='utf-8'))


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch, tmp_path, request):
    if request.node.get_closest_marker('live') is None:
        monkeypatch.setenv('NAVER_BLOG_HOME', str(tmp_path / 'naver-blog'))


@pytest.fixture
def fake_aside(monkeypatch, tmp_path):
    base = Path(__file__).parent
    monkeypatch.setenv('NAVER_BLOG_ASIDE_BIN', str(base / 'fake_aside/aside'))
    monkeypatch.setenv('NAVER_BLOG_FIXTURES', str(base / 'fixtures'))
    log = tmp_path / 'requests.ndjson'
    monkeypatch.setenv('NAVER_BLOG_FAKE_LOG', str(log))
    return log


@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    """Environment for running the CLI as a real subprocess against the fake browser."""
    base = Path(__file__).parent
    return dict(os.environ,
                NAVER_BLOG_ASIDE_BIN=str(base / 'fake_aside/aside'),
                NAVER_BLOG_FIXTURES=str(base / 'fixtures'),
                NAVER_BLOG_FAKE_LOG=str(tmp_path / 'requests.ndjson'),
                NAVER_BLOG_HOME=str(tmp_path / 'naver-blog'),
                NAVER_BLOG_NO_PACING='1')
