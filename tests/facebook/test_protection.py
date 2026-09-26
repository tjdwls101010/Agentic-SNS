"""Account protection seen from outside: classification, persisted blocks, pacing, retries and the request budget."""
import json
import os
import subprocess
import sys
import time

import pytest

from tests.facebook.helpers import (CLI, FAKE_ASIDE, LIMITED, PROCESS_DOUBLES, Account, envelope, feed_page,
                                    login, profile_page)


def graphql(data=None, *, body=None, status=200, url='https://www.facebook.com/api/graphql/'):
    return envelope(json.dumps(data) if body is None else body, status=status, url=url)


def news_feed(edges=None):
    return graphql({'data': {'viewer': {'news_feed': {
        'edges': [{'node': {'feedback': {'id': 'synthetic'}}}] if edges is None else edges,
        'page_info': {'has_next_page': False, 'end_cursor': None}}}}})


@pytest.mark.parametrize('response,code', [
    (graphql({'checkpoint_url': '/checkpoint/', 'error': 1357001}, status=429), 5),
    (graphql({}, url='https://www.facebook.com/checkpoint/'), 5),
    (graphql({'error': 1357001}, status=429), 4),
    (graphql({'caa_login_form_data': {}}), 4),
    (graphql({}, status=429), 5),
    (graphql({'error': 1357004}), 5),
    (graphql({'errors': [{'message': 'secret'}]}), 6),
    (graphql(body='not json'), 6),
    (graphql({'data': {'unrelated': {'edges': []}}}), 6),
    (news_feed([]), 7),
])
def test_responses_are_classified_in_protection_order_and_only_blocks_persist(tmp_path, response, code):
    account = Account(tmp_path)
    result = account.run('feed', '--json', responses=[login(), response])
    assert result.code == code, result.stdout
    assert 'secret' not in result.stdout + result.stderr
    assert account.blocked() == (code == 5)


@pytest.mark.parametrize('connection', [None, {}, [], {'edges': None}, {'edges': 'bad'}, {'edges': [None]},
                                        {'edges': [{'node': None}]},
                                        {'edges': [], 'page_info': {'has_next_page': 'false'}}])
def test_connections_must_be_structural_not_just_present(tmp_path, connection):
    result = Account(tmp_path).run('feed', responses=[login(), graphql({'data': {'news_feed': connection}})])
    assert result.code == 6, result.stdout


@pytest.mark.parametrize('tail', ['\n{"errors":[{"severity":"CRITICAL"}],"data":{"x":1}}',
                                  '\n{"errors":[{"message":"failed"}]}', '\n{broken'])
def test_later_chunk_failures_override_an_earlier_connection(tmp_path, tail):
    body = news_feed()['body'] + tail
    assert Account(tmp_path).run('feed', responses=[login(), graphql(body=body)]).code == 6


def test_checkpoint_persists_until_explicit_unblock_even_for_refresh(tmp_path):
    account = Account(tmp_path)
    assert account.run('feed', responses=[login(), graphql({'challenge_url': '/checkpoint/'})]).code == 5
    record = json.loads((account.home / 'blocked.json').read_text())
    assert (record['reason'], record['expires_at']) == ('checkpoint', None)
    assert account.blocked()
    refresh = account.run('refresh')
    assert refresh.code == 5 and refresh.calls == []
    unblocked = account.run('doctor', '--unblock', '--json', responses=[login()])
    assert unblocked.code == 0 and unblocked.data['results'][0]['blocked'] is False
    assert account.run('feed', '--limit', '1', responses=[login(), feed_page(['p1'])]).code == 0


