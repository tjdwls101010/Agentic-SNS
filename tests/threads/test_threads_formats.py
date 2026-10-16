"""threads_web's pure rules: targets, response classification, records (fixtures: targets, classify, records_*)."""
import json

import pytest

from conftest import fixture
from threads import threads_web
from threads.errors import ThreadsError

TARGETS = fixture('targets.json')
CLASSIFY = fixture('classify.json')


@pytest.mark.parametrize('case', TARGETS['routes']['cases'], ids=lambda c: c['path'])
def test_read_routes(case):
    assert threads_web.route_allowed(case['path']) is case['allowed']


@pytest.mark.parametrize('case', TARGETS['targets']['cases'], ids=lambda c: f"{c['kind']} {c['input']}")
def test_targets(case):
    parse = threads_web.parse_user if case['kind'] == 'user' else threads_web.parse_post
    if case.get('refused'):
        with pytest.raises(ThreadsError) as error:
            parse(case['input'])
        assert error.value.code == 2
        return
    target = parse(case['input'])
    for key, value in case['normalized'].items():
        assert getattr(target, key) == value, key


@pytest.mark.parametrize('case', TARGETS['shortcodes']['cases'], ids=lambda c: c['code'])
def test_shortcode_is_the_post_id(case):
    assert threads_web.shortcode_id(case['code']) == case['post_id']


def test_a_post_target_carries_the_id_its_shortcode_encodes():
    assert threads_web.parse_post('https://www.threads.com/@a/post/CAB').post_id == '8193'


def envelope(case):
    env = dict(case['envelope'])
    if 'json' in env:
        env['body'] = env.pop('prefix', '') + json.dumps(env.pop('json'))
    return env


@pytest.mark.parametrize('case', CLASSIFY['cases'], ids=lambda c: c['name'])
def test_classify(case):
    verdict = threads_web.classify_response(envelope(case), mode=case['mode'])
    expected = case['outcome']
    assert verdict.kind == expected['outcome']
    if expected['outcome'] == 'blocked':
        assert verdict.block == expected['reason']
    if expected['outcome'] == 'failed':
        assert verdict.reason == expected['kind']
    codes = {'ok': None, 'blocked': 5, 'login': 4, 'unavailable': 9, 'failed': 6}
    assert (verdict.error.code if verdict.error else None) == codes[expected['outcome']]


@pytest.mark.parametrize('case', CLASSIFY['sessions']['cases'], ids=lambda c: c['name'])
def test_document_sessions(case):
    verdict = threads_web.classify_document(case['body'])
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
        outcome = threads_web.follow_redirect(case['path'], step.get('location'), hop)
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
