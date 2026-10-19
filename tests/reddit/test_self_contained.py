"""The skill folder alone, copied outside the repository, runs: its help, a doctor through the fake Aside, and its
state lands in the copy's own data/ (nothing in the repository or the home directory)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from conftest import SKILL, TESTS


def test_a_copy_of_the_skill_folder_runs_on_its_own(tmp_path):
    outside = Path(tempfile.mkdtemp(prefix='reddit-skill-copy-'))
    try:
        copy = outside / 'reddit'
        shutil.copytree(SKILL, copy, ignore=shutil.ignore_patterns('__pycache__', 'data'))
        (copy / 'data').mkdir()
        scenario = tmp_path / 'scenario.json'
        scenario.write_text(json.dumps({'responses': [{'match': {'path': '/api/me.json'}, 'response': {
            'body': {'kind': 't2', 'data': {'name': 'example_viewer'}}}}]}))
        home = tmp_path / 'home'
        home.mkdir()
        env = {key: value for key, value in os.environ.items() if not key.startswith('REDDIT_')}
        env.update(HOME=str(home), REDDIT_ASIDE_BIN=str(TESTS / 'fake_aside.py'), REDDIT_FAKE_SCENARIO=str(scenario),
                   REDDIT_FAKE_LOG=str(tmp_path / 'log'), REDDIT_TEST_NO_WAIT='1', PYTHONDONTWRITEBYTECODE='1')
        cli = copy / 'scripts/cli.py'
        helped = subprocess.run([sys.executable, str(cli), '--help'], capture_output=True, text=True, env=env,
                                cwd=outside, timeout=60)
        assert helped.returncode == 0 and 'doctor' in helped.stdout
        before = sorted(p.name for p in (SKILL / 'data').iterdir()) if (SKILL / 'data').exists() else []
        done = subprocess.run([sys.executable, str(cli), 'doctor'], capture_output=True, text=True, env=env, cwd=outside,
                              timeout=60)
        assert done.returncode == 0, done.stdout + done.stderr
        assert Path(json.loads(done.stdout)['results'][0]['data_dir']).resolve() == (copy / 'data').resolve()
        assert (copy / 'data/protection/u0/requests.jsonl').exists()
        assert sorted(p.name for p in (SKILL / 'data').iterdir()) == before, 'nothing written into the repository copy'
        assert not list(home.iterdir()), 'nothing written into the home directory'
    finally:
        shutil.rmtree(outside, ignore_errors=True)
