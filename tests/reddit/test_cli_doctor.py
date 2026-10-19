"""doctor through the real cli.py with the fake Aside: the Aside account, login, account protection, and the verified
unblock."""
import json
import time

from conftest import VIEWER, run_cli

CHALLENGE = {'status': 403, 'body': '<html><script src="/js_challenge.js"></script></html>'}


def doctor(reddit, *args, env=None):
    code, out, err = run_cli(reddit, 'doctor', *args, env=env)
    return code, json.loads(out), err


def challenged(data_dir, account='u0'):
    path = data_dir / 'protection' / account
    path.mkdir(parents=True, exist_ok=True)
    (path / 'blocked.json').write_text(json.dumps({'reason': 'challenge', 'blocked_at': time.time(), 'expires_at': None}))
    return path


def test_doctor_reports_aside_login_and_protection(reddit, data_dir):
    reddit.me()
    code, envelope, _ = doctor(reddit)
    assert code == 0 and envelope['ok'] is True and envelope['stop_reason'] == 'ready'
    check, = envelope['results']
    assert check['aside_account'] == 'u0' and check['reddit_account'] == VIEWER and check['login'] == 'ready'
    assert check['blocked'] is False and check['buckets']['general']['status'] == 'known'
    assert check['requests_last_hour'] == 1 and check['data_dir'] == str(data_dir)
    assert envelope['request_count'] == 1
    assert [c['account'] for c in reddit.calls() if c['op'] == 'fetch'] == ['u0'], 'every request names the account'


def test_a_saved_challenge_stops_doctor_before_any_request(reddit, data_dir):
    challenged(data_dir)
    code, envelope, _ = doctor(reddit)
    assert code == 5 and envelope['error'] == 'blocked' and envelope['reason'] == 'challenge'
    assert 'doctor --unblock' in envelope['fix'] and reddit.fetches() == []


def test_unblock_lifts_a_challenge_after_a_clean_check(reddit, data_dir):
    challenged(data_dir)
    reddit.me()
    code, envelope, _ = doctor(reddit, '--unblock')
    assert code == 0 and envelope['results'][0]['blocked'] is False and envelope['results'][0]['unblocked'] is True
    assert reddit.paths() == ['/api/me.json']


def test_unblock_keeps_the_block_when_the_check_is_still_challenged(reddit, data_dir):
    path = challenged(data_dir)
    reddit.respond(CHALLENGE, path='/api/me.json')
    code, envelope, _ = doctor(reddit, '--unblock')
    assert code == 5 and (path / 'blocked.json').exists()


def test_unblock_keeps_the_block_when_logged_out(reddit, data_dir):
    path = challenged(data_dir)
    reddit.json('/api/me.json', {})
    code, envelope, _ = doctor(reddit, '--unblock')
    assert code == 4 and (path / 'blocked.json').exists()


def test_unblock_keeps_a_wiki_rate_limit(reddit, data_dir):
    path = challenged(data_dir)
    (path / 'buckets.json').write_text(json.dumps({'wiki': {'status': 'known', 'remaining': 0, 'used': 600,
                                                            'reset_at': time.time() + 300,
                                                            'blocked_until': time.time() + 300}}))
    reddit.me()
    code, envelope, _ = doctor(reddit, '--unblock')
    assert code == 0 and envelope['results'][0]['buckets']['wiki']['rate_limited_for'] > 200


def test_logged_out_is_exit_4(reddit, data_dir):
    reddit.json('/api/me.json', {})
    code, envelope, _ = doctor(reddit)
    assert code == 4 and envelope['error'] == 'login'


def test_an_ambiguous_aside_account_is_exit_3_with_no_request(reddit, data_dir):
    reddit.account_status('* u0  a@example.com\n* u1  b@example.com\n')
    code, envelope, _ = doctor(reddit)
    assert code == 3 and 'REDDIT_ASIDE_ACCOUNT' in envelope['fix'] and reddit.fetches() == []


def test_the_default_account_and_its_id_share_one_protection_state(reddit, data_dir):
    challenged(data_dir, 'u1')
    reddit.account_status('  u0  a@example.com\n* u1  b@example.com  signed in\n')
    code, _, _ = doctor(reddit)
    assert code == 5
    code, _, _ = doctor(reddit, env={'REDDIT_ASIDE_ACCOUNT': 'u1'})
    assert code == 5 and reddit.fetches() == []
    reddit.me()
    code, envelope, _ = doctor(reddit, env={'REDDIT_ASIDE_ACCOUNT': 'u0'})
    assert code == 0 and envelope['results'][0]['aside_account'] == 'u0'


def test_doctor_help_says_what_it_costs_and_returns(reddit):
    code, out, _ = run_cli(reddit, 'doctor', '--help')
    assert code == 0
    for words in ('--unblock', 'requests: 1', 'exit codes', 'REDDIT_ASIDE_ACCOUNT'):
        assert words in out
