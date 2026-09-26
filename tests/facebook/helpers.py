"""Run the Facebook CLI as a process against the fake Aside, and build the responses Facebook would send.

Every test that needs the CLI goes through `Account.run`: one isolated FACEBOOK_HOME per account, a queue of fake
Aside replies per call, and the fake's call log returned with the result. Pacing sleeps are skipped unless a test
passes paced=True, because pacing has its own real-clock test.
"""
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / '.claude/skills/facebook'
CLI = SKILL / 'scripts/cli.py'
FIXTURES = Path(__file__).with_name('fixtures')
FAKE_ASIDE = Path(__file__).with_name('fake_aside') / 'aside'
PROCESS_DOUBLES = Path(__file__).with_name('process_doubles')
POST_URL = 'https://www.facebook.com/zuck/posts/123'
LIMITED = {'status': 429, 'url': 'https://www.facebook.com/', 'body': '{}'}


@dataclass
class Result:
    code: int
    stdout: str
    stderr: str
    calls: list
    left: int

    @property
    def data(self):
        return json.loads(self.stdout)

    @property
    def ids(self):
        return [row['id'] for row in self.data['results']]

    @property
    def snippets(self):
        return [call['name'] for call in self.calls]

    def graphql(self, index=0):
        """Arguments of the index-th GraphQL call (query name, doc_id, referer, variables)."""
        return [call['args'] for call in self.calls if call['name'] == 'graphql'][index]


class Account:
    """One isolated account state directory; each run queues its own fake Aside replies."""

    def __init__(self, tmp_path, cli=CLI):
        self.tmp = Path(tmp_path)
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.home = self.tmp / 'state'
        self.cli = Path(cli)
        self.runs = 0

    def run(self, *args, responses=(), paced=False, expected=None, env=None, timeout=120, cwd=None):
        self.runs += 1
        queue = self.tmp / f'responses-{self.runs}.json'
        log = self.tmp / f'calls-{self.runs}.jsonl'
        queue.write_text(json.dumps(list(responses)))
        environment = {**os.environ, 'FACEBOOK_ASIDE_BIN': str(FAKE_ASIDE), 'FAKE_ASIDE_RESPONSES': str(queue),
                       'FAKE_ASIDE_LOG': str(log), 'FACEBOOK_HOME': str(self.home)}
        for name in ('FAKE_ASIDE_MODE', 'FAKE_ASIDE_EXPECTED_ARGS', 'FAKE_NO_SLEEP', 'FAKE_FAIL_REPLACE'):
            environment.pop(name, None)
        environment['PYTHONPATH'] = str(PROCESS_DOUBLES)
        if not paced:
            environment['FAKE_NO_SLEEP'] = '1'
        if expected is not None:
            environment['FAKE_ASIDE_EXPECTED_ARGS'] = json.dumps(expected)
        environment.update(env or {})
        done = subprocess.run([sys.executable, str(self.cli), *args], capture_output=True, text=True,
                              env=environment, timeout=timeout, cwd=cwd)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return Result(done.returncode, done.stdout, done.stderr, calls, len(json.loads(queue.read_text())))

    def blocked(self):
        """Whether the next read is refused before any request."""
        result = self.run('feed', '--json')
        return result.code == 5 and result.calls == []


def more_args(command, cli=CLI):
    """A more: command is this CLI's allowed-tools invocation; return the arguments after it."""
    words = shlex.split(command)
    assert words[:3] == ['uv', 'run', str(cli)]
    return words[3:]


def text_more(stdout):
    last = stdout.rstrip('\n').splitlines()[-1]
    assert last.startswith('more: ')
    return last.removeprefix('more: ')


# --- responses ----------------------------------------------------------------------------------------------------

def envelope(body, status=200, url='https://www.facebook.com/api/graphql/'):
    return {'status': status, 'url': url, 'body': body if isinstance(body, str) else json.dumps(body)}


def login(user='100', dtsg='synthetic', lsd='synthetic', spin='123'):
    return envelope(f'"USER_ID":"{user}" "DTSGInitialData",[],{{"token":{json.dumps(dtsg)}}} '
                    f'"LSD",[],{{"token":{json.dumps(lsd)}}} "__spin_r":{spin}', url='https://www.facebook.com/')


def page_info(cursor=None):
    return {'has_next_page': cursor is not None, 'end_cursor': cursor}


def story(ident, text=None, **fields):
    return {'feedback': {'id': ident}, 'message': {'text': 'Synthetic ' + ident if text is None else text}, **fields}


def connection(key, nodes, cursor=None, root='node'):
    return envelope({'data': {root: {key: {'edges': [{'node': n} for n in nodes], 'page_info': page_info(cursor)}}}})


def feed_page(ids, cursor=None):
    return connection('news_feed', [story(i) for i in ids], cursor, root='viewer')


def feed_stories(stories, cursor=None):
    return connection('news_feed', stories, cursor, root='viewer')


def timeline_page(stories, cursor=None):
    return connection('timeline_list_feed_units', stories, cursor)


def group_page(stories, cursor=None):
    return connection('group_feed', stories, cursor)


def story_id_page(story_id='story'):
    return envelope(f'"storyID":"{story_id}"', url=POST_URL)


def profile_page(user_id):
    return envelope(f'<html>"userID":"{user_id}"</html>', url='https://www.facebook.com/synthetic')


def post_response(text='Complete synthetic post', ident='post-feedback'):
    return envelope({'data': {'node': {'feedback': {'id': ident}, 'message': {'text': text}}}})


def fixture_response(name):
    return envelope((FIXTURES / name).read_text())


def comment_node(ident, depth=0, parent=None, text=None):
    return {'id': ident, 'depth': depth, 'author': {'id': 'author', 'name': 'Synthetic'},
            'body': {'text': 'Synthetic comment ' + ident if text is None else text},
            'comment_direct_parent': {'id': parent} if parent else None,
            'feedback': {'id': ident + '-feedback', 'expansion_info': {'expansion_token': ident + '-token'},
                         'replies_fields': {'total_count': 1 if depth == 0 else 0}}}


def comment_page(nodes, key='comments', cursor=None):
    return connection(key, nodes, cursor)


def search_page(nodes, cursor=None):
    return envelope({'data': {'serpResponse': {'results': {'edges': [{'node': n} for n in nodes],
                                                           'page_info': page_info(cursor)}}}})


def entity(ident, typename='User', name='Synthetic Entity', **fields):
    return {'__typename': typename, 'id': ident, 'name': name, 'url': 'https://www.facebook.com/' + ident, **fields}


def about_overview(sections=(), collections=()):
    return envelope({'data': {'user': {'about_app_sections': {'nodes': list(sections)},
                                       'all_collections': {'nodes': [{'id': i, 'name': n} for i, n in collections]}}}})


def about_section(section, *texts, url=None):
    return {'field_section_type': section, 'profile_fields': {'nodes': [
        {'title': {'text': t}, **({'link_url': url} if url else {})} for t in texts]}}


def about_collection(*sections):
    return envelope({'data': {'user': {'about_app_sections': {'nodes': list(sections)}}}})


def chunks(*values):
    return envelope('\n'.join(json.dumps(v) for v in values))
