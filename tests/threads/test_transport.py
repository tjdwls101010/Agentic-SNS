import json

import pytest

from threads_skill._errors import ThreadsError
from threads_skill._transport import classify


def envelope(body, status=200, url='https://www.threads.com/graphql/query'):
    return {'status': status, 'url': url, 'body': body if isinstance(body, str) else json.dumps(body)}


@pytest.mark.parametrize('body,status,url,code,kind', [
    ({'errors': [{'message': 'checkpoint_required'}]}, 429, '', 5, 'checkpoint'),
    ({'error': {'error_subcode': 368}}, 200, '', 5, 'checkpoint'),
    ({'errors': [{'code': 459}]}, 200, '', 5, 'checkpoint'),
    ({}, 429, '', 5, 'rate_limit'),
    ({'error_code': 17}, 200, '', 5, 'rate_limit'),
    ({'error_code': '368'}, 200, '', 5, 'checkpoint'),
    ({'error_subcode': '459'}, 200, '', 5, 'checkpoint'),
    ({'errors': [{'message': 'login_required'}]}, 200, '', 4, 'login'),
    ('', 302, 'https://www.threads.com/accounts/login/', 4, 'login'),
    ('bad gateway', 502, '', 6, 'transient'),
    ('{"data":', 200, '', 6, 'transient'),
    ({'errors': [{'message': 'execution error', 'severity': 'CRITICAL'}], 'data': None}, 200, '', 6, 'operation_rotated'),
    ({'data': {'user': None}}, 200, '', 6, 'envelope_drift'),
])
def test_error_contract(body, status, url, code, kind):
    with pytest.raises(ThreadsError) as error:
        classify(envelope(body, status, url), 'graphql')
    assert (error.value.code, error.value.error) == (code, kind)


def test_normal_post_text_does_not_block_and_partial_data_is_readable():
    payload = {'data': {'feedData': {'edges': [{'caption': 'challenge try again later checkpoint_required'}]}},
               'errors': [{'message': 'field_exception', 'path': ['optional_field']}]}
    assert classify(envelope(payload), 'graphql') == payload
    html = '<script type="application/json">{"caption":{"text":"checkpoint_required challenge"}}</script>'
    assert classify(envelope(html), 'page') == html


def test_structural_html_challenge_and_post_redirect_evidence():
    with pytest.raises(ThreadsError) as error:
        classify(envelope('<form action="/challenge/"></form>'), 'page')
    assert error.value.error == 'checkpoint'


def test_error_paths_and_source_locations_are_not_rate_limit_codes():
    payload = {'data': {'feedData': {'edges': []}}, 'errors': [{'message': 'field_exception',
        'path': ['feedData', 'edges', 4, 'caption'], 'locations': [{'line': 17, 'column': 4}]}]}
    assert classify(envelope(payload), 'graphql') == payload


def test_query_validates_operation_shape_at_the_transport_boundary(monkeypatch):
    from threads_skill import _transport
    from threads_skill._session import Session
    transport = _transport.Transport()
    transport.session = Session('fixture', '42', 'fixture', [])
    monkeypatch.setattr(_transport, 'run_snippet', lambda *args: envelope({'data': {'unexpected': True}}))
    with pytest.raises(ThreadsError) as error:
        transport.query('BarcelonaFeedDirectQuery', {'variant': 'for_you',
            'data': {'pagination_source': 'text_post_feed_threads', 'reason': 'cold_start_fetch'}})
    assert error.value.error == 'envelope_drift'
