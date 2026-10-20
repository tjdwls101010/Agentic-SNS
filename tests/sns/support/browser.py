"""A scripted fake of the Aside browser (fakes/fake_aside.py), and what the CLI asked of it."""
import json
import os
import sys
from pathlib import Path

FAKE = Path(__file__).resolve().parents[1] / 'fakes' / 'fake_aside.py'


class Browser:
    def __init__(self, root):
        self.root = Path(root)
        self.scenario = {'tabs': [], 'responses': []}
        self.added_tabs = []
        self.flags = {}
        self.log = self.root / 'aside-log.jsonl'
        self.path = self.root / 'scenario.json'

    def tab(self, target='TAB1', url='about:blank'):
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

    def unused(self):
        return [r for r in json.loads(self.path.read_text())['responses'] if not r.get('used')] if self.path.exists() \
            else self.scenario['responses']

    def write(self):
        """Save the scenario, keeping what earlier runs did to it (responses used, tabs opened or closed)."""
        if self.path.exists():
            previous = json.loads(self.path.read_text())
            for mine, theirs in zip(self.scenario['responses'], previous['responses']):
                mine['used'] = theirs.get('used', False)
            self.scenario['tabs'] = previous['tabs'] + [t for t in self.added_tabs if t not in previous['tabs']]
            for key in ('counters', 'loaded', 'open_ids'):
                if key in previous:
                    self.scenario[key] = previous[key]
        self.scenario.update(self.flags)
        self.added_tabs = []
        self.path.write_text(json.dumps(self.scenario))
        return self

    def env(self):
        """The environment that points the skill at this fake."""
        return {'SNS_ASIDE_BIN': str(self.bin()),
                'SNS_FAKE_SCENARIO': str(self.path), 'SNS_FAKE_LOG': str(self.log), 'SNS_TEST_NO_WAIT': '1'}

    def bin(self):
        """A one-line launcher, so the skill runs the fake with this Python whatever is on PATH."""
        launcher = self.root / 'aside'
        if not launcher.exists():
            launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE}" "$@"\n')
            launcher.chmod(0o755)
        return launcher

    def install(self, monkeypatch):
        """Point this process (in-process tests) at the fake."""
        self.write()
        for key, value in self.env().items():
            monkeypatch.setenv(key, value)
        return self
