import json
from pathlib import Path

import pytest

from _errors import FacebookError

HOME = {'status': 200, 'url': 'https://www.facebook.com/', 'body': '"USER_ID":"123" "DTSGInitialData",[],{"token":"test&+한"} "LSD",[],{"token":"test-lsd"} "__spin_r":456'}


def envelope(data=None, *, body=None, status=200, url='https://www.facebook.com/api/graphql/'):
    return {'status': status, 'url': url, 'body': json.dumps(data) if body is None else body}


def feed(edges=None):
    return envelope({'data': {'viewer': {'news_feed': {'edges': [{'node': {'id': 'synthetic'}}] if edges is None else edges, 'page_info': {'has_next_page': False, 'end_cursor': None}}}}})


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('FACEBOOK_HOME', str(tmp_path))
    monkeypatch.setenv('FACEBOOK_ASIDE_BIN', str(Path(__file__).with_name('fake_aside') / 'aside'))


@pytest.mark.parametrize('response,code', [
    (envelope({'checkpoint_url': '/checkpoint/', 'error': 1357001}, status=429), 5),
    (envelope({}, url='https://www.facebook.com/checkpoint/'), 5),
    (envelope({'error': 1357001}, status=429), 4),
    (envelope({'caa_login_form_data': {}}), 4),
    (envelope({}, status=429), 5),
    (envelope({'error': 1357004}), 5),
    (envelope({'errors': [{'message': 'secret'}]}), 6),
    (envelope(body='not json'), 6),
    (envelope({'data': {'unrelated': {'edges': []}}}), 6),
    (feed([]), 7),
])
def test_response_classification_order(response, code, tmp_path):
    from _transport import classify
    from _registry import get_query
    with pytest.raises(FacebookError) as error:
        classify(response, get_query('newsfeed'))
    assert error.value.code == code
    assert 'secret' not in error.value.message
    assert (tmp_path / 'blocked.json').exists() == (code == 5)


@pytest.mark.parametrize('connection', [None, {}, [], {'edges': None}, {'edges': 'bad'}, {'edges': [None]}, {'edges': [{'node': None}]}, {'edges': [], 'page_info': {'has_next_page': 'false'}}])
def test_connections_must_be_structural_not_just_present(connection):
    from _transport import classify
    with pytest.raises(FacebookError) as error:
        classify(envelope({'data': {'news_feed': connection}}), 'news_feed')
    assert error.value.code == 6


def queued(tmp_path, monkeypatch, responses):
    path = tmp_path / 'responses.json'
    path.write_text(json.dumps(responses))
    monkeypatch.setenv('FAKE_ASIDE_RESPONSES', str(path))
    monkeypatch.setenv('FAKE_ASIDE_LOG', str(tmp_path / 'calls.jsonl'))
    return path


def test_lazy_start_html_query_share_budget_and_keep_tokens_in_memory(tmp_path, monkeypatch):
    from _transport import Transport
    monkeypatch.setattr('time.sleep', lambda seconds: None)
    queued(tmp_path, monkeypatch, [HOME, envelope(body='<html>profile</html>'), feed()])
    transport = Transport(limit=3)
    assert transport.request_count == 0 and transport.tokens == {} and transport.account_id is None
    assert not (tmp_path / 'calls.jsonl').exists()
    transport.start()
    assert transport.account_id == '123' and transport.request_count == 1
    transport.start()
    assert transport.request_count == 1
    assert transport.html('https://www.facebook.com/synthetic')['body'] == '<html>profile</html>'
    assert isinstance(transport.query('newsfeed'), bytes)
    assert transport.request_count == 3
    with pytest.raises(FacebookError) as error:
        transport.html('https://www.facebook.com/synthetic')
    assert error.value.code == 8
    assert len((tmp_path / 'calls.jsonl').read_text().splitlines()) == 3
    for name in ['blocked.json', 'pace.json']:
        path = tmp_path / name
        if path.exists():
            assert 'test&+한' not in path.read_text()


