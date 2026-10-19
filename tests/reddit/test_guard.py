"""Account protection on a real filesystem (fixture limits.json): Reddit's buckets as their headers report them, the
probe of an unknown bucket, blocks, the verified unblock, reservations that survive a kill, and fail-closed state."""
import json
import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from conftest import SKILL, fixture
from reddit import guard
from reddit.errors import RedditError

SCENARIOS = {s['name']: s for s in fixture('limits.json')['scenarios']}
ACCOUNT = 'u0'


@pytest.fixture(autouse=True)
def no_wait(monkeypatch, data_dir):
    monkeypatch.setenv('REDDIT_ASIDE_BIN', '/nonexistent/stand-in')
    monkeypatch.setenv('REDDIT_TEST_NO_WAIT', '1')


def protection(data_dir, account=ACCOUNT):
    path = data_dir / 'protection' / account
    path.mkdir(parents=True, exist_ok=True)
    return path


def buckets(data_dir, account=ACCOUNT):
    return json.loads((protection(data_dir, account) / 'buckets.json').read_text())


def write_buckets(data_dir, value, account=ACCOUNT):
    (protection(data_dir, account) / 'buckets.json').write_text(json.dumps(value))


def known(remaining, used, resets_in):
    return {'status': 'known', 'remaining': remaining, 'used': used, 'reset_at': time.time() + resets_in}


def send(g, bucket='general', headers=None, metered=True):
    with g.request(bucket, metered=metered) as slot:
        slot.report(headers)
        slot.classify('ok')
    return slot


def H(used, remaining, reset):
    return {'used': used, 'remaining': remaining, 'reset': reset}


def test_valid_headers_update_the_bucket(data_dir):
    assert SCENARIOS['valid-headers-update-the-bucket']
    send(guard.Guard(ACCOUNT, 25), headers=H('4', '96.0', '300'))
    state = buckets(data_dir)['general']
    assert (state['status'], state['remaining'], state['used']) == ('known', 96, 4)
    assert 295 <= state['reset_at'] - time.time() <= 300


@pytest.mark.parametrize('headers', [H('51', None, '299'), H('51', '-1', '299'), H('x', '48', 'nan'),
                                     H('51', 'inf', '299'), H(True, '48', '299'), None])
def test_unusable_headers_keep_the_reservation(data_dir, headers):
    write_buckets(data_dir, {'general': known(50, 50, 300)})
    send(guard.Guard(ACCOUNT, 25), headers=headers)
    state = buckets(data_dir)['general']
    assert (state['remaining'], state['used']) == (49, 51)


def test_spent_bucket_is_not_sent_to_and_the_other_bucket_goes_on(data_dir):
    scenario = SCENARIOS['remaining-zero-stops-that-bucket']
    g = guard.Guard(ACCOUNT, 25)
    send(g, headers=H('100', '0', '120'))
    with pytest.raises(RedditError) as caught:
        send(g)
    assert caught.value.code == 8 and caught.value.reason == 'window_spent' == scenario['result']['stop_reason']
    assert 'resets in 12' in caught.value.message
    send(g, 'wiki', headers=H('1', '599', '120'))
    assert g.used == 2
    assert guard.status(protection(data_dir))['buckets']['general']['wait_seconds'] > 100


def test_a_passed_reset_makes_the_bucket_unknown_and_the_next_request_a_probe(data_dir):
    write_buckets(data_dir, {'general': {**known(0, 100, 0), 'reset_at': time.time() - 1}})
    with guard.Guard(ACCOUNT, 25).request('general') as slot:
        inside = buckets(data_dir)['general']
        slot.report(H('1', '99', '599'))
    assert inside['status'] == 'probe' and inside['pid'] == os.getpid()
    assert buckets(data_dir)['general']['remaining'] == 99


def test_slow_down_when_half_spent(data_dir):
    scenario = SCENARIOS['slow-down-when-half-spent']
    g = guard.Guard(ACCOUNT, 25)
    first, second = scenario['steps']
    send(g, headers=first['headers'])
    gap = json.loads((protection(data_dir) / 'pace.json').read_text())['next_allowed_at'] - time.time()
    assert first['next_gap_at_most'] >= gap > first['next_gap_at_least'] - 0.1
    assert 'slow_until' not in buckets(data_dir)['general']
    send(g, headers=second['headers'])
    gap = buckets(data_dir)['general']['slow_until'] - time.time()
    assert gap >= second['next_gap_at_least'] - 0.1 and g.slowest >= 9.9


