"""Where the skill keeps its runtime state, and the one door into it.

State lives outside the skill folder, because installing or updating the skill replaces that folder (`npx skills add`
removes it before copying): SNS_DATA_DIR when set (tests and contrast runs), else
${XDG_STATE_HOME:-~/.local/state}/agentic-sns/. Every install of the skill on this computer shares it, so a block one
install recorded stops the others. Under it, <platform>/<aside account>/<kind>/ holds one platform's state for one Aside
account (protection, session, a platform's own store); <kind>/ holds what the whole skill shares (handles, images).

An install from before the move kept its state in data/ beside SKILL.md; legacy_dir() names it so it can be imported.
"""
import os
import re
from pathlib import Path

from sns.errors import SnsError

SKILL_DIR = Path(__file__).resolve().parents[2]
_NAME = re.compile(r'[A-Za-z0-9_-]{1,64}')


def data_dir():
    """The state directory: SNS_DATA_DIR, else ${XDG_STATE_HOME:-~/.local/state}/agentic-sns."""
    override = os.environ.get('SNS_DATA_DIR')
    if override:
        return Path(override)
    base = os.environ.get('XDG_STATE_HOME')
    base = Path(base) if base and os.path.isabs(base) else Path.home() / '.local' / 'state'
    return base / 'agentic-sns'


def legacy_dir():
    """This install's data/ from before the state moved, when there is one to import; never with SNS_DATA_DIR (a test
    or contrast run has its own state and must not take in the real one)."""
    if os.environ.get('SNS_DATA_DIR'):
        return None
    old = SKILL_DIR / 'data'
    return old if old.is_dir() and old.resolve() != data_dir().resolve() else None


def _make(path):
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        raise SnsError('blocked', f'The skill\'s state directory {path} cannot be created.',
                       f'Make {data_dir()} writable (or set SNS_DATA_DIR to a writable directory), then retry.',
                       reason='unreadable') from None
    return path


def scope(platform, account, kind):
    """<state>/<platform>/<account>/<kind>/, created private on first use."""
    for name in (platform, account, kind):
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ValueError(f'unsafe state path part {name!r}')
    return _make(data_dir() / platform / account / kind)


def shared(kind):
    """<state>/<kind>/ for state the whole skill shares, created private on first use."""
    if not _NAME.fullmatch(kind):
        raise ValueError(f'unsafe state path part {kind!r}')
    return _make(data_dir() / kind)


def outside_data(path):
    """Refuse a user file (an --out path) that would sit inside the skill's state directory, or inside an old data/."""
    target = Path(path).expanduser().absolute()
    places = {target, target.resolve() if target.exists() else target.parent.resolve() / target.name}
    for data in filter(None, (data_dir(), SKILL_DIR / 'data')):
        data = data.absolute()
        for place in places:
            if place == data or data in place.parents or data.resolve() in place.parents:
                raise SnsError('argument', f'The --out file would sit inside the skill\'s state directory ({data}).',
                               'Pass --out a path outside it (and outside the skill folder).')
