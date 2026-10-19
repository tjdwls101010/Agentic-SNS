import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
SKILL = REPO / '.claude/skills/twitter'
CLI = SKILL / 'scripts/cli.py'
FIXTURES = TESTS / 'fixtures'


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    path = tmp_path / 'data'
    monkeypatch.setenv('TWITTER_DATA_DIR', str(path))
    return path


START = 'https://x.com/i/xskill'
ACCOUNT = '1000000099'


class Browser:
    """A scripted fake of the Aside browser (fake_aside.py), and what the CLI asked of it."""

    def __init__(self, root):
        self.root = root
        self.scenario = {'tabs': [], 'responses': []}
        self.added_tabs = []
        self.flags = {}
        self.log = root / 'aside-log.jsonl'

    def tab(self, target='TAB1', url=START):
        self.scenario['tabs'].append({'id': target, 'url': url})
        self.added_tabs.append({'id': target, 'url': url})
        return self

    def respond(self, op, response, **match):
        """Queue a response for the next call of `op` whose ARGS contain `match`."""
        self.scenario['responses'].append({'op': op, 'match': match, 'response': response})
        return self

    def flag(self, **flags):
        self.flags.update(flags)
        return self

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines() if line.strip()]

    def ops(self):
        return [call['op'] for call in self.calls()]

    def write(self):
        """Save the scenario, keeping what earlier runs did to it (responses used, tabs opened or closed)."""
        path = self.root / 'scenario.json'
        if path.exists():
            previous = json.loads(path.read_text())
            for mine, theirs in zip(self.scenario['responses'], previous['responses']):
                mine['used'] = theirs.get('used', False)
            self.scenario['tabs'] = previous['tabs'] + [t for t in self.added_tabs if t not in previous['tabs']]
        self.scenario.update(self.flags)
        self.added_tabs = []
        path.write_text(json.dumps(self.scenario))


@pytest.fixture
def browser(tmp_path, data_dir):
    return Browser(tmp_path)


def environment(browser, env=None):
    base = {key: value for key, value in os.environ.items() if not key.startswith('TWITTER_') or key == 'TWITTER_DATA_DIR'}
    base.update({'TWITTER_ASIDE_BIN': str(TESTS / 'fake_aside.py'), 'TWITTER_FAKE_SCENARIO': str(browser.root / 'scenario.json'),
                 'TWITTER_FAKE_LOG': str(browser.log), 'TZ': 'UTC', 'TWITTER_IDLE_SECONDS': 'off', **(env or {})})
    return base


def run_cli(browser, *args, env=None):
    """Run the real cli.py with the fake Aside; returns (exit code, stdout, stderr)."""
    browser.write()
    result = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True,
                            env=environment(browser, env), timeout=120)
    return result.returncode, result.stdout, result.stderr


def state(**extra):
    """What the state page function reports for a logged-in tab on the start screen."""
    return {'location': START, 'user_id': ACCOUNT, 'language': 'en', 'app': True, 'store': True, 'switches': 1442,
            'ct0': True, 'installed_at': 300, 'ready_at_install': 'loading', 'app_at_install': False, 'resources': 0,
            'ours': 0, 'statuses': [], 'signals': [], 'moved': None, **extra}


def known_tab(browser, data_dir, target='T1', **extra):
    """A dedicated tab the skill already knows and that is still open."""
    browser.tab(target)
    (data_dir / 'session').mkdir(parents=True, exist_ok=True)
    (data_dir / 'session/default.json').write_text(json.dumps({'tab': target}))
    browser.respond('state', state(**extra))
    return browser


def opening(browser, target='NEW1', resources=13, early=True, **extra):
    """Aside opens a new tab; it loads x.com with the kit installed early (or late) and is logged in."""
    browser.respond('opener', {'tabs': [target]})
    browser.respond('load:arm', {'installed_at': 300 if early else 4000, 'location': START,
                                 'ready_at_install': 'loading' if early else 'complete', 'app_at_install': not early})
    browser.respond('state', state(resources=resources, **extra))
    return browser


def query_result(body, status=200, headers=None, resources=0, ours=1, **extra):
    return {'status': status, 'body': body if isinstance(body, str) else json.dumps(body), 'headers': headers or {},
            'used': {'source': 'live', 'query_id': 'SYNTHq', 'features': []}, 'nonce': 'n1', 'explicit': 1,
            'resources': resources, 'ours': ours, 'statuses': [200] * resources, 'signals': [], 'location': START,
            'moved': None, **extra}


MODULES = {'live': {'Viewer': {'query_id': 'SYNTHqVW01', 'type': 'query', 'features': 0}}, 'modules': 3702,
           'generator': True, 'bearer': True, 'resources': 0, 'ours': 0, 'statuses': [], 'signals': [],
           'location': START, 'moved': None}


def command_of(line):
    """The arguments of a printed more: command line, parsed the way a shell would."""
    import shlex
    return shlex.split(line.split(' ', 1)[1])[3:]  # drop: uv run "<cli.py>"
