import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
SKILL = REPO / '.claude/skills/threads'
CLI = SKILL / 'scripts/cli.py'
FIXTURES = TESTS / 'fixtures'
START = 'https://www.threads.com/search'
ACCOUNT = '1000000009'


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    path = tmp_path / 'data'
    monkeypatch.setenv('THREADS_DATA_DIR', str(path))
    return path


class Browser:
    """A scripted fake of the Aside browser (fake_aside.py), and what the CLI asked of it."""

    def __init__(self, root):
        self.root = root
        self.scenario = {'tabs': [], 'responses': []}
        self.added_tabs, self.vanishing = [], None
        self.log = root / 'aside-log.jsonl'

    def tab(self, target='TAB1', url=START):
        self.scenario['tabs'].append({'id': target, 'url': url})
        self.added_tabs.append({'id': target, 'url': url})
        return self

    def respond(self, op, response, **match):
        """Queue a response for the next call of `op` whose ARGS contain `match`."""
        self.scenario['responses'].append({'op': op, 'match': match, 'response': response})
        return self

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines() if line.strip()]

    def ops(self):
        return [call['op'] for call in self.calls()]

    def vanish_after_state(self, target):
        """The tab disappears right after its next state check, as when a person closes it."""
        self.vanishing = target
        return self

    def write(self):
        """Save the scenario, keeping what earlier runs did to it (responses used, tabs opened or closed)."""
        path = self.root / 'scenario.json'
        if path.exists():
            previous = json.loads(path.read_text())
            for mine, theirs in zip(self.scenario['responses'], previous['responses']):
                mine['used'] = theirs.get('used', False)
            self.scenario['tabs'] = previous['tabs'] + [t for t in self.added_tabs if t not in previous['tabs']]
        self.scenario['vanish_after_state'] = self.vanishing
        self.added_tabs, self.vanishing = [], None
        path.write_text(json.dumps(self.scenario))


@pytest.fixture
def browser(tmp_path, data_dir):
    return Browser(tmp_path)


def environment(browser, env=None):
    base = {key: value for key, value in os.environ.items() if key != 'THREADS_ASIDE_ACCOUNT'}
    base.update({'THREADS_ASIDE_BIN': str(TESTS / 'fake_aside.py'), 'THREADS_FAKE_SCENARIO': str(browser.root / 'scenario.json'),
                 'THREADS_FAKE_LOG': str(browser.log), 'TZ': 'UTC', 'THREADS_IDLE_SECONDS': 'off', **(env or {})})
    return base


def run_cli(browser, *args, env=None):
    """Run the real cli.py with the fake Aside; returns (exit code, stdout, stderr)."""
    browser.write()
    result = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True,
                            env=environment(browser, env), timeout=120)
    return result.returncode, result.stdout, result.stderr


def state(**extra):
    """What the state page function reports for a logged-in tab on the start screen."""
    return {'location': START, 'user_id': ACCOUNT, 'app_id': '999000111222333', 'runtime': True, 'resources': 0,
            'statuses': [], 'signals': [], 'document': None, **extra}


LOGGED_IN_DOCUMENT = ('<script>{"csrf_token":"tok","NON_FACEBOOK_USER_ID":"' + ACCOUNT +
                      '","username":"example.viewer","__bbox":{}}</script>')


def known_tab(browser, data_dir, target='T1', **extra):
    """A dedicated tab the skill already knows and that is still open."""
    browser.tab(target)
    (data_dir / 'session').mkdir(parents=True, exist_ok=True)
    (data_dir / 'session/default.json').write_text(json.dumps({'tab': target, 'queries': {}}))
    browser.respond('state', state(**extra))
    return browser


def opening(browser, target='NEW1', resources=33, **extra):
    """Aside opens a new tab on the start screen, which loads logged in."""
    browser.respond('open', {'tab': {'id': target, 'url': START}})
    browser.respond('state', state(resources=resources, document=LOGGED_IN_DOCUMENT, **extra))
    browser.respond('state', state(resources=0, **{k: v for k, v in extra.items() if k != 'resources'}))  # quiet
    return browser


def query_result(body, status=200, source='live', doc_id='111', resources=1, **extra):
    return {'status': status, 'url': 'https://www.threads.com/api/graphql/', 'body': body if isinstance(body, str) else json.dumps(body),
            'used': {'source': source, 'doc_id': doc_id, 'flags': {'__relay_internal__pv__BarcelonaIsLoggedInrelayprovider': True}
                     if source == 'live' else None}, 'explicit': 1, 'resources': resources, 'statuses': [200] * resources,
            'signals': [], 'location': START, **extra}


def command_of(line):
    """The arguments of a printed more: command line, parsed the way a shell would."""
    import shlex
    return shlex.split(line.split(' ', 1)[1])[3:]  # drop: uv run "<cli.py>"
