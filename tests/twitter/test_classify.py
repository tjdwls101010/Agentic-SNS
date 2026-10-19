"""x_web classification (fixtures/classify.json): what one GraphQL response means, and what a response the tab's hook
kept means for account protection."""
import pytest

from conftest import fixture
from twitter import guard, x_web

CLASSIFY = fixture('classify.json')


@pytest.mark.parametrize('case', CLASSIFY['responses'], ids=lambda c: c['name'])
def test_response(case):
    verdict = x_web.classify_response(case['envelope'], case['operation'], case['root'])
    expected = case['outcome']
    assert verdict.kind == expected['outcome'], (verdict.kind, verdict.error and verdict.error.message)
    if 'reason' in expected:
        assert verdict.block == expected['reason']
    if 'warnings' in expected:
        assert len(verdict.warnings) == expected['warnings']
    if 'names' in expected:
        assert verdict.names == expected['names']
    if 'bucket' in expected:
        assert verdict.bucket == expected['bucket']
        reset = guard.headers_bucket(case['envelope']['headers'])
        assert (reset or {}).get('reset') == expected['reset']
    if verdict.kind != 'ok':
        assert verdict.error is not None and verdict.error.fix
    else:
        assert verdict.root is not None


@pytest.mark.parametrize('case', CLASSIFY['buckets']['cases'], ids=lambda c: str(c['headers']))
def test_headers_bucket(case):
    found = guard.headers_bucket(case['headers'])
    expected = case['expected']
    assert found == (None if expected is None else {k: expected[k] for k in ('limit', 'remaining', 'reset')})


@pytest.mark.parametrize('case', CLASSIFY['signals']['cases'], ids=lambda c: c['name'])
def test_signal(case):
    expected = case['expected']
    if expected['outcome'] == 'undecided':
        pytest.skip('decided in P2 R6: the hook always knows the URL, so a signal always has a bucket')
    verdict = x_web.classify_signal(case['signal'])
    assert verdict.kind == expected['outcome']
    if 'reason' in expected:
        assert verdict.block == expected['reason']
    if 'bucket' in expected:
        assert verdict.bucket == expected['bucket']
        assert verdict.reset == expected['reset']


def test_bucket_of_a_path():
    assert x_web.bucket_of('/i/api/graphql/abcSYNTH/TweetDetail?variables=x') == 'TweetDetail'
    assert x_web.bucket_of('/i/api/2/notifications/all.json?x=1') == '/i/api/2/notifications/all.json'
    assert x_web.bucket_of('https://x.com/i/api/graphql/abc/Viewer#xs-n1') == 'Viewer'
