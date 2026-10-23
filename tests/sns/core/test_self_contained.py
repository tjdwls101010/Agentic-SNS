"""The skill folder alone is the installed skill (decision S7): copied outside the repository with an empty data/ and
an empty HOME, it runs, keeps its state in its own data/ and writes nothing to HOME or to the original folder."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.sns.support.browser import Browser

SKILL = Path(__file__).resolve().parents[3] / '.claude/skills/sns'


@pytest.fixture
def copy(tmp_path):
    target = tmp_path / 'installed' / 'sns'
    shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns('__pycache__'))
    for item in (target / 'data').iterdir():
        if item.name != '.gitignore':
            shutil.rmtree(item) if item.is_dir() else item.unlink()
    return target


def environment(tmp_path):
    home = tmp_path / 'home'
    home.mkdir(exist_ok=True)
    return {'HOME': str(home), 'PATH': '/usr/bin:/bin'}


def test_the_copy_runs_and_keeps_state_in_its_own_data(copy, tmp_path):
    env = environment(tmp_path)
    done = subprocess.run([sys.executable, str(copy / 'scripts/cli.py'), '--help'], capture_output=True, text=True,
                          env=env)
    assert done.returncode == 0, done.stderr
    where = subprocess.run([sys.executable, '-c', 'from sns.paths import data_dir; print(data_dir())'],
                           capture_output=True, text=True, env={**env, 'PYTHONPATH': str(copy / 'scripts')})
    assert where.stdout.strip() == str(copy / 'data')
    assert list(Path(env['HOME']).iterdir()) == []


def test_a_real_platform_doctor_writes_only_the_copys_data(copy, tmp_path):
    platforms = [p.name for p in (copy / 'scripts/sns').iterdir() if p.name in ('x', 'reddit', 'threads', 'facebook',
                                                                                  'naver_blog')]
    if not platforms:
        pytest.skip('no platform package yet (P4 adds them)')
    word = 'reddit' if 'reddit' in platforms else platforms[0].replace('_', '-')
    browser = Browser(tmp_path / 'browser')
    browser.root.mkdir()
    browser.write()
    original = sorted(p.name for p in (SKILL / 'data').iterdir())
    env = {**environment(tmp_path), **browser.env()}
    subprocess.run([sys.executable, str(copy / 'scripts/cli.py'), word, 'doctor'], capture_output=True, text=True,
                   env=env)
    assert (copy / 'data' / word.replace('-', '_')).exists()
    assert sorted(p.name for p in (SKILL / 'data').iterdir()) == original
    assert list(Path(env['HOME']).iterdir()) == []