def test_a_wait_longer_than_a_command_should_take_stops_instead(data_dir):
    (protection(data_dir) / 'pace.json').write_text(json.dumps({'next_allowed_at': time.time() + 90}))
    started = time.time()
    with pytest.raises(RedditError) as caught:
        send(guard.Guard(ACCOUNT, 25))
    assert caught.value.code == 8 and caught.value.reason == 'window_spent' and time.time() - started < 5


HOLD = textwrap.dedent('''
    import os, sys, time, signal
    from reddit import guard
    g = guard.Guard(sys.argv[1], 25)
    with g.request(sys.argv[2]) as slot:
        open(sys.argv[3], 'w').write('inside')
        if sys.argv[4] == 'kill':
            os.kill(os.getpid(), signal.SIGKILL)
        time.sleep(float(sys.argv[4]))
        slot.report({'used': '1', 'remaining': '99', 'reset': '300'})
''')


def hold(data_dir, tmp_path, action, bucket='general'):
    """Another process inside a request slot: it sleeps `action` seconds, or kills itself after the reservation."""
    flag = tmp_path / f'inside-{time.time()}'
    env = {**os.environ, 'PYTHONPATH': str(SKILL / 'scripts'), 'REDDIT_DATA_DIR': str(data_dir)}
    child = subprocess.Popen([sys.executable, '-c', HOLD, ACCOUNT, bucket, str(flag), action], env=env)
    deadline = time.time() + 20
    while not flag.exists() and child.poll() is None and time.time() < deadline:
        time.sleep(0.02)
    return child


def test_two_processes_on_an_unknown_bucket_make_one_probe(data_dir, tmp_path):
    first = hold(data_dir, tmp_path, '2')  # inside its probe, holding the lock until the answer
    started = time.time()
    with guard.Guard(ACCOUNT, 25).request('general') as slot:
        inside = buckets(data_dir)['general']
        slot.report(H('2', '98', '300'))
    assert time.time() - started >= 1.5, 'the second process waited for the probe to be answered'
    assert inside['status'] == 'known' and inside['remaining'] == 98, 'then sent as a reserved request, not a probe'
    first.wait(timeout=20)


def test_a_dead_probe_counts_as_sent_and_blocks_a_new_probe_for_a_while(data_dir):
    scenario = SCENARIOS['dead-probe-counted']
    dead = subprocess.Popen(['true'])
    dead.wait()
    write_buckets(data_dir, {'general': {'status': 'probe', 'pid': dead.pid, 'started_at': time.time() - 30}})
    with pytest.raises(RedditError) as caught:
        send(guard.Guard(ACCOUNT, 25))
    assert caught.value.reason == 'probe_pending' and 'counts as sent' in caught.value.message
    wait = guard.status(protection(data_dir))['buckets']['general']['wait_seconds']
    assert abs(wait - scenario['after']['general']['wait_seconds']) < 3
    write_buckets(data_dir, {'general': {'status': 'probe', 'pid': dead.pid, 'started_at': time.time() - 200}})
    send(guard.Guard(ACCOUNT, 25), headers=H('2', '98', '300'))


def test_a_probe_answered_without_headers_makes_the_bucket_unmetered(data_dir):
    g = guard.Guard(ACCOUNT, 25)
    send(g, headers=H(None, None, None))
    state = buckets(data_dir)['general']
    assert state['status'] == 'unmetered' and 595 <= state['until'] - time.time() <= 600
    with pytest.raises(RedditError) as caught:
        send(g)
    assert caught.value.code == 6 and caught.value.reason == 'unmetered'


