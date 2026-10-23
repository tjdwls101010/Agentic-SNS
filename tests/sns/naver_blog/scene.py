"""A scripted Naver Blog behind the fake Aside (fakes/fake_aside.py), run through the real cli.main, and what the CLI
asked of it. Every request the platform makes is the `naver_blog.fetch` snippet, answered with an envelope
{status, url, location, content_type, body, b64}; the scene fills the parts a test does not care about (status 200,
the URL that was asked, a JSON body serialized from `json=`). Naver reports no rate limit, so there are no headers.
"""
import json as jsonlib
import time
from pathlib import Path

import cli
from tests.sns.support.browser import Browser

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
M = 'm.blog.naver.com'
SECTION = 'section.blog.naver.com'
CBOX = 'apis.naver.com', '/commentBox/cbox/web_naver_list_json.json'
VIEWER = 'viewer_blog'
ACCOUNT = 'u0'   # the Aside account the stand-in marks active

# The fixtures were written when the skill raised exit numbers; units now raise the kind cli.py maps to a number.
KIND_OF = {2: 'argument', 3: 'aside', 4: 'login', 5: 'blocked', 6: 'failed', 7: 'empty', 8: 'partial', 9: 'unavailable'}


def fixture(name):
    return jsonlib.loads((FIXTURES / name).read_text(encoding='utf-8'))


def response(name):
    """A synthetic response shape of cli_responses.json, by its case name (a copy: tests may edit it); a text one
    (the section hosts' XSSI answers) comes back as the string."""
    for case in fixture('cli_responses.json')['cases']:
        if case['name'] == name:
            return jsonlib.loads(jsonlib.dumps(case['response' if 'response' in case else 'response_text']))
    raise KeyError(name)


class Scene:
    def __init__(self, root, monkeypatch, capsys, data_dir):
        root.mkdir(parents=True, exist_ok=True)
        self.browser = Browser(root)
        self.monkeypatch, self.capsys, self.data_dir = monkeypatch, capsys, data_dir

    # --- scripting ---------------------------------------------------------------------------------------------

    def respond(self, host, path, *, query=None, json=None, **envelope):
        """Queue an answer for the next fetch of host+path whose query holds `query`. json= is a JSON body; other
        envelope fields (status, body, location, content_type, b64) are used as given; a raw `__raw_stdout`/`__exit`
        goes through unchanged."""
        if json is not None:
            envelope['body'] = jsonlib.dumps(json, ensure_ascii=False)
        if not any(key.startswith('__') for key in envelope):
            envelope = {'status': 200, 'url': f'https://{host}{path}', 'location': None, 'content_type':
                        'application/json', 'body': '', 'b64': None, **envelope}
        match = {'host': host, 'path': path, **({'query': query} if query else {})}
        self.browser.respond('naver_blog.fetch', envelope, **match)
        return self

    def logged_in(self, **extra):
        return self.respond(M, '/api/current-user', json=_current_user(**extra))

    def account_status(self, text, exit_code=0):
        self.browser.flag(account_status=text, account_status_exit=exit_code)
        return self

    def hint(self, viewer=VIEWER, age=0):
        """The viewer cache a run left: a hint of who was logged in `age` seconds ago, never proof."""
        directory = self.data_dir / 'naver_blog' / ACCOUNT / 'session'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'viewer.json').write_text(jsonlib.dumps({'viewer': viewer, 'seen_at': time.time() - age}))
        return self

    # --- running -----------------------------------------------------------------------------------------------

    def run(self, *argv, env=None, platforms=None):
        """cli.main in this process against the fake Aside; returns (exit code, stdout, stderr)."""
        self.browser.install(self.monkeypatch)
        for key, value in (env or {}).items():
            self.monkeypatch.setenv(key, value)
        code = cli.main([str(a) for a in argv], platforms=platforms)
        captured = self.capsys.readouterr()
        return code, captured.out, captured.err

    # --- what the CLI asked ------------------------------------------------------------------------------------

    def calls(self):
        return self.browser.calls()

    def fetches(self):
        return [call['args'] for call in self.calls() if call['op'] == 'naver_blog.fetch']

    def paths(self):
        return [args['path'] for args in self.fetches()]

    def unused(self):
        return self.browser.unused()


def _current_user(**extra):
    """current-user for a logged-in viewer whose blog is VIEWER (synthetic identifiers, and the login identifiers the
    app also sends, which must never reach a record)."""
    body = response('current_user-1')
    body['result'].update(extra)
    return body
