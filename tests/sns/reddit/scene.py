"""A scripted Reddit behind the fake Aside (fakes/fake_aside.py), run through the real cli.main, and what the CLI asked
of it. Every request the reddit platform makes is the `reddit.fetch` snippet, answered with an envelope
{status, url, body, location, ratelimit}; the scene fills the parts a test does not care about (a status of 200, the
URL that was asked, a body serialized from JSON) and, unless a test states its own headers, adds Reddit's per-bucket
counter ('__ratelimit') the way Reddit answers: 100 in the general bucket, 600 in the wiki bucket, none for a share link.
"""
import json
import time
from pathlib import Path

import cli
from tests.sns.support.browser import Browser

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
VIEWER = 'example_viewer'
LIMITS = {'general': 100, 'wiki': 600}
BASE = 'https://www.reddit.com'


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


class Scene:
    def __init__(self, root, monkeypatch, capsys):
        root.mkdir(parents=True, exist_ok=True)
        self.browser = Browser(root)
        self.monkeypatch, self.capsys = monkeypatch, capsys

    # --- scripting ---------------------------------------------------------------------------------------------

    def respond(self, response=None, **match):
        """Queue an answer for the next fetch whose ARGS fit `match` (path=, url=, query={...} with real types)."""
        response = dict(response or {})
        sent = match.get('url') or BASE + match.get('path', '')
        response.setdefault('status', 200)
        response.setdefault('url', sent)
        response.setdefault('location', None)
        body = response.get('body', '')
        response['body'] = body if isinstance(body, str) else json.dumps(body)
        if 'ratelimit' not in response and '__ratelimit' not in response and not match.get('url'):
            bucket = 'wiki' if '/wiki/' in match.get('path', '') else 'general'
            response['__ratelimit'] = {'bucket': bucket, 'limit': LIMITS[bucket], 'reset': 300}
        elif 'ratelimit' not in response and '__ratelimit' not in response:
            response['ratelimit'] = {'used': None, 'remaining': None, 'reset': None}
        self.browser.respond('reddit.fetch', response, **match)
        return self

    def json(self, path, body, query=None, **response):
        match = {'path': path, **({'query': query} if query else {})}
        return self.respond({'body': body, **response}, **match)

    def me(self, name=VIEWER):
        return self.json('/api/me.json', {'kind': 't2', 'data': {'name': name, 'id': 'v1'}})

    def account_status(self, text, exit_code=0):
        self.browser.flag(account_status=text, account_status_exit=exit_code)
        return self

    # --- running -----------------------------------------------------------------------------------------------

    def run(self, *argv, env=None, platforms=None):
        """cli.main in this process against the fake Aside (with the platforms given, else the real ones); returns
        (exit code, stdout, stderr)."""
        self.browser.install(self.monkeypatch)
        for key, value in (env or {}).items():
            self.monkeypatch.setenv(key, value)
        time.tzset()
        code = cli.main([str(a) for a in argv], platforms=platforms)
        captured = self.capsys.readouterr()
        return code, captured.out, captured.err

    # --- what the CLI asked ------------------------------------------------------------------------------------

    def calls(self):
        return self.browser.calls()

    def fetches(self):
        return [call['args'] for call in self.calls() if call['op'] == 'reddit.fetch']

    def paths(self):
        return [args.get('path') or args.get('url') for args in self.fetches()]
