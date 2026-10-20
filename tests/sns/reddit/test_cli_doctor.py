"""doctor through the real cli with the fake Aside: the Aside account, login, account protection, and the verified
unblock."""
import json
import time

from tests.sns.reddit.scene import VIEWER
from tests.sns.reddit.shapes import CHALLENGE


def doctor(reddit, *args, env=None):
    code, out, err = reddit.run('reddit', 'doctor', *args, env=env)
    return code, json.loads(out), err


def protection(data_dir, account='u0'):
    path = data_dir / 'reddit' / account / 'protection'
    path.mkdir(parents=True, exist_ok=True)
    return path


def challenged(data_dir, account='u0', viewer=None):
    path = protection(data_dir, account)
    (path / 'blocks.json').write_text(json.dumps({'person': {'reason': 'challenge', 'at': time.time(),
                                                             'viewer': viewer}, 'hold': None}))
    return path


def test_doctor_reports_aside_login_and_protection(reddit, data_dir):
    reddit.me()
    code, envelope, _ = doctor(reddit)
    assert code == 0 and envelope['ok'] is True and envelope['stop_reason'] == 'ready'
    check, = envelope['results']
    assert check['aside_account'] == 'u0' and check['reddit_account'] == VIEWER == check['viewer']
    assert check['login'] == 'ready' and check['blocked'] is False
    assert check['limits']['general']['status'] == 'known'
    assert check['requests_last_hour'] == 1 and check['data_dir'] == str(data_dir) and 'snapshot_bytes' in check
    assert envelope['request_count'] == 1
    assert [c['account'] for c in reddit.calls() if c['op'] == 'reddit.fetch'] == ['u0'], 'every request names the account'


def test_a_saved_challenge_stops_doctor_before_any_request(reddit, data_dir):
    challenged(data_dir)
    code, envelope, _ = doctor(reddit)
    assert code == 5 and envelope['error'] == 'blocked' and 'challenge' in envelope['message']
    assert 'doctor --unblock' in envelope['fix'] and reddit.fetches() == []


def test_unblock_lifts_a_challenge_after_a_clean_check(reddit, data_dir):
    challenged(data_dir, viewer=VIEWER)
    reddit.me()
    code, envelope, _ = doctor(reddit, '--unblock')
    assert code == 0 and envelope['results'][0]['blocked'] is False and envelope['results'][0]['unblocked'] is True
    assert reddit.paths() == ['/api/me.json']
    assert json.loads((protection(data_dir) / 'blocks.json').read_text())['person'] is None


def test_unblock_keeps_the_block_when_the_check_is_still_challenged(reddit, data_dir):
    path = challenged(data_dir)
    reddit.respond(CHALLENGE, path='/api/me.json')
    code, envelope, _ = doctor(reddit, '--unblock')
    assert code == 5 and json.loads((path / 'blocks.json').read_text())['person']['reason'] == 'challenge'


def test_unblock_keeps_the_block_when_logged_out(reddit, data_dir):
    path = challenged(data_dir)
    reddit.json('/api/me.json', {})
    code, envelope, _ = doctor(reddit, '--unblock')
    assert code == 4 and json.loads((path / 'blocks.json').read_text())['person'] is not None


def test_unblock_keeps_the_block_when_the_browser_is_another_account(reddit, data_dir):
    path = challenged(data_dir, viewer='the_blocked_account')
    reddit.me()
    code, envelope, _ = doctor(reddit, '--unblock')
    assert code == 5 and envelope['verification_reason'] == 'account_mismatch'
    assert json.loads((path / 'blocks.json').read_text())['person'] is not None


def test_unblock_keeps_a_wiki_rate_limit(reddit, data_dir):
    path = challenged(data_dir)
    (path / 'scopes.json').write_text(json.dumps({'wiki': {'status': 'known', 'limit': 600, 'remaining': 0,
                                                           'reset_at': time.time() + 300,
                                                           'blocked_until': time.time() + 300}}))
    reddit.me()
    code, envelope, _ = doctor(reddit, '--unblock')
    wiki = envelope['results'][0]['limits']['wiki']
    assert code == 0 and wiki['blocked_until'] > time.time() + 200


def test_logged_out_is_exit_4(reddit, data_dir):
    reddit.json('/api/me.json', {})
    code, envelope, _ = doctor(reddit)
    assert code == 4 and envelope['error'] == 'login'


def test_an_ambiguous_aside_account_is_exit_3_with_no_request(reddit, data_dir):
    reddit.account_status('* u0  a@example.com\n* u1  b@example.com\n')
    code, envelope, _ = doctor(reddit)
    assert code == 3 and 'SNS_ASIDE_ACCOUNT' in envelope['fix'] and reddit.fetches() == []


def test_the_default_account_and_its_id_share_one_protection_state(reddit, data_dir):
    challenged(data_dir, 'u1')
    reddit.account_status('  u0  a@example.com\n* u1  b@example.com  signed in\n')
    code, _, _ = doctor(reddit)
    assert code == 5
    code, _, _ = doctor(reddit, env={'SNS_ASIDE_ACCOUNT': 'u1'})
    assert code == 5 and reddit.fetches() == []
    reddit.me()
    code, envelope, _ = doctor(reddit, env={'SNS_ASIDE_ACCOUNT': 'u0'})
    assert code == 0 and envelope['results'][0]['aside_account'] == 'u0'