def test_a_share_link_is_never_a_probe(data_dir):
    g = guard.Guard(ACCOUNT, 25)
    send(g, 'share', metered=False, headers=H(None, None, None))
    assert 'general' not in buckets(data_dir) and buckets(data_dir)['share'] == {'status': 'unknown'}
    send(g, headers=H('1', '99', '300'))  # the general bucket still gets its own probe
    assert buckets(data_dir)['general']['status'] == 'known' and g.used == 2
    log = [json.loads(line) for line in (protection(data_dir) / 'requests.jsonl').read_text().splitlines()]
    assert [entry['bucket'] for entry in log if entry['n'] == 1] == ['share', 'general']


def test_a_rate_limit_blocks_only_its_bucket(data_dir):
    g = guard.Guard(ACCOUNT, 25)
    with g.request('wiki') as slot:
        slot.report(H('600', '0', '200'))
        slot.rate_limit('200')
        slot.classify('rate_limited')
    with pytest.raises(RedditError) as caught:
        send(g, 'wiki')
    assert caught.value.code == 5 and caught.value.reason == 'rate_limit'
    send(g, 'general', headers=H('1', '99', '300'))
    log = [json.loads(line) for line in (protection(data_dir) / 'requests.jsonl').read_text().splitlines()]
    assert [entry['outcome'] for entry in log if entry['n'] == 0] == ['rate_limited', 'ok']
    assert sum(entry['n'] for entry in log) == 2


def test_a_rate_limit_without_reset_lasts_the_default(data_dir):
    g = guard.Guard(ACCOUNT, 25)
    with g.request('general') as slot:
        slot.report(H(None, None, None))
        slot.rate_limit(None)
    assert 595 <= buckets(data_dir)['general']['blocked_until'] - time.time() <= 600


def test_a_challenge_blocks_every_bucket(data_dir):
    g = guard.Guard(ACCOUNT, 25)
    with g.request('general') as slot:
        slot.report(H('3', '97', '300'))
        slot.challenge()
    for bucket in ('general', 'wiki'):
        with pytest.raises(RedditError) as caught:
            send(guard.Guard(ACCOUNT, 25), bucket)
        assert caught.value.code == 5 and caught.value.reason == 'challenge'
    assert guard.status(protection(data_dir))['blocked'] is True


def challenged_with_wiki_limit(data_dir):
    (protection(data_dir) / 'blocked.json').write_text(json.dumps({'reason': 'challenge', 'blocked_at': time.time(),
                                                                   'expires_at': None}))
    write_buckets(data_dir, {'wiki': {**known(0, 600, 300), 'blocked_until': time.time() + 300}})


def test_unblock_lifts_only_a_verified_challenge(data_dir):
    challenged_with_wiki_limit(data_dir)
    g = guard.Guard(ACCOUNT, guard.MAX_BUDGET)
    with g.verify_unblock() as check:
        with g.request('general') as inner:  # the client's request runs inside the check
            assert inner is check
            inner.report(H('5', '95', '300'))
        check.clear()
    assert guard.status(protection(data_dir))['blocked'] is False
    with pytest.raises(RedditError) as caught:
        send(guard.Guard(ACCOUNT, 25), 'wiki')
    assert caught.value.reason == 'rate_limit', 'a general check proves nothing about the wiki bucket'


def test_a_failed_check_keeps_the_block(data_dir):
    challenged_with_wiki_limit(data_dir)
    g = guard.Guard(ACCOUNT, guard.MAX_BUDGET)
    with pytest.raises(RedditError):
        with g.verify_unblock() as check:
            check.report(H('5', '95', '300'))
            raise RedditError(5, 'still a challenge', 'x')
    assert guard.status(protection(data_dir))['blocked'] is True
    with pytest.raises(RedditError) as caught:
        with g.verify_unblock():
            pass
    assert 'already made' in caught.value.message


UNBLOCK_KILLED = textwrap.dedent('''
    import os, signal, sys
    from reddit import guard
    g = guard.Guard(sys.argv[1], guard.MAX_BUDGET)
    with g.verify_unblock() as check:
        os.kill(os.getpid(), signal.SIGKILL)
''')


