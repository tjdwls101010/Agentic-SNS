"""doctor through the real cli with the fake Aside: Aside, the logged-in account, account protection, and the verified
unblock. A network block is a person block (doctor --unblock lifts it after a clean check); a 429 is a hold that passes
at its time and that unblock never lifts."""
import json
import time

import pytest

from tests.sns.naver_blog.scene import ACCOUNT, M, VIEWER, fixture

SECRETS = ('secret_login_id', '7777', 'bk-secret')


def doctor(naver, *args, env=None):
    code, out, err = naver.run('naver-blog', 'doctor', *args, env=env)
    return code, json.loads(out), err


def protection(data_dir, account=ACCOUNT):
    path = data_dir / 'naver_blog' / account / 'protection'
    path.mkdir(parents=True, exist_ok=True)
    return path


def network_blocked(data_dir, viewer=None):
    path = protection(data_dir)
    (path / 'blocks.json').write_text(json.dumps({'person': {'reason': 'network_blocked', 'at': time.time(),
                                                             'viewer': viewer}, 'hold': None}))
    return path


def held(data_dir, seconds=1200):
    path = protection(data_dir)
    now = time.time()
    (path / 'blocks.json').write_text(json.dumps({'person': None, 'hold': {'reason': 'rate_limit', 'at': now,
                                                                           'until': now + seconds}}))
    return path


def test_doctor_reports_the_account_and_protection(naver, data_dir):
    naver.logged_in()
    code, envelope, _ = doctor(naver)
    assert code == 0 and envelope['ok'] is True and envelope['stop_reason'] == 'ready'
    check, = envelope['results']
    assert check['aside_account'] == ACCOUNT and check['viewer'] == VIEWER and check['login'] == 'ready'
    assert check['blocked'] is False and check['requests_last_hour'] == 1 and check['limits'] == {}
    assert naver.paths() == ['/api/current-user'] and envelope['request_count'] == 1
    text = json.dumps(envelope, ensure_ascii=False)
    assert not [secret for secret in SECRETS if secret in text]


def test_doctor_remembers_who_was_logged_in_as_a_hint_without_the_login_identifiers(naver, data_dir):
    naver.logged_in()
    doctor(naver)
    path = data_dir / 'naver_blog' / ACCOUNT / 'session' / 'viewer.json'
    saved = json.loads(path.read_text())
    assert saved['viewer'] == VIEWER and set(saved) == {'viewer', 'seen_at'}
    assert not [secret for secret in SECRETS if secret in path.read_text()]


def test_a_saved_block_stops_doctor_before_any_request(naver, data_dir):
    network_blocked(data_dir)
    code, envelope, _ = doctor(naver)
    assert code == 5 and envelope['error'] == 'blocked' and naver.fetches() == []
    assert 'doctor --unblock' in envelope['fix']


def test_logged_out_is_exit_4_and_leaves_no_hint(naver, data_dir):
    naver.hint()
    naver.logged_in(loggedIn=False)
    code, envelope, _ = doctor(naver)
    assert code == 4 and envelope['error'] == 'login'


def test_a_network_block_is_recorded_as_a_person_block_that_stops_the_next_command(naver, data_dir):
    naver.logged_in(networkBlocked=True)
    code, envelope, _ = doctor(naver)
    assert code == 5 and envelope['error'] == 'blocked'
    saved = json.loads((protection(data_dir) / 'blocks.json').read_text())
    assert saved['person']['reason'] == 'network_blocked' and saved['person']['viewer'] == VIEWER
    sent = len(naver.fetches())
    code, out, _ = naver.run('naver-blog', 'keywords')
    assert code == 5 and 'doctor --unblock' in json.loads(out)['fix'] and len(naver.fetches()) == sent


def test_unblock_lifts_a_network_block_after_a_clean_check(naver, data_dir):
    path = network_blocked(data_dir, viewer=VIEWER)
    naver.logged_in()
    code, envelope, _ = doctor(naver, '--unblock')
    assert code == 0 and envelope['results'][0]['unblocked'] is True and envelope['results'][0]['blocked'] is False
    assert naver.paths() == ['/api/current-user']
    assert json.loads((path / 'blocks.json').read_text())['person'] is None


def test_unblock_keeps_the_block_while_naver_still_reports_it(naver, data_dir):
    path = network_blocked(data_dir, viewer=VIEWER)
    naver.logged_in(networkBlocked=True)
    code, envelope, _ = doctor(naver, '--unblock')
    assert code == 5 and json.loads((path / 'blocks.json').read_text())['person']['reason'] == 'network_blocked'


def test_unblock_keeps_the_block_when_the_check_cannot_run(naver, data_dir):
    path = network_blocked(data_dir)
    naver.respond(M, '/api/current-user', __raw_stdout='', __exit=1)
    code, envelope, _ = doctor(naver, '--unblock')
    assert code == 3 and json.loads((path / 'blocks.json').read_text())['person'] is not None


def test_unblock_keeps_the_block_when_the_answer_names_no_account(naver, data_dir):
    path = network_blocked(data_dir)
    naver.respond(M, '/api/current-user', json={'isSuccess': True, 'result': {'loggedIn': True, 'networkBlocked': False}})
    code, envelope, _ = doctor(naver, '--unblock')
    assert code == 4 and json.loads((path / 'blocks.json').read_text())['person'] is not None


