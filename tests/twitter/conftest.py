import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / '.claude/skills/twitter/scripts'
spec = importlib.util.spec_from_file_location('twitter_skill', SCRIPTS / '__init__.py', submodule_search_locations=[str(SCRIPTS)])
module = importlib.util.module_from_spec(spec)
sys.modules['twitter_skill'] = module
spec.loader.exec_module(module)
