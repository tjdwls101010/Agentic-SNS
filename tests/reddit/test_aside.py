"""The Aside unit (fixture aside_output.json): reading what one REPL run printed, telling which Aside account is
active, and what the real fetch snippet sends and prints (run under Node with a fake fetch)."""
import json
import shutil
import subprocess

import pytest

from conftest import TESTS, fixture
from reddit import aside
from reddit.errors import RedditError

OUTPUT = fixture('aside_output.json')
SNIPPET = TESTS.parents[1] / '.claude/skills/reddit/scripts/reddit/aside/fetch.js'
PARSED = [c for c in OUTPUT['cases'] if c.get('exit', 0) == 0 and not c.get('timed_out')]


def subset(expected, actual):
    return all(actual.get(k) == v if not isinstance(v, dict) else subset(v, actual.get(k) or {}) for k, v in expected.items())


@pytest.mark.parametrize('case', PARSED, ids=lambda c: c['name'])
def test_reading_one_run(case):
    if 'envelope' in case['outcome']:
        assert subset(case['outcome']['envelope'], aside.parse(case['stdout']))
    else:
        with pytest.raises(RedditError) as caught:
            aside.parse(case['stdout'])
        assert caught.value.code == 3 and caught.value.reason == case['outcome']['error']


@pytest.mark.parametrize('text, account', [
    ('* u0  viewer@example.com  signed in  profiles: Profile 0\n', 'u0'),
    ('  u0  a@example.com  signed in\n* u1  b@example.com  signed in\n', 'u1'),
    ('\x1b[32m* u2\x1b[0m  c@example.com\n', 'u2'),
    ('  u0  a@example.com  signed in\n', None),                      # nothing marked active
    ('* u0  a\n* u1  b\n', None),                                     # two marked: ambiguous
    ('', None),
    ('* \n', None),
])
def test_active_account(text, account):
    assert aside.active_account(text) == account


def harness(tmp_path, args, response):
    node = shutil.which('node')
    if not node:
        pytest.skip('node is not installed')
    case = tmp_path / 'case.json'
    case.write_text(json.dumps({'snippet': str(SNIPPET), 'args': args, 'response': response}))
    done = subprocess.run([node, str(TESTS / 'snippet_harness.mjs'), str(case)], capture_output=True, text=True,
                          timeout=60, check=True)
    return json.loads(done.stdout)


SNIPPET_CASES = {c['name']: c for c in OUTPUT['snippet']['cases']}


def test_a_path_request_is_a_cookie_bearing_get_without_following_redirects(tmp_path):
    case = SNIPPET_CASES['path-request']
    got = harness(tmp_path, case['args'], {'status': 302, 'body': '', 'headers': {
        'location': '/r/example/hot.json', 'x-ratelimit-used': '3', 'x-ratelimit-remaining': '97.0',
        'x-ratelimit-reset': '200'}})
    fetch, = got['fetches']
    assert fetch['url'] == case['sends']['url']
    assert (fetch['method'], fetch['credentials'], fetch['redirect'], fetch['headers']) == \
        ('GET', 'include', 'manual', {'accept': 'application/json'})
    envelope = aside.parse('\n'.join(got['lines']))
    assert envelope['location'] == '/r/example/hot.json'
    assert envelope['ratelimit'] == {'used': '3', 'remaining': '97.0', 'reset': '200'}


def test_absent_headers_are_null(tmp_path):
    got = harness(tmp_path, {'url': 'https://www.reddit.com/r/example/s/AbC123'}, {'status': 301, 'body': 'x'})
    envelope = aside.parse('\n'.join(got['lines']))
    assert envelope['ratelimit'] == {'used': None, 'remaining': None, 'reset': None}
    assert got['fetches'][0]['url'] == SNIPPET_CASES['share-url-request']['sends']['url']


def test_the_query_is_encoded(tmp_path):
    case = SNIPPET_CASES['query-is-encoded']
    got = harness(tmp_path, case['args'], {'status': 200, 'body': '{}'})
    assert got['fetches'][0]['url'] == case['sends']['url']


@pytest.mark.parametrize('name', ['dot-segment-refused-in-browser', 'share-url-other-host-refused'])
def test_unsafe_requests_throw_before_fetching(tmp_path, name):
    got = harness(tmp_path, SNIPPET_CASES[name]['args'], {'status': 200, 'body': '{}'})
    assert got['error'] and got['fetches'] == []


def test_a_large_body_comes_in_chunks_that_rejoin(tmp_path):
    # quotes double in JSON, so this 1,200,000-character body passes the 8 MiB envelope threshold
    body = '"\\' * 2_800_000
    got = harness(tmp_path, {'path': '/x.json', 'query': {}}, {'status': 200, 'body_repeat': ['"\\', 2_800_000]})
    chunks = [json.loads(line) for line in got['lines'][:-1]]
    assert len(chunks) > 1 and all(len(c['body']) <= 524288 for c in chunks)
    assert aside.parse('\n'.join(got['lines']))['body'] == body


def test_a_surrogate_pair_is_not_split(tmp_path):
    prefix = '"' * 524287
    body = prefix + '\U0001F600' + '"' * 4_500_000  # quotes double in JSON: past the 8 MiB threshold
    got = harness(tmp_path, {'path': '/x.json', 'query': {}}, {'status': 200, 'body': body})
    first = json.loads(got['lines'][0])
    assert first['body'] == prefix
    assert aside.parse('\n'.join(got['lines']))['body'] == body