def test_a_killed_check_keeps_the_block(data_dir):
    challenged_with_wiki_limit(data_dir)
    env = {**os.environ, 'PYTHONPATH': str(SKILL / 'scripts'), 'REDDIT_DATA_DIR': str(data_dir)}
    done = subprocess.run([sys.executable, '-c', UNBLOCK_KILLED, ACCOUNT], env=env)
    assert done.returncode == -signal.SIGKILL
    assert guard.status(protection(data_dir))['blocked'] is True


def test_a_reservation_survives_a_kill_after_sending(data_dir, tmp_path):
    write_buckets(data_dir, {'general': known(50, 50, 300)})
    child = hold(data_dir, tmp_path, 'kill')
    assert child.wait(timeout=20) == -signal.SIGKILL
    state = buckets(data_dir)['general']
    assert (state['remaining'], state['used']) == (49, 51)
    assert json.loads((protection(data_dir) / 'pace.json').read_text())['next_allowed_at'] > time.time()


@pytest.mark.parametrize('name, content', [
    ('buckets.json', '{"general": {"status": "maybe"}}'),
    ('buckets.json', '{"general": {"status": "known", "remaining": "lots"}}'),
    ('buckets.json', '['),
    ('blocked.json', '{"reason": "vibes", "blocked_at": 1}'),
    ('pace.json', '{"next_allowed_at": "soon"}'),
])
def test_unreadable_state_fails_closed(data_dir, name, content):
    (protection(data_dir) / name).write_text(content)
    with pytest.raises(RedditError) as caught:
        send(guard.Guard(ACCOUNT, 25))
    assert caught.value.code == 5
    if name != 'pace.json':
        assert guard.status(protection(data_dir))['blocked'] is True


def test_the_budget_is_per_command(data_dir):
    g = guard.Guard(ACCOUNT, 2)
    send(g, headers=H('1', '99', '300'))
    send(g, headers=H('2', '98', '300'))
    with pytest.raises(RedditError) as caught:
        send(g, headers=H('3', '97', '300'))
    assert caught.value.reason == 'budget' and g.used == 2
    for bad in (0, 101, '25', True):
        with pytest.raises(RedditError):
            guard.Guard(ACCOUNT, bad)


def test_accounts_do_not_share_state(data_dir):
    with guard.Guard('u0', 25).request('general') as slot:
        slot.report(H('100', '0', '100'))
        slot.rate_limit('100')
    with pytest.raises(RedditError):
        send(guard.Guard('u0', 25))
    send(guard.Guard('u1', 25), headers=H('1', '99', '300'))


LOCK_HOLDER = textwrap.dedent('''
    import fcntl, sys, time
    lock = open(sys.argv[1], 'a'); fcntl.flock(lock, fcntl.LOCK_EX)
    open(sys.argv[2], 'w').write('locked'); time.sleep(3)
''')


def test_status_reads_without_the_lock(data_dir, tmp_path):
    write_buckets(data_dir, {'general': known(10, 90, 300)})
    flag = tmp_path / 'locked'
    child = subprocess.Popen([sys.executable, '-c', LOCK_HOLDER, str(protection(data_dir) / 'lock'), str(flag)])
    while not flag.exists():
        time.sleep(0.02)
    started = time.time()
    state = guard.status(protection(data_dir))
    assert time.time() - started < 1 and state['buckets']['general']['remaining'] == 10
    child.wait(timeout=10)


def test_recent_counts_the_log_of_every_invocation(data_dir):
    send(guard.Guard(ACCOUNT, 25), headers=H('1', '99', '300'))
    send(guard.Guard(ACCOUNT, 25), headers=H('2', '98', '300'))
    assert guard.Guard(ACCOUNT, 25).recent() == {'last_hour': 2, 'last_day': 2}


# --- reproductions of the P3 shared-contract review (Codex, round 1)


def test_a_dead_probes_rate_limit_outlives_the_probe(data_dir):
    dead = subprocess.Popen(['true'])
    dead.wait()
    write_buckets(data_dir, {'general': {'status': 'probe', 'pid': dead.pid, 'started_at': time.time() - 126,
                                         'blocked_until': time.time() + 170}})
    with pytest.raises(RedditError) as caught:
        send(guard.Guard(ACCOUNT, 25))
    assert caught.value.reason == 'rate_limit'
    write_buckets(data_dir, {'general': {'status': 'unmetered', 'until': time.time() - 1,
                                         'blocked_until': time.time() + 170}})
    with pytest.raises(RedditError) as caught:
        send(guard.Guard(ACCOUNT, 25))
    assert caught.value.reason == 'rate_limit'


