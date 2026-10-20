import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
SKILL = REPO / '.claude/skills/reddit'
CLI = SKILL / 'scripts/cli.py'
FIXTURES = TESTS / 'fixtures'
VIEWER = 'example_viewer'


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    path = tmp_path / 'data'
    monkeypatch.setenv('REDDIT_DATA_DIR', str(path))
    return path


class Reddit:
    """A scripted fake of Reddit behind the Aside CLI (fake_aside.py), and what the CLI asked of it."""

    def __init__(self, root):
        self.root = root
        self.scenario = {'responses': []}
        self.log = root / 'aside-log.jsonl'

    def respond(self, response=None, **match):
        """Queue an answer for the next request whose ARGS fit `match` (path=, url=, query={...})."""
        self.scenario['responses'].append({'match': match, 'response': response or {}})
        return self

    def json(self, path, body, query=None, **response):
        match = {'path': path, **({'query': query} if query else {})}
        return self.respond({'body': body, **response}, **match)

    def me(self, name=VIEWER):
        return self.json('/api/me.json', {'kind': 't2', 'data': {'name': name, 'id': 'v1'}})

    def account_status(self, text, exit_code=0):
        self.scenario['account_status'] = text
        self.scenario['account_status_exit'] = exit_code
        return self

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines() if line.strip()]

    def fetches(self):
        return [call['args'] for call in self.calls() if call['op'] == 'fetch']

    def paths(self):
        return [args.get('path') or args.get('url') for args in self.fetches()]

    def write(self):
        """Save the scenario, keeping what earlier runs did to it (responses used, bucket counters)."""
        path = self.root / 'scenario.json'
        if path.exists():
            previous = json.loads(path.read_text())
            for mine, theirs in zip(self.scenario['responses'], previous['responses']):
                mine['used'] = theirs.get('used', False)
            self.scenario['buckets'] = previous.get('buckets', {})
        path.write_text(json.dumps(self.scenario))


@pytest.fixture
def reddit(tmp_path, data_dir):
    return Reddit(tmp_path)


def environment(reddit, env=None):
    base = {key: value for key, value in os.environ.items() if not key.startswith('REDDIT_')}
    base.update({'REDDIT_ASIDE_BIN': str(TESTS / 'fake_aside.py'), 'REDDIT_FAKE_SCENARIO': str(reddit.root / 'scenario.json'),
                 'REDDIT_FAKE_LOG': str(reddit.log), 'REDDIT_DATA_DIR': os.environ['REDDIT_DATA_DIR'], 'TZ': 'UTC',
                 'REDDIT_TEST_NO_WAIT': '1', **(env or {})})
    return base


def run_cli(reddit, *args, env=None):
    """Run the real cli.py with the fake Aside; returns (exit code, stdout, stderr)."""
    reddit.write()
    result = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True,
                            env=environment(reddit, env), timeout=120)
    return result.returncode, result.stdout, result.stderr


def command_of(line):
    """The arguments of a printed more: command line, parsed the way a shell would."""
    return shlex.split(line.split(' ', 1)[1])[3:]  # drop: uv run "<cli.py>"