@pytest.mark.parametrize('twice', [False, True])
def test_1357054_gets_exactly_one_budgeted_retry_before_block(tmp_path, monkeypatch, twice):
    from _transport import Transport
    from _blocked import check_blocked
    monkeypatch.setattr('time.sleep', lambda seconds: None)
    temporary_error = envelope({'errors': [{'code': 1357054}]})
    queued(tmp_path, monkeypatch, [HOME, temporary_error, temporary_error if twice else feed()])
    transport = Transport()
    if twice:
        with pytest.raises(FacebookError) as error:
            transport.query('newsfeed')
        assert error.value.code == 5
        with pytest.raises(FacebookError):
            check_blocked()
        with pytest.raises(FacebookError) as error:
            Transport().start()
        assert error.value.code == 5
    else:
        transport.query('newsfeed')
        assert check_blocked() is None
    assert transport.request_count == 3
    assert len((tmp_path / 'calls.jsonl').read_text().splitlines()) == 3


@pytest.mark.parametrize('surface', ['home', 'html'])
def test_non_graphql_requests_persist_blocks(tmp_path, monkeypatch, surface):
    from _transport import Transport
    monkeypatch.setattr('time.sleep', lambda seconds: None)
    responses = [envelope(body='rate limited', status=429)]
    queued(tmp_path, monkeypatch, responses)
    transport = Transport()
    with pytest.raises(FacebookError) as error:
        transport.start() if surface == 'home' else transport.html('https://www.facebook.com/synthetic')
    assert error.value.code == 5
    assert transport.request_count == 1
    with pytest.raises(FacebookError):
        Transport().html('https://www.facebook.com/synthetic')
    assert len((tmp_path / 'calls.jsonl').read_text().splitlines()) == 1


@pytest.mark.parametrize('key,value', [('newsfeed', {'news_feed': {'edges': [{'node': {'id': 'x'}}]}}), ('timeline', {'timeline_list_feed_units': {'edges': [{'node': {'id': 'x'}}]}}), ('group', {'group_feed': {'edges': [{'node': {'id': 'x'}}]}}), ('search', {'results': {'edges': [{'node': {'id': 'x'}}]}}), ('comments', {'comments': {'edges': [{'node': {'id': 'x'}}]}}), ('comments_page', {'comments': {'edges': [{'node': {'id': 'x'}}]}}), ('replies', {'replies_connection': {'edges': [{'node': {'id': 'x'}}]}}), ('about', {'about_app_sections': {'nodes': [{'id': 'x'}]}}), ('post', {'node': {'id': 'x', '__typename': 'Story'}})])
def test_all_registry_queries_validate_their_structure(key, value):
    from _registry import get_query
    from _transport import classify
    assert classify(envelope({'data': value}), get_query(key))


@pytest.mark.parametrize('tail', ['\n{"errors":[{"severity":"CRITICAL"}],"data":{"x":1}}', '\n{"errors":[{"message":"failed"}]}', '\n{broken'])
def test_later_chunk_failures_override_an_earlier_connection(tail):
    from _transport import classify
    with pytest.raises(FacebookError) as error:
        classify(envelope(body=feed()['body'] + tail), 'news_feed')
    assert error.value.code == 6