def test_a_share_link_429_is_not_sent_again(data_dir):
    g = guard.Guard(ACCOUNT, 25)
    with g.request('share', metered=False) as slot:
        slot.report(None)
        slot.rate_limit('300')
    with pytest.raises(RedditError) as caught:
        send(g, 'share', metered=False)
    assert caught.value.reason == 'rate_limit'
    send(g, 'general', headers=H('1', '99', '300'))


def test_the_unblock_check_is_one_general_request_within_the_budget(data_dir):
    challenged_with_wiki_limit(data_dir)
    g = guard.Guard(ACCOUNT, 1)
    send_failed = False
    with g.verify_unblock() as check:
        with g.request('general') as inner:
            inner.report(H('5', '95', '300'))
        for bucket in ('general', 'wiki'):
            try:
                with g.request(bucket):
                    pass
            except RedditError:
                send_failed = True
        check.clear()
    assert send_failed and g.used == 1
    spent = guard.Guard(ACCOUNT, 1)
    send(spent, headers=H('6', '94', '300'))
    (protection(data_dir) / 'blocked.json').write_text(json.dumps({'reason': 'challenge', 'blocked_at': time.time(),
                                                                   'expires_at': None}))
    with pytest.raises(RedditError) as caught:
        with spent.verify_unblock():
            pass
    assert caught.value.reason == 'budget'


@pytest.mark.parametrize('bucket', [{'status': 'known'}, {'status': 'known', 'remaining': 5, 'used': 5},
                                    {'status': 'probe'}, {'status': 'unmetered'}, {'status': 'known', 'remaining': -1,
                                                                                  'used': 1, 'reset_at': 5.0}])
def test_a_bucket_missing_what_its_status_needs_fails_closed(data_dir, bucket):
    write_buckets(data_dir, {'general': bucket})
    with pytest.raises(RedditError) as caught:
        send(guard.Guard(ACCOUNT, 25))
    assert caught.value.code == 5


def test_a_low_general_bucket_does_not_slow_the_wiki(data_dir):
    g = guard.Guard(ACCOUNT, 25)
    send(g, headers=H('99', '1', '300'))
    send(g, 'wiki', headers=H('1', '599', '300'))
    with pytest.raises(RedditError) as caught:
        send(g)
    assert caught.value.reason == 'window_spent'


def test_slow_down_waits_add_up_to_a_limit_per_command(data_dir, monkeypatch):
    slept = []
    monkeypatch.delenv('REDDIT_TEST_NO_WAIT')
    monkeypatch.setattr(guard.time, 'sleep', lambda seconds: slept.append(seconds))
    write_buckets(data_dir, {'general': {**known(10, 90, 290), 'slow_until': time.time() + 20}})
    g = guard.Guard(ACCOUNT, 25)
    send(g, headers=H('91', '9', '200'))
    write_buckets(data_dir, {'general': {**known(9, 91, 200), 'slow_until': time.time() + 20}})
    with pytest.raises(RedditError) as caught:
        send(g)
    assert caught.value.reason == 'window_spent' and sum(s for s in slept if s > 2.5) <= guard.MAX_WAIT_SECONDS


KILL_SHARE = textwrap.dedent('''
    import os, signal, sys
    from reddit import guard
    with guard.Guard(sys.argv[1], 25).request('share', metered=False) as slot:
        os.kill(os.getpid(), signal.SIGKILL)
''')


def test_a_request_killed_after_sending_is_still_logged(data_dir):
    env = {**os.environ, 'PYTHONPATH': str(SKILL / 'scripts'), 'REDDIT_DATA_DIR': str(data_dir)}
    assert subprocess.run([sys.executable, '-c', KILL_SHARE, ACCOUNT], env=env).returncode == -signal.SIGKILL
    assert guard.Guard(ACCOUNT, 25).recent() == {'last_hour': 1, 'last_day': 1}