def test_unblock_keeps_the_block_when_the_browser_is_another_account(naver, data_dir):
    path = network_blocked(data_dir, viewer='the_blocked_account')
    naver.logged_in()
    code, envelope, _ = doctor(naver, '--unblock')
    assert code == 5 and envelope['verification_reason'] == 'account_mismatch'
    assert json.loads((path / 'blocks.json').read_text())['person'] is not None


def test_a_429_is_a_hold_for_the_policys_half_hour_and_the_next_command_waits_without_a_request(naver, data_dir):
    naver.respond(M, '/api/search/v1/post', status=429, body='')
    code, out, _ = naver.run('naver-blog', 'search', '카페', '--json')
    envelope = json.loads(out)
    assert code == 5 and envelope['error'] == 'blocked' and 1700 < envelope['limit']['reset'] - time.time() < 1815
    saved = json.loads((protection(data_dir) / 'blocks.json').read_text())
    assert saved['person'] is None and saved['hold']['reason'] == 'rate_limit'
    sent = len(naver.fetches())
    code, out, _ = naver.run('naver-blog', 'feed')
    assert code == 5 and len(naver.fetches()) == sent


def test_unblock_never_lifts_a_hold(naver, data_dir):
    path = held(data_dir)
    naver.logged_in()
    code, envelope, _ = doctor(naver, '--unblock')
    assert code == 5 and envelope['verification_reason'] == 'rate_limited' and naver.fetches() == []
    assert json.loads((path / 'blocks.json').read_text())['hold'] is not None


def test_a_hold_that_has_passed_lets_requests_go_on(naver, data_dir):
    path = protection(data_dir)
    (path / 'blocks.json').write_text(json.dumps({'person': None, 'hold': {'reason': 'rate_limit', 'at': time.time() - 3000,
                                                                          'until': time.time() - 1200}}))
    naver.logged_in()
    code, envelope, _ = doctor(naver)
    assert code == 0 and envelope['results'][0]['login'] == 'ready'


def test_many_recent_requests_do_not_stop_a_command(naver, data_dir):
    """The old skill's own 10-minute window of 120 (exit 10) is gone: only Naver's signals, the time limit and pacing
    stop a command."""
    (protection(data_dir) / 'requests.jsonl').write_text(
        json.dumps({'id': 'x', 'at': time.time() - 30, 'kind': 'query', 'n': 500, 'outcome': 'ok'}) + '\n')
    naver.logged_in()
    code, envelope, _ = doctor(naver)
    assert code == 0 and envelope['results'][0]['requests_last_hour'] >= 500


def test_unreadable_protection_state_fails_closed(naver, data_dir):
    (protection(data_dir) / 'blocks.json').write_text('not json')
    code, envelope, _ = doctor(naver)
    assert code == 5 and naver.fetches() == []


def test_aside_missing_is_exit_3(naver, data_dir):
    code, envelope, _ = doctor(naver, env={'SNS_ASIDE_BIN': str(data_dir / 'no-such-aside')})
    assert code == 3 and envelope['error'] == 'aside'


@pytest.mark.parametrize('case', [c for c in fixture('aside_output.json')['cases'] if 'error' in c],
                         ids=lambda c: c['name'])
def test_unreadable_aside_output_is_exit_3(naver, data_dir, case):
    naver.respond(M, '/api/current-user', __raw_stdout=case['stdout'] + case['stderr'], __exit=case['exit'])
    code, envelope, _ = doctor(naver)
    assert code == 3 and envelope['error'] == 'aside'


@pytest.mark.parametrize('answer', [{'status': '200'}, {'status': 42}, {'status': 200, 'body': None},
                                    {'status': 200, 'body_file': '/tmp/x'}, {'status': 200, 'location': 7},
                                    {'status': 200, 'content_type': 7}, {'status': 200, 'b64': 7}])
def test_an_envelope_the_skill_cannot_read_is_exit_3(naver, data_dir, answer):
    naver.respond(M, '/api/current-user', **{'body': '{}', **answer})
    code, envelope, _ = doctor(naver)
    assert code == 3 and envelope['error'] == 'aside'


def test_the_aside_account_comes_from_the_environment(naver, data_dir):
    naver.logged_in()
    doctor(naver, env={'SNS_ASIDE_ACCOUNT': 'u1'})
    naver.monkeypatch.delenv('SNS_ASIDE_ACCOUNT')
    naver.logged_in()
    doctor(naver)
    assert [call['account'] for call in naver.calls() if call['op'] == 'naver_blog.fetch'] == ['u1', 'u0']
    assert (data_dir / 'naver_blog' / 'u1').exists() and (data_dir / 'naver_blog' / 'u0').exists()


def test_an_ambiguous_aside_account_is_exit_3_with_no_request(naver, data_dir):
    naver.account_status('* u0  a@example.com\n* u1  b@example.com\n')
    code, envelope, _ = doctor(naver)
    assert code == 3 and 'SNS_ASIDE_ACCOUNT' in envelope['fix'] and naver.fetches() == []