def test_rate_limit_blocks_for_thirty_minutes_then_expires(tmp_path):
    account = Account(tmp_path)
    before = time.time()
    assert account.run('feed', responses=[login(), LIMITED]).code == 5
    record = json.loads((account.home / 'blocked.json').read_text())
    assert record['reason'] == 'rate_limit'
    assert before + 1800 <= record['expires_at'] <= time.time() + 1800
    assert account.blocked()
    record['expires_at'] = time.time() - 1
    (account.home / 'blocked.json').write_text(json.dumps(record))
    assert account.run('feed', '--limit', '1', responses=[login(), feed_page(['p1'])]).code == 0


@pytest.mark.parametrize('name,text', [('blocked.json', '{broken'), ('pace.json', '{broken'),
                                       ('pace.json', '{"next_allowed_at": "soon"}')])
def test_unreadable_protection_state_fails_closed(tmp_path, name, text):
    account = Account(tmp_path)
    account.home.mkdir(parents=True)
    (account.home / name).write_text(text)
    result = account.run('feed', responses=[login(), feed_page(['p1'])])
    assert result.code == 5 and result.calls == []


@pytest.mark.parametrize('twice', [False, True])
def test_1357054_gets_exactly_one_budgeted_retry_before_block(tmp_path, twice):
    account = Account(tmp_path)
    temporary = graphql({'errors': [{'code': 1357054}]})
    result = account.run('feed', '--json', responses=[login(), temporary, temporary if twice else news_feed()])
    assert result.snippets == ['tokens', 'graphql', 'graphql']
    if twice:
        assert result.code == 5
        assert account.blocked()
    else:
        assert result.code == 0 and result.data['request_count'] == 3
        assert not account.blocked()


@pytest.mark.parametrize('surface', ['home', 'html'])
def test_non_graphql_requests_persist_blocks(tmp_path, surface):
    account = Account(tmp_path)
    limited = graphql(body='rate limited', status=429)
    responses = [limited] if surface == 'home' else [login(), limited]
    result = account.run('profile', 'synthetic.vanity', responses=responses)
    assert result.code == 5
    assert result.snippets == (['tokens'] if surface == 'home' else ['tokens', 'page'])
    assert account.blocked()


def test_html_query_error_is_classified_instead_of_being_treated_as_html(tmp_path):
    result = Account(tmp_path).run('profile', 'synthetic.vanity', responses=[
        login(), graphql({'errors': [{'severity': 'CRITICAL', 'message': 'secret'}]})])
    assert result.code == 6 and 'secret' not in result.stdout


def test_home_failure_stops_before_any_query(tmp_path):
    result = Account(tmp_path).run('feed', responses=[envelope('"USER_ID":"0"', url='https://www.facebook.com/')])
    assert result.code == 4
    assert result.snippets == ['tokens']


def test_home_tokens_are_used_in_memory_and_never_written_to_state(tmp_path):
    account = Account(tmp_path)
    tokens = {'user_id': '123', 'fb_dtsg': 'a&+한', 'lsd': 'l+&', 'jazoest': '254798', '__spin_r': '456',
              '__rev': '456'}
    result = account.run('profile', 'synthetic.vanity', '--limit', '1', expected={'graphql': {'tokens': tokens}},
                         responses=[login(user='123', dtsg='a&+한', lsd='l+&', spin='456'), profile_page('4'),
                                    feed_page_for_profile()])
    assert result.code == 0, result.stdout + result.stderr
    assert result.snippets == ['tokens', 'page', 'graphql']
    for path in account.home.rglob('*'):
        if path.is_file():
            assert 'a&+한' not in path.read_text(errors='replace')


def feed_page_for_profile():
    return graphql({'data': {'node': {'timeline_list_feed_units': {
        'edges': [{'node': {'feedback': {'id': 'p1'}, 'message': {'text': 'x'}}}],
        'page_info': {'has_next_page': False, 'end_cursor': None}}}}})


@pytest.mark.parametrize('home', ['"USER_ID":"123"',
                                  '"USER_ID":"123" "DTSGInitialData",[],{"token":""} "LSD",[],{"token":"lsd"} '
                                  '"__spin_r":1',
                                  '"USER_ID":"123" "DTSGInitialData",[],{"token":"bad\\qsecret"} '
                                  '"LSD",[],{"token":"lsd"} "__spin_r":1'])
