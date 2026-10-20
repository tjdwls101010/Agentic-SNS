"""Where the skill keeps its runtime state: the skill folder's data/ directory, one subdirectory per kind of state and
per Aside account (each browser profile has its own Reddit login, protection and handles)."""
import os
import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2]


def data_dir():
    """data/ beside SKILL.md; REDDIT_DATA_DIR overrides it for tests and contrast runs."""
    override = os.environ.get('REDDIT_DATA_DIR')
    return Path(override) if override else SKILL_DIR / 'data'


def account_key(account):
    """A file-name-safe key for an Aside account id."""
    return re.sub(r'[^A-Za-z0-9_-]', '_', account)


def state_dir(name, account, create=True):
    """One kind of state's directory for one Aside account, created private on first use."""
    path = data_dir() / name / account_key(account)
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path
