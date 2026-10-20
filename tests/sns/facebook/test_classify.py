"""What a Facebook response means for the account and the read (fixtures/classify.json): the order of the stops and
what each one is. Where a body names a checkpoint only by a key, the key must carry something."""
import json
import re

import pytest

from sns.errors import SnsError
from sns.facebook import web
from tests.sns.facebook.data import fixture
from tests.sns.facebook.scenes import ACCOUNT

CASES = fixture('classify.json')['cases']
GRAPHQL = {'mode': 'graphql', 'expected': ('news_feed', 'connection')}


def envelope(case):
    env = dict(case['envelope'])
    if 'body_lines' in env:
        env['body'] = env.pop('prefix', '') + '\n'.join(json.dumps(line) for line in env.pop('body_lines'))
    env.pop('prefix', None)
    return env


def outcome(case):
    if case['mode'] == 'home':
        user = re.search(r'"USER_ID"\s*:\s*"(\d+)"', case['envelope']['body'])
        verdict = web.classify_location(case['envelope']['url'], user.group(1) if user else None)
    else:
        expected = case.get('expected')
        verdict = web.classify_response(envelope(case), mode=case['mode'],
                                        expected=(expected['key'], expected['kind']) if expected else None,
                                        retried=case.get('retried', False))
    if verdict.kind == 'blocked':
        return {'outcome': 'blocked', 'reason': verdict.block}
    if verdict.kind == 'rate_limited':
        return {'outcome': 'blocked', 'reason': 'rate_limit'}
    if verdict.kind in ('failed', 'stale'):
        assert verdict.error.kind == 'failed'
        return {'outcome': 'failed'}
    if verdict.kind == 'login':
        assert verdict.error.kind == 'login'
    result = {'outcome': verdict.kind}
    if verdict.kind == 'ok' and case['mode'] == 'graphql':
        result['chunks'] = len(verdict.chunks)
    return result


@pytest.mark.parametrize('case', [pytest.param(c, id=c['name']) for c in CASES])
def test_response_classification(case):
    expected = dict(case['outcome'])
    if case['mode'] != 'graphql':
        expected.pop('chunks', None)
    assert outcome(case) == expected


def graphql_body(*lines, url='https://www.facebook.com/api/graphql/', status=200):
    return {'status': status, 'url': url, 'body': '\n'.join(json.dumps(line) for line in lines)}


def verdict_of(payload):
    return web.classify_response(graphql_body(payload), mode='graphql', expected=('news_feed', 'connection'))


@pytest.mark.parametrize('key', ['checkpoint_url', 'challenge_url'])
def test_a_checkpoint_key_with_a_value_is_a_checkpoint(key):
    """A checkpoint response names where to go; the key with an address in it is the signal (the old key-only rule's
    positive half, still held)."""
    verdict = verdict_of({'error': 1357053, key: 'https://www.facebook.com/checkpoint/x/'})
    assert verdict.kind == 'blocked' and verdict.block == 'checkpoint' and verdict.error.kind == 'blocked'


@pytest.mark.parametrize('value', [None, False, '', [], {}])
@pytest.mark.parametrize('key', ['checkpoint_url', 'challenge_url'])
def test_a_checkpoint_key_with_nothing_in_it_is_not_a_checkpoint(key, value):
    """Decided (appendix C: has_key fired on a null checkpoint_url): a key that names no checkpoint is the field being
    absent. A false person block costs a human a trip to the browser; none of the live responses ever carried the key,
    so the safe reading is the one where only a present value is taken as the signal."""
    data = {'viewer': {'news_feed': {'edges': [{'node': {'feedback': {'id': 'F1'}}}],
                                     'page_info': {'has_next_page': False, 'end_cursor': None}}}}
    verdict = verdict_of({'data': data, key: value})
    assert verdict.kind == 'ok'


def test_a_null_checkpoint_key_inside_a_html_page_is_not_a_checkpoint_either():
    page = {'status': 200, 'url': 'https://www.facebook.com/some.person',
            'body': '<script>{"checkpoint_url":null,"challenge_url":"","userID":"4"}</script>'}
    assert web.classify_response(page, mode='html').kind == 'ok'
    page['body'] = '<script>{"challenge_url":"https://www.facebook.com/checkpoint/1/"}</script>'
    assert web.classify_response(page, mode='html').block == 'checkpoint'


def test_a_checkpoint_outranks_a_login_and_a_login_outranks_a_rate_limit():
    both = {'error': 1357001, 'checkpoint_url': 'https://www.facebook.com/checkpoint/x/'}
    assert web.classify_response(graphql_body(both), mode='graphql').kind == 'blocked'
    login_and_limit = web.classify_response(graphql_body({'error': 1357001}, status=429), mode='graphql')
    assert login_and_limit.kind == 'login'


def test_a_missing_page_is_unavailable_not_a_failure():
    """Only an explicit 404 for a page the user named: Facebook saying there is nothing there for this account."""
    verdict = web.classify_response({'status': 404, 'url': 'https://www.facebook.com/no.such', 'body': 'x'},
                                    mode='html')
    assert verdict.kind == 'unavailable' and verdict.error.kind == 'unavailable'
    graphql = web.classify_response(graphql_body({'data': {}}, status=404), mode='graphql')
    assert graphql.kind == 'failed'  # a query that 404s is the query's fault, not a missing target


@pytest.mark.parametrize('name', ['CheckPointSoftware', 'loginradius', 'recoveryhelp', 'checkpoint.fans'])
def test_a_page_whose_name_only_starts_like_a_screen_is_an_ordinary_page(name):
    """A vanity name that begins with checkpoint, login or recover is a profile, not the checkpoint or login screen
    (matching by prefix recorded a person block for a harmless read)."""
    url = f'https://www.facebook.com/{name.lower()}'
    assert web.classify_response({'status': 200, 'url': url, 'body': '<html>x</html>'}, mode='html').kind == 'ok'
    assert web.classify_location(url, ACCOUNT).kind == 'ok'


@pytest.mark.parametrize('path', ['/checkpoint', '/checkpoint/', '/checkpoint/1501092823525282/', '/login', '/login/',
                                  '/login.php', '/recover/initiate'])
def test_the_screens_themselves_are_matched_whole(path):
    kind = web.classify_location('https://www.facebook.com' + path, ACCOUNT).kind
    assert kind == ('blocked' if 'checkpoint' in path else 'login')


@pytest.mark.parametrize('value', [0, True, ' ', [[]]])
def test_a_checkpoint_value_must_name_something_in_the_body_and_in_the_text_alike(value):
    """The decoded body and the text scan agree: only a non-blank string, or a non-empty object or list, counts."""
    data = {'viewer': {'news_feed': {'edges': [{'node': {'feedback': {'id': 'F1'}}}],
                                     'page_info': {'has_next_page': False, 'end_cursor': None}}}}
    decoded = verdict_of({'data': data, 'checkpoint_url': value}).kind
    text = web.classify_response({'status': 200, 'url': 'https://www.facebook.com/x',
                                  'body': '<script>{"checkpoint_url": %s}</script>' % json.dumps(value)},
                                 mode='html').kind
    assert decoded == text


def test_every_error_the_classifier_makes_is_a_sns_error():
    for status in (500, 403):
        verdict = web.classify_response({'status': status, 'url': 'https://www.facebook.com/x', 'body': 'x'},
                                        mode='html')
        assert isinstance(verdict.error, SnsError)
