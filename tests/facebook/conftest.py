import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
SKILL = REPO / '.claude/skills/facebook'
CLI = SKILL / 'scripts/cli.py'
FIXTURES = TESTS / 'fixtures'


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    path = tmp_path / 'data'
    monkeypatch.setenv('FACEBOOK_DATA_DIR', str(path))
    return path


class Browser:
    """A scripted fake of the Aside browser (fake_aside.py), and what the CLI asked of it."""

    def __init__(self, root):
        self.root = root
        self.scenario = {'tabs': [], 'responses': []}
        self.log = root / 'aside-log.jsonl'

    def tab(self, target='TAB1', url='https://www.facebook.com/'):
        self.scenario['tabs'].append({'id': target, 'url': url})
        return self

    def respond(self, op, response, **match):
        """Queue a response for the next call of `op` whose ARGS contain `match`."""
        self.scenario['responses'].append({'op': op, 'match': match, 'response': response})
        return self

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines() if line.strip()]

    def write(self):
        (self.root / 'scenario.json').write_text(json.dumps(self.scenario))


@pytest.fixture
def browser(tmp_path, data_dir):
    return Browser(tmp_path)


def run_cli(browser, *args, env=None):
    """Run the real cli.py with the fake Aside; returns (exit code, stdout, stderr)."""
    browser.write()
    environment = {key: value for key, value in os.environ.items() if key != 'FACEBOOK_ASIDE_ACCOUNT'}
    environment.update({'FACEBOOK_ASIDE_BIN': str(TESTS / 'fake_aside.py'),
                        'FACEBOOK_FAKE_SCENARIO': str(browser.root / 'scenario.json'),
                        'FACEBOOK_FAKE_LOG': str(browser.log), 'TZ': 'UTC', **(env or {})})
    result = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, env=environment,
                            timeout=120)
    return result.returncode, result.stdout, result.stderr
