"""Where the skill keeps its runtime state: the skill folder's data/ directory."""
import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]


def data_dir():
    """data/ beside SKILL.md; TWITTER_DATA_DIR overrides it for tests and contrast runs."""
    override = os.environ.get('TWITTER_DATA_DIR')
    return Path(override) if override else SKILL_DIR / 'data'


def state_dir(name):
    """One kind of state's directory under data/, created private on first use."""
    path = data_dir() / name
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path
