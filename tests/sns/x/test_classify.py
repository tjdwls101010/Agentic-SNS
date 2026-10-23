"""x.web classification (fixtures/classify.json): what one GraphQL response means, and what a response the tab's hook
kept means for account protection."""
import pytest

from sns.limits import Fact
from sns.x import web
from tests.sns.x.data import fixture

CLASSIFY = fixture('classify.json')


@pytest.mark.parametrize('case', CLASSIFY['responses'], ids=lambda c: c['name'])
def test_response(case):
    verdict = web.classify_response(case['envelope'], case['operation'], case['root'])
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
        found = web.fact(case['envelope']['headers'])
        assert (found.reset_at if found else None) == expected['reset']
    if verdict.kind == 'ok':
        assert verdict.root is not None
    elif verdict.kind != 'rate_limited':  # a limit's stop is named by the guard (slot.hold), not by the verdict
        assert verdict.error is not None and verdict.error.fix


@pytest.mark.parametrize('case', CLASSIFY['buckets']['cases'], ids=lambda c: str(c['headers']))
def test_headers_fact(case):
    found = web.fact(case['headers'])
    expected = case['expected']
    assert found == (None if expected is None else Fact(expected['limit'], expected['remaining'], expected['reset']))


@pytest.mark.parametrize('case', CLASSIFY['signals']['cases'], ids=lambda c: c['name'])
def test_signal(case):
    expected = case['expected']
    verdict = web.classify_signal(case['signal'])
    assert verdict.kind == expected['outcome']
    if 'reason' in expected:
        assert verdict.block == expected['reason']
    if 'bucket' in expected:
        assert verdict.bucket == expected['bucket']
        assert verdict.reset == expected['reset']


def test_every_signal_has_a_url_so_it_has_a_bucket():
    """The hook always knows the URL (P2 R6), so a limit signal always names the operation or REST path it counts for."""
    for case in CLASSIFY['signals']['cases']:
        if case['expected']['outcome'] == 'rate_limited':
            assert case['signal'].get('path'), case['name']
            assert web.classify_signal(case['signal']).bucket


def test_bucket_of_a_path():
    assert web.bucket_of('/i/api/graphql/abcSYNTH/TweetDetail?variables=x') == 'TweetDetail'
    assert web.bucket_of('/i/api/2/notifications/all.json?x=1') == '/i/api/2/notifications/all.json'
    assert web.bucket_of('https://x.com/i/api/graphql/abc/Viewer#xs-n1') == 'Viewer'
