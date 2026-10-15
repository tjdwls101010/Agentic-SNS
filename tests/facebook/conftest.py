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
        """Save the scenario, keeping which responses earlier runs already used."""
        path = self.root / 'scenario.json'
        if path.exists():
            used = json.loads(path.read_text())['responses']
            for mine, theirs in zip(self.scenario['responses'], used):
                mine['used'] = theirs.get('used', False)
            self.scenario['tabs'] = json.loads(path.read_text())['tabs'] + [
                t for t in self.scenario['tabs'] if t not in json.loads(path.read_text())['tabs']]
        path.write_text(json.dumps(self.scenario))


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


STATE_OK = {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'runtime': True, 'resources': 0}


def known_tab(browser, data_dir, target='T1'):
    """A dedicated tab the skill already knows and that is still open."""
    browser.tab(target)
    (data_dir / 'session').mkdir(parents=True, exist_ok=True)
    (data_dir / 'session/default.json').write_text(json.dumps({'tab': target, 'queries': {}}))
    browser.respond('state', STATE_OK)
    return browser


def story(identity, created='2026-09-12T03:00:00Z', text=None, **flags):
    """A minimal feed story for a scripted response; created is an ISO time or None."""
    from datetime import datetime
    node = {'feedback': {'id': identity}, 'actors': [{'id': '9' + identity, 'name': 'Author ' + identity,
                                                      'url': 'https://www.facebook.com/author.' + identity.lower()}],
            'message': {'text': text if text is not None else f'post {identity}'},
            'permalink_url': f'https://www.facebook.com/author.{identity.lower()}/posts/{identity}'}
    if created:
        node['creation_time'] = int(datetime.fromisoformat(created.replace('Z', '+00:00')).timestamp())
    if flags.get('sponsored'):
        node['sponsored_data'] = {'ad_id': '1'}
    if flags.get('pinned'):
        node['is_pinned'] = True
    return node


def graphql_body(connection_path, stories, has_next=True, cursor='CUR1'):
    """An NDJSON GraphQL body with one connection at connection_path (e.g. ['viewer', 'news_feed'])."""
    connection = {'edges': [{'node': s} for s in stories],
                  'page_info': {'has_next_page': has_next, 'end_cursor': cursor if has_next else None}}
    data = connection
    for key in reversed(connection_path):
        data = {key: data}
    return json.dumps({'data': data})


def query_result(body, status=200, source='live', doc_id='111', resources=1):
    return {'status': status, 'url': 'https://www.facebook.com/api/graphql/', 'body': body,
            'used': {'source': source, 'doc_id': doc_id, 'flags': {'__relay_internal__pv__Xrelayprovider': True}
                     if source == 'live' else None}, 'explicit': 1, 'resources': resources}
