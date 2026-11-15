"""The skill folder alone is the installed skill (decision S7), and it never writes into itself (decision A5): installing
or updating replaces the folder, so its state lives in ${XDG_STATE_HOME:-~/.local/state}/agentic-sns/. Copied outside
the repository with an empty HOME, it runs, keeps its state there and writes nothing into the copy or the original."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.sns.support.browser import Browser

SKILL = Path(__file__).resolve().parents[3] / '.claude/skills/sns'


def files(root):
    """The skill's own files (an old data/ in this checkout belongs to whatever ran it last, not to this test)."""
    return sorted(str(p.relative_to(root)) for p in root.rglob('*') if '__pycache__' not in p.parts
                  and p.relative_to(root).parts[0] != 'data')


@pytest.fixture
def copy(tmp_path):
    target = tmp_path / 'installed' / 'sns'
    shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns('__pycache__', 'data'))
    return target


def environment(tmp_path, **extra):
    home = tmp_path / 'home'
    home.mkdir(exist_ok=True)
    return {'HOME': str(home), 'PATH': '/usr/bin:/bin', **extra}


def test_the_state_directory_is_the_users_state_home(copy, tmp_path):
    env = environment(tmp_path)
    where = lambda extra: subprocess.run(  # noqa: E731
        [sys.executable, '-c', 'from sns.paths import data_dir; print(data_dir())'], capture_output=True, text=True,
        env={**env, **extra, 'PYTHONPATH': str(copy / 'scripts')}).stdout.strip()
    assert where({}) == str(tmp_path / 'home' / '.local' / 'state' / 'agentic-sns')
    assert where({'XDG_STATE_HOME': str(tmp_path / 'xdg')}) == str(tmp_path / 'xdg' / 'agentic-sns')
    assert where({'XDG_STATE_HOME': 'relative/ignored'}) == str(tmp_path / 'home' / '.local' / 'state' / 'agentic-sns')
    assert where({'SNS_DATA_DIR': str(tmp_path / 'own')}) == str(tmp_path / 'own')
    done = subprocess.run([sys.executable, str(copy / 'scripts/cli.py'), '--help'], capture_output=True, text=True,
                          env=env)
    assert done.returncode == 0, done.stderr


def test_a_real_platform_doctor_writes_its_state_outside_the_skill_folder(copy, tmp_path):
    browser = Browser(tmp_path / 'browser')
    browser.root.mkdir()
    browser.write()
    before_copy, before_original = files(copy), files(SKILL)
    env = {**environment(tmp_path, XDG_STATE_HOME=str(tmp_path / 'xdg')), **browser.env()}
    subprocess.run([sys.executable, str(copy / 'scripts/cli.py'), 'reddit', 'doctor'], capture_output=True, text=True,
                   env=env)
    assert (tmp_path / 'xdg' / 'agentic-sns' / 'reddit').is_dir()
    assert files(copy) == before_copy and not (copy / 'data').exists()
    assert files(SKILL) == before_original
    assert list((tmp_path / 'home').iterdir()) == []
