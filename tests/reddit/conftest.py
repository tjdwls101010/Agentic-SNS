"""Load Reddit under its own namespace; Facebook uses similarly named modules."""
import importlib.util
import sys
from pathlib import Path
import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / '.claude/skills/reddit/scripts'
spec = importlib.util.spec_from_file_location('reddit_skill', SCRIPTS / '__init__.py', submodule_search_locations=[str(SCRIPTS)])
module = importlib.util.module_from_spec(spec)
sys.modules['reddit_skill'] = module
spec.loader.exec_module(module)

@pytest.fixture(autouse=True)
def reddit_state(monkeypatch, tmp_path, request):
    if request.node.get_closest_marker('live') is None:
        monkeypatch.setenv('REDDIT_HOME', str(tmp_path / 'reddit'))