def test_pacing_and_blocking_are_shared_between_concurrent_cli_processes(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    from _blocked import unblock
    script = "from _transport import Transport; from _errors import FacebookError\nt = Transport()\ntry:\n t.html('https://www.facebook.com/synthetic')\nexcept FacebookError as e:\n raise SystemExit(e.code)"
    queued(tmp_path, monkeypatch, [envelope(body='first'), envelope(body='second')])
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2] / '.claude/skills/facebook/scripts'))
    processes = [subprocess.Popen([sys.executable, '-c', script], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    for process in processes:
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        assert not stdout
    calls = [json.loads(line) for line in (tmp_path / 'calls.jsonl').read_text().splitlines()]
    assert calls[1]['time'] - calls[0]['time'] >= 1.0
    (tmp_path / 'calls.jsonl').unlink()
    queued(tmp_path, monkeypatch, [envelope(body='limited', status=429)])
    processes = [subprocess.Popen([sys.executable, '-c', script], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    for process in processes:
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 5, stderr
        assert not stdout
    assert len((tmp_path / 'calls.jsonl').read_text().splitlines()) == 1
    unblock()


def test_budget_includes_failed_home_and_retry_and_caps_at_400(tmp_path, monkeypatch):
    from _transport import Transport
    monkeypatch.setattr('time.sleep', lambda seconds: None)
    queued(tmp_path, monkeypatch, [HOME, envelope({'error': 1357054})])
    transport = Transport(limit=2)
    with pytest.raises(FacebookError) as error:
        transport.query('newsfeed')
    assert error.value.code == 8
    assert transport.request_count == 2
    assert Transport(limit=401).limit == 400
    assert Transport().limit == 25


@pytest.mark.parametrize('url', ['https://facebook.com.evil.test/', 'http://www.facebook.com/', 'https://www.facebook.com:999/', 'https://u:p@www.facebook.com/', 'file:///etc/passwd'])
def test_invalid_urls_fail_before_any_request(url):
    from _transport import Transport
    transport = Transport()
    with pytest.raises(FacebookError) as error:
        transport.html(url)
    assert error.value.code == 2
    assert transport.request_count == 0


def test_html_query_error_is_classified_instead_of_being_treated_as_html(tmp_path, monkeypatch):
    from _transport import Transport
    queued(tmp_path, monkeypatch, [envelope({'errors': [{'severity': 'CRITICAL', 'message': 'secret'}]})])
    with pytest.raises(FacebookError) as error:
        Transport().html('https://www.facebook.com/synthetic')
    assert error.value.code == 6
    assert 'secret' not in error.value.message


def test_home_failure_preserves_the_budget_and_cannot_start_a_query(tmp_path, monkeypatch):
    from _transport import Transport
    queued(tmp_path, monkeypatch, [envelope(body='"USER_ID":"0"')])
    transport = Transport()
    with pytest.raises(FacebookError) as error:
        transport.query('newsfeed')
    assert error.value.code == 4
    assert transport.request_count == 1
    assert transport.tokens == {} and transport.account_id is None


@pytest.mark.parametrize('edges,has_next,code', [([{'node': {'id': 'x'}}], False, None), ([], False, 7), ([], True, None), ([], None, None)])
def test_inline_connection_and_deferred_page_info_are_classified_together(edges, has_next, code):
    from _transport import classify
    chunks = [{'data': {'viewer': {'news_feed': {'edges': edges}}}}]
    info = {'end_cursor': 'next'}
    if has_next is not None:
        info['has_next_page'] = has_next
    chunks.append({'path': ['viewer', 'news_feed'], 'data': {'page_info': info}})
    response = envelope(body='\n'.join(map(json.dumps, chunks)))
    if code:
        with pytest.raises(FacebookError) as error:
            classify(response, 'news_feed')
        assert error.value.code == code
    else:
        assert classify(response, 'news_feed') == chunks


def test_deferred_metadata_cannot_supply_edges_from_a_different_connection():
    from _transport import classify
    body = feed()['body'] + '\n' + json.dumps({'path': ['other', 'news_feed'], 'data': {'page_info': {'has_next_page': False}}})
    with pytest.raises(FacebookError) as error:
        classify(envelope(body=body), 'news_feed')
    assert error.value.code == 6


def test_empty_inline_connection_with_more_pages_returns_to_paginator():
    from _transport import classify
    for info in ({'has_next_page': True, 'end_cursor': 'next'}, {}):
        response = envelope({'data': {'news_feed': {'edges': [], 'page_info': info}}})
        assert classify(response, 'news_feed')


def test_candidate_replay_uses_supplied_spec_without_saving_it(tmp_path, monkeypatch):
    from dataclasses import replace
    from _registry import get_query
    from _transport import Transport
    monkeypatch.setattr('time.sleep', lambda seconds: None)
    original = get_query('newsfeed')
    candidate = replace(original, doc_id='999')
    monkeypatch.setenv('FAKE_ASIDE_EXPECTED_ARGS', json.dumps({'graphql': {'doc_id': '999', 'referer': 'https://www.facebook.com/me'}}))
    queued(tmp_path, monkeypatch, [HOME, feed()])
    transport = Transport(limit=2)
    assert isinstance(transport.query_spec(candidate, {'count': 1}, 'https://www.facebook.com/me'), bytes)
    assert transport.request_count == 2
    assert get_query('newsfeed').doc_id == original.doc_id
    assert not (tmp_path / 'registry.json').exists()
    with pytest.raises(FacebookError) as error:
        transport.query_spec(candidate)
    assert error.value.code == 8


@pytest.mark.parametrize('response,code', [(envelope({'queries': [], 'missing': [], 'failed': None, 'request_count': 1, 'count_complete': True}), None), (envelope(body='limited', status=429), 5), (envelope({}, url='https://www.facebook.com/checkpoint/'), 5), (envelope({'queries': [], 'failed': 'capture_timeout'}), 6)])
def test_capture_uses_the_same_budget_and_block_guard(tmp_path, monkeypatch, response, code):
    from _transport import Transport
    monkeypatch.setattr('time.sleep', lambda seconds: None)
    queued(tmp_path, monkeypatch, [response])
    transport = Transport(limit=1)
    args = {'url': 'https://www.facebook.com/synthetic/posts/1', 'targets': ['CommentListComponentsRootQuery']}
    if code:
        with pytest.raises(FacebookError) as error:
            transport.capture(args)
        assert error.value.code == code
    else:
        assert transport.capture(args) == response
    assert transport.request_count == 1
    with pytest.raises(FacebookError) as error:
        transport.html('https://www.facebook.com/synthetic')
    assert error.value.code == (5 if code == 5 else 8)
    assert len((tmp_path / 'calls.jsonl').read_text().splitlines()) == 1


def test_candidate_replay_also_persists_checkpoint_blocks(tmp_path, monkeypatch):
    from _registry import get_query
    from _transport import Transport
    monkeypatch.setattr('time.sleep', lambda seconds: None)
    queued(tmp_path, monkeypatch, [HOME, envelope({'challenge_url': '/checkpoint/'})])
    transport = Transport()
    with pytest.raises(FacebookError) as error:
        transport.query_spec(get_query('newsfeed'))
    assert error.value.code == 5
    with pytest.raises(FacebookError) as error:
        Transport().capture({'url': 'https://www.facebook.com/synthetic/posts/1', 'targets': ['CommentListComponentsRootQuery']})
    assert error.value.code == 5
    assert len((tmp_path / 'calls.jsonl').read_text().splitlines()) == 2


def test_capture_reserves_remaining_budget_and_reconciles_actual_dispatches(tmp_path, monkeypatch):
    from _transport import Transport
    monkeypatch.setattr('time.sleep', lambda seconds: None)
    monkeypatch.setenv('FAKE_ASIDE_EXPECTED_ARGS', json.dumps({'capture': {'request_budget': 4}}))
    captured = envelope({'queries': [], 'envelopes': [], 'failed': None, 'request_count': 3, 'count_complete': True})
    queued(tmp_path, monkeypatch, [captured, envelope(body='page')])
    transport = Transport(limit=4)
    transport.capture({'url': 'https://www.facebook.com/synthetic/posts/1', 'targets': ['CommentListComponentsRootQuery']})
    assert transport.request_count == 3
    transport.html('https://www.facebook.com/synthetic')
    assert transport.request_count == 4


@pytest.mark.parametrize('observed', [envelope(status=429), envelope({'checkpoint_url': '/checkpoint/'})])
def test_capture_observed_response_persists_block_before_releasing_lock(tmp_path, monkeypatch, observed):
    from _transport import Transport
    from _blocked import check_blocked
    captured = envelope({'queries': [], 'envelopes': [observed], 'failed': 'capture_blocked', 'request_count': 2, 'count_complete': True})
    queued(tmp_path, monkeypatch, [captured])
    transport = Transport(limit=4)
    with pytest.raises(FacebookError) as error:
        transport.capture({'url': 'https://www.facebook.com/synthetic/posts/1', 'targets': ['CommentListComponentsRootQuery']})
    assert error.value.code == 5
    assert transport.request_count == 2
    with pytest.raises(FacebookError):
        check_blocked()


def test_capture_missing_count_keeps_whole_reservation(tmp_path, monkeypatch):
    from _transport import Transport
    queued(tmp_path, monkeypatch, [envelope({'queries': [], 'envelopes': [], 'failed': 'capture_timeout', 'request_count': 1, 'count_complete': False})])
    transport = Transport(limit=4)
    with pytest.raises(FacebookError):
        transport.capture({'url': 'https://www.facebook.com/synthetic/posts/1', 'targets': ['CommentListComponentsRootQuery']})
    assert transport.request_count == 4


def test_navigation_only_capture_exhausts_one_request_budget(tmp_path, monkeypatch):
    from _transport import Transport
    monkeypatch.setenv('FAKE_ASIDE_EXPECTED_ARGS', json.dumps({'capture': {'request_budget': 1}}))
    queued(tmp_path, monkeypatch, [envelope({'queries': [], 'envelopes': [], 'failed': 'capture_budget', 'request_count': 1, 'count_complete': True})])
    transport = Transport(limit=1)
    with pytest.raises(FacebookError) as error:
        transport.capture({'url': 'https://www.facebook.com/synthetic/posts/1', 'targets': ['CommentListComponentsRootQuery'], 'request_budget': 400})
    assert error.value.code == 8
    assert transport.request_count == 1
