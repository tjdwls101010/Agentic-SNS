"""Where the skill keeps its runtime state: the skill folder's data/ directory, and the one door into it.

data/<platform>/<aside account>/<kind>/ holds one platform's state for one Aside account (protection, session, a
platform's own store); data/<kind>/ holds what the whole skill shares (handles, images).
"""
import os
import re
from pathlib import Path

from sns.errors import SnsError

SKILL_DIR = Path(__file__).resolve().parents[2]
_NAME = re.compile(r'[A-Za-z0-9_-]{1,64}')


def data_dir():
    """data/ beside SKILL.md; SNS_DATA_DIR overrides it for tests and contrast runs."""
    override = os.environ.get('SNS_DATA_DIR')
    return Path(override) if override else SKILL_DIR / 'data'


def _make(path):
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        raise SnsError('blocked', f'The skill\'s state directory {path} cannot be created.',
                       'Make the skill\'s data/ directory writable, then retry.', reason='unreadable') from None
    return path


def scope(platform, account, kind):
    """data/<platform>/<account>/<kind>/, created private on first use."""
    for name in (platform, account, kind):
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError(f'unsafe state path part {name!r}')
    return _make(data_dir() / platform / account / kind)


def shared(kind):
    """data/<kind>/ for state the whole skill shares, created private on first use."""
    if not _NAME.fullmatch(kind):
        raise ValueError(f'unsafe state path part {kind!r}')
    return _make(data_dir() / kind)


def outside_data(path):
    """Refuse a user file (an --out path) that would sit inside the skill's data/, among its state."""
    target, data = Path(path).expanduser().absolute(), data_dir().absolute()
    places = {target, target.resolve() if target.exists() else target.parent.resolve() / target.name}
    for place in places:
        if place == data or data in place.parents or data.resolve() in place.parents:
            raise SnsError('argument', 'The --out file would sit inside the skill\'s data/ directory, among its state.',
                           'Pass --out a path outside the skill folder (and outside the repository).')
