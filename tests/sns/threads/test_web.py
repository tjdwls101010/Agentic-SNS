"""sns.threads.web's pure rules: targets, response classification, document sessions and redirects (fixtures: targets,
classify) and which links Threads claims (locate)."""
import json

import pytest

from sns.errors import SnsError
from sns.threads import web
from tests.sns.threads.data import fixture

TARGETS = fixture('targets.json')
CLASSIFY = fixture('classify.json')
KINDS = {'ok': None, 'blocked': 'blocked', 'login': 'login', 'unavailable': 'unavailable', 'failed': 'failed'}


@pytest.mark.parametrize('case', TARGETS['routes']['cases'], ids=lambda c: c['path'])
def test_read_routes(case):
    assert web.route_allowed(case['path']) is case['allowed']


@pytest.mark.parametrize('case', TARGETS['targets']['cases'], ids=lambda c: f"{c['kind']} {c['input']}")
def test_targets(case):
    parse = web.parse_user if case['kind'] == 'user' else web.parse_post
    if case.get('refused'):
        with pytest.raises(SnsError) as error:
            parse(case['input'])
        assert error.value.kind == 'argument' and error.value.fix
        return
    target = parse(case['input'])
    for key, value in case['normalized'].items():
        assert getattr(target, key) == value, key


@pytest.mark.parametrize('case', TARGETS['shortcodes']['cases'], ids=lambda c: c['code'])
def test_shortcode_is_the_post_id(case):
    assert web.shortcode_id(case['code']) == case['post_id']


def test_a_post_target_carries_the_id_its_shortcode_encodes():
    assert web.parse_post('https://www.threads.com/@a/post/CAB').post_id == '8193'


def envelope(case):
    env = dict(case['envelope'])
    if 'json' in env:
        env['body'] = env.pop('prefix', '') + json.dumps(env.pop('json'))
    return env


@pytest.mark.parametrize('case', CLASSIFY['cases'], ids=lambda c: c['name'])
def test_classify(case):
    verdict = web.classify_response(envelope(case), mode=case['mode'])
    expected = case['outcome']
    assert verdict.kind == expected['outcome']
    if expected['outcome'] == 'blocked':
        assert verdict.block == expected['reason']
    if expected['outcome'] == 'failed':
        assert verdict.reason == expected['kind']
    assert (verdict.error.kind if verdict.error else None) == KINDS[expected['outcome']]


def test_a_rate_limit_is_a_hold_and_a_checkpoint_a_person_block():
    """Both are 'blocked' for the verdict, told apart by block: the client raises slot.hold() for the first (it passes
    by itself) and slot.block() for the second (a person clears it)."""
    limited = web.classify_response({'status': 429, 'url': '', 'body': ''}, mode='graphql')
    checkpoint = web.classify_response({'status': 200, 'url': 'https://www.threads.com/challenge/', 'body': ''},
                                       mode='page')
    assert (limited.block, limited.error.reason) == ('rate_limit', 'rate_limited')
    assert (checkpoint.block, checkpoint.error.reason) == ('checkpoint', 'checkpoint')


@pytest.mark.parametrize('case', CLASSIFY['sessions']['cases'], ids=lambda c: c['name'])
def test_document_sessions(case):
    verdict = web.classify_document(case['body'])
    expected = case['outcome']
    assert verdict.kind == expected['outcome']
    if expected['outcome'] == 'ok':
        assert verdict.account_id == expected['account_id'] and verdict.username == expected['username']
    if expected['outcome'] == 'failed':
        assert verdict.reason == expected['kind']


@pytest.mark.parametrize('case', CLASSIFY['redirects']['cases'], ids=lambda c: c['name'])
def test_redirect_rules(case):
    path, outcome, hop = case['path'], None, 0
    for step in case['hops']:
        if step['status'] == 200:
            break
        hop += 1
        outcome = web.follow_redirect(case['path'], step.get('location'), hop)
        if outcome.kind != 'follow':
            break
        path = outcome.path
    expected = case['outcome']
    if expected['outcome'] == 'ok':
        assert outcome.kind == 'follow' and path == expected['final_path']
    else:
        assert outcome.kind == expected['outcome']
        if expected['outcome'] == 'failed':
            assert outcome.reason == expected['kind']


@pytest.mark.parametrize('url, command', [
    ('https://www.threads.com/@example.user/post/DAbc_-12', 'post'),
    ('https://threads.net/@Example.User/post/DAbc_-12?xmt=1', 'post'),
    ('threads.com/t/DAbc_-12', 'post'),
    ('https://www.threads.com/@example.user', 'profile'),
    ('https://threads.net/@example.user/replies', 'profile'),
    ('threads.com/@example.user/media/', 'profile'),
], ids=lambda value: value[-24:])
def test_a_threads_link_is_claimed_with_the_command_that_opens_it(url, command):
    assert web.locate(url) == (command, url)


@pytest.mark.parametrize('url', [
    'https://example.com/@example.user/post/DAbc', 'https://x.com/example_user/status/1',
    'https://www.reddit.com/r/python/comments/abc/title/', 'https://threads.com.evil.example/@example.user',
    'https://www.threads.com/', 'https://www.threads.com/search?q=a', 'https://www.threads.com/activity',
    'https://www.threads.com/@example.user/followers', '@example.user', 'example.user', 'DAbc', '', '   ',
    'https://[broken',
])
def test_what_is_not_a_threads_reading_target_is_not_claimed(url):
    assert web.locate(url) is None