def test_missing_or_invalid_session_tokens_are_a_safe_query_error(tmp_path, home):
    result = Account(tmp_path).run('feed', responses=[envelope(home, url='https://www.facebook.com/')])
    assert result.code == 6 and 'secret' not in result.stdout
    assert result.snippets == ['tokens']


def test_budget_counts_setup_and_retries_and_stops_reading_at_the_limit(tmp_path):
    # Without --limit the read budget is 25: home, 22 pages, a rejected request and its retry, then no more.
    pages = [feed_page(['p%d' % i], 'c%d' % i) for i in range(22)]
    temporary = graphql({'errors': [{'code': 1357054}]})
    result = Account(tmp_path).run('feed', '--json', responses=[login(), *pages, temporary, feed_page(['p22'], 'c22'),
                                                                feed_page(['never'])])
    assert result.code == 8, result.stdout
    assert result.data['stop_reason'] == 'budget' and result.data['ok'] is False
    assert result.ids == ['p%d' % i for i in range(23)]
    assert result.data['request_count'] == 25 and len(result.calls) == 25 and result.left == 1


def test_budget_exhausted_on_a_rejected_request_leaves_no_retry(tmp_path):
    # The 25th request is rejected with 1357054; its retry would be the 26th, so it is never sent.
    pages = [feed_page(['p%d' % i], 'c%d' % i) for i in range(23)]
    temporary = graphql({'errors': [{'code': 1357054}]})
    result = Account(tmp_path).run('feed', '--json', responses=[login(), *pages, temporary, feed_page(['retry'])])
    assert result.code == 8, result.stdout
    assert result.data['stop_reason'] == 'budget'
    assert len(result.calls) == 25 and result.left == 1


def test_budget_stop_keeps_the_uncommitted_cursor_for_the_next_invocation(tmp_path):
    from tests.facebook.helpers import more_args
    account = Account(tmp_path)
    pages = [feed_page(['p%d' % i], 'c%d' % i) for i in range(24)]
    first = account.run('feed', '--json', responses=[login(), *pages])
    assert first.code == 8 and first.data['stop_reason'] == 'budget'
    resumed = account.run(*more_args(first.data['next']), responses=[login(), feed_page(['p24'])])
    assert resumed.code == 0
    assert resumed.graphql()['variables']['cursor'] == 'c23'
    assert resumed.ids == ['p24']


def test_pacing_and_blocking_are_shared_between_concurrent_cli_processes(tmp_path):
    def launch(queue, log):
        environment = {**os.environ, 'FACEBOOK_ASIDE_BIN': str(FAKE_ASIDE), 'FAKE_ASIDE_RESPONSES': str(queue),
                       'FAKE_ASIDE_LOG': str(log), 'FACEBOOK_HOME': str(tmp_path / 'state'),
                       'PYTHONPATH': str(PROCESS_DOUBLES)}
        environment.pop('FAKE_NO_SLEEP', None)
        return subprocess.Popen([sys.executable, str(CLI), 'doctor'], env=environment,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    queue, log = tmp_path / 'queue.json', tmp_path / 'calls.jsonl'
    queue.write_text(json.dumps([login(), login()]))
    for process in [launch(queue, log), launch(queue, log)]:
        process.communicate(timeout=30)
        assert process.returncode == 0
    times = sorted(json.loads(line)['time'] for line in log.read_text().splitlines())
    assert len(times) == 2 and times[1] - times[0] >= 1.0
    log.unlink()
    queue.write_text(json.dumps([graphql(body='limited', status=429)]))
    processes = [launch(queue, log), launch(queue, log)]
    for process in processes:
        process.communicate(timeout=30)
        assert process.returncode == 5
    assert len(log.read_text().splitlines()) == 1
