"""Account protection (sns.protection): the invariants every platform's requests rely on.

① a request is reserved (pacing, the scope's remaining or probe owner, a log line) before it is sent;
② the answer's outcome and header facts are recorded after, and a lost answer stays "sent";
③ an unknown scope gets one probe at a time, a dead owner's probe is reclaimed after the longest Aside call;
④ strength never weakens: person and hold are separate slots that never overwrite each other, a stop's time is never
  shortened, a headerless or successful answer never clears a stop;
⑤ unblock verification clears only the person block it read when it started.
"""
import json
import os
import subprocess
import sys

import pytest

from sns import protection
from sns.clock import Deadline
from sns.errors import SnsError
from sns.limits import Fact
from tests.sns.support.clocks import FakeClock
from tests.sns.support.policies import POLICIES

TITLES = {'x': ('X', 'x.com'), 'reddit': ('Reddit', 'reddit.com'), 'threads': ('Threads', 'threads.com'),
          'facebook': ('Facebook', 'facebook.com'), 'naver_blog': ('Naver Blog', 'blog.naver.com')}


@pytest.fixture
def clock():
    return FakeClock()


def guard(platform, clock, seconds=100, account='u0'):
    title, site = TITLES[platform]
    return protection.open(platform, account, POLICIES[platform], Deadline(seconds, clock), title=title, site=site)


def files(data_dir, platform='threads', account='u0'):
    return data_dir / platform / account / 'protection'


def log_lines(data_dir, platform='threads'):
    path = files(data_dir, platform) / 'requests.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


# ① reserve before sending ---------------------------------------------------------------------------------------

@pytest.mark.parametrize('platform', sorted(POLICIES))
def test_a_request_is_paced_counted_and_logged_before_it_is_sent(platform, data_dir, clock):
    g = guard(platform, clock)
    scope = {'x': 'UserTweets', 'reddit': 'general'}.get(platform)
    with pytest.raises(RuntimeError):
        with g.request(scope=scope) as slot:
            lines = log_lines(data_dir, platform)
            assert [(line['n'], line['outcome']) for line in lines] == [(1, 'sent')]
            pace = json.loads((files(data_dir, platform) / 'pace.json').read_text())['next_allowed_at']
            low, high = POLICIES[platform].pace
            assert clock.now + low <= pace <= clock.now + high
            raise RuntimeError('the process dies with the request in flight')
    assert g.count == 1
    assert [line['outcome'] for line in log_lines(data_dir, platform)] == ['sent']  # a lost answer stays sent


def test_the_next_request_waits_out_the_pacing_gap(data_dir, clock):
    g = guard('naver_blog', clock)
    with g.request():
        pass
    with g.request():
        pass
    assert clock.slept and 0.5 <= clock.slept[0] <= 0.8 and g.count == 2


def test_a_known_scope_has_its_remaining_reserved_before_sending(data_dir, clock):
    g = guard('reddit', clock)
    with g.request(scope='general') as slot:
        slot.fact('general', Fact(limit=100, remaining=40, reset_at=clock.now + 300))
    with g.request(scope='general'):
        scopes = json.loads((files(data_dir, 'reddit') / 'scopes.json').read_text())
        assert scopes['general']['remaining'] == 39


def test_setup_requests_are_counted_apart_and_charge_and_cancel_adjust(data_dir, clock):
    g = guard('threads', clock)
    with g.request(setup=True, reserve=1) as slot:
        slot.charge(30)
    with g.request() as slot:
        slot.cancel()
    assert (g.count, g.setup) == (30, 30)


def test_the_answer_outcome_is_logged_against_the_sent_line(data_dir, clock):
    g = guard('threads', clock)
    with g.request() as slot:
        slot.classify('ok')
    lines = log_lines(data_dir)
    assert [line['outcome'] for line in lines] == ['sent', 'ok'] and lines[0]['id'] == lines[1]['id']
    assert lines[1]['n'] == 0


def test_a_damaged_log_never_stops_a_request(data_dir, clock):
    g = guard('threads', clock)
    with g.request():
        pass
    with open(files(data_dir) / 'requests.jsonl', 'a') as stream:
        stream.write('not json\n')
    with g.request():
        pass
    assert g.recent()['last_day'] == 2


# person blocks and holds ---------------------------------------------------------------------------------------

@pytest.mark.parametrize('platform', sorted(POLICIES))
def test_a_person_block_stops_every_later_invocation(platform, data_dir, clock):
    reason = POLICIES[platform].person[0]
    g = guard(platform, clock)
    with g.request() as slot:
        slot.block(reason, viewer='42')
    with pytest.raises(SnsError) as caught:
        guard(platform, clock).check()
    assert caught.value.kind == 'blocked' and caught.value.reason == reason
    assert 'doctor --unblock' in caught.value.fix
    clock.advance(10 * 86400)
    with pytest.raises(SnsError):
        guard(platform, clock).check()  # only a verified unblock lifts it


def test_a_reason_outside_the_platforms_person_reasons_is_a_programming_error(data_dir, clock):
    g = guard('threads', clock)
    with g.request() as slot:
        with pytest.raises(ValueError):
            slot.block('challenge')


@pytest.mark.parametrize('platform', ['threads', 'facebook', 'naver_blog'])
def test_an_account_hold_passes_by_itself_at_its_time(platform, data_dir, clock):
    g = guard(platform, clock)
    with g.request() as slot:
        slot.hold()  # a 429 without a reset: the platform's default
    with pytest.raises(SnsError) as caught:
        guard(platform, clock).check()
    error = caught.value
    assert error.kind == 'blocked' and error.reason == 'rate_limited'
    assert error.details['until'] == pytest.approx(clock.now + POLICIES[platform].hold_seconds, abs=3)
    clock.advance(POLICIES[platform].hold_seconds + 5)
    later = guard(platform, clock)
    later.check()
    with later.request():
        pass


def test_a_hold_with_the_platforms_reset_uses_that_time(data_dir, clock):
    g = guard('threads', clock)
    with g.request() as slot:
        slot.hold(until=clock.now + 120)
    with pytest.raises(SnsError) as caught:
        guard('threads', clock).check()
    assert caught.value.details['until'] == clock.now + 120


def test_person_and_hold_never_overwrite_each_other_and_times_never_shorten(data_dir, clock):
    g = guard('threads', clock)
    with g.request() as slot:
        slot.hold(until=clock.now + 1000)
        slot.block('checkpoint')                 # a person block beside a hold: both kept
        slot.hold(until=clock.now + 10)          # a later, shorter hold keeps the longer one
    snapshot = guard('threads', clock).snapshot()
    assert snapshot['person']['reason'] == 'checkpoint'
    assert snapshot['hold']['until'] == pytest.approx(clock.now + 1000, abs=3)


def test_an_unreadable_state_file_refuses_every_request(data_dir, clock):
    guard('threads', clock).check()
    (files(data_dir) / 'blocks.json').write_text('{broken')
    with pytest.raises(SnsError) as caught:
        guard('threads', clock).check()
    assert caught.value.kind == 'blocked' and caught.value.reason == 'unreadable'
    (files(data_dir) / 'blocks.json').write_text('{"person": {"reason": "not a reason", "at": 1}, "hold": null}')
    with pytest.raises(SnsError):
        guard('threads', clock).check()


# server-announced scopes ----------------------------------------------------------------------------------------

def test_a_spent_scope_stops_that_scope_only_until_its_reset(data_dir, clock):
    g = guard('x', clock)
    with g.request(scope='SearchTimeline') as slot:
        slot.fact('SearchTimeline', Fact(limit=50, remaining=0, reset_at=clock.now + 600))
    with pytest.raises(SnsError) as caught:
        with g.request(scope='SearchTimeline'):
            pass
    error = caught.value
    assert error.kind == 'scope_limit' and error.reason == 'rate_limited'
    assert error.details['scope'] == 'SearchTimeline' and error.details['reset'] == clock.now + 600
    with g.request(scope='UserTweets'):
        pass
    clock.advance(601)
    with guard('x', clock).request(scope='SearchTimeline'):  # a later invocation
        pass


def test_a_scope_429_stops_the_scope_for_the_default_when_no_reset_is_given(data_dir, clock):
    g = guard('reddit', clock)
    with g.request(scope='wiki') as slot:
        slot.hold(scope='wiki')
    with pytest.raises(SnsError) as caught:
        with g.request(scope='wiki'):
            pass
    assert caught.value.kind == 'scope_limit' and caught.value.details['reset'] == pytest.approx(clock.now + 600, abs=3)
    guard('reddit', clock).check()  # not an account block


def test_a_headerless_or_successful_answer_never_clears_a_scope_stop(data_dir, clock):
    g = guard('reddit', clock)
    with g.request(scope='general') as slot:
        slot.hold(scope='general', until=clock.now + 300)
    clock.advance(1)
    with pytest.raises(SnsError):
        with g.request(scope='general'):
            pass
    snapshot = g.snapshot()
    assert snapshot['scopes']['general']['blocked_until'] == pytest.approx(clock.now - 1 + 300)


def test_a_fact_after_a_stop_does_not_shorten_it(data_dir, clock):
    g = guard('x', clock)
    with g.request(scope='TweetDetail') as slot:
        slot.hold(scope='TweetDetail', until=clock.now + 900)
        slot.fact('TweetDetail', Fact(limit=300, remaining=200, reset_at=clock.now + 60))
    assert g.snapshot()['scopes']['TweetDetail']['blocked_until'] == pytest.approx(clock.now + 900)


def test_a_nearly_spent_scope_is_slowed_and_stops_when_the_wait_passes_the_deadline(data_dir, clock):
    g = guard('x', clock, seconds=100)
    with g.request(scope='UserTweets') as slot:
        slot.fact('UserTweets', Fact(limit=50, remaining=2, reset_at=clock.now + 400))  # under 20%: 200 s apart
    with pytest.raises(SnsError) as caught:
        with g.request(scope='UserTweets'):
            pass
    assert caught.value.kind == 'scope_limit' and caught.value.details.get('slowed')


def test_a_slowed_scope_waits_when_the_wait_fits(data_dir, clock):
    g = guard('reddit', clock, seconds=100)
    with g.request(scope='general') as slot:
        slot.fact('general', Fact(limit=100, remaining=10, reset_at=clock.now + 100))  # remaining <= used: 10 s apart
    with g.request(scope='general'):
        pass
    assert max(clock.slept) == pytest.approx(10, abs=0.1)


def test_pacing_that_would_pass_the_deadline_is_a_time_limit(data_dir, clock):
    g = guard('threads', clock, seconds=4)
    with g.request():
        pass
    with pytest.raises(SnsError) as caught:
        with g.request():
            pass
    assert caught.value.kind == 'failed' and caught.value.reason == 'time_limit'


def test_a_lock_held_past_the_deadline_is_a_time_limit(data_dir):
    directory = files(data_dir)
    directory.mkdir(parents=True)
    holder = subprocess.Popen([sys.executable, '-c', 'import fcntl,sys,time\n'
                               f'f=open({str(directory / "lock")!r},"a"); fcntl.flock(f, fcntl.LOCK_EX)\n'
                               'print("held", flush=True); time.sleep(30)'], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'held'
        g = protection.open('threads', 'u0', POLICIES['threads'], Deadline(0.3), title='Threads', site='threads.com')
        with pytest.raises(SnsError) as caught:
            with g.request():
                pass
        assert caught.value.reason == 'time_limit'
    finally:
        holder.kill()
        holder.wait()


# ③ probes ------------------------------------------------------------------------------------------------------

def dead_pid():
    process = subprocess.Popen([sys.executable, '-c', 'pass'])
    process.wait()
    return process.pid


def test_an_unknown_scope_is_probed_and_the_probe_is_recorded_before_sending(data_dir, clock):
    g = guard('reddit', clock)
    with g.request(scope='general') as slot:
        scopes = json.loads((files(data_dir, 'reddit') / 'scopes.json').read_text())
        assert scopes['general']['status'] == 'probe' and scopes['general']['pid'] == os.getpid()
        slot.classify('ok')
    assert g.snapshot()['scopes']['general']['status'] == 'unknown'  # answered without headers: unknown again


def test_a_dead_owners_unanswered_probe_is_reclaimed_after_the_longest_aside_call(data_dir, clock):
    directory = files(data_dir, 'reddit')
    directory.mkdir(parents=True)
    (directory / 'scopes.json').write_text(json.dumps(
        {'general': {'status': 'probe', 'pid': dead_pid(), 'started_at': clock.now - 10}}))
    g = guard('reddit', clock, seconds=200)
    with g.request(scope='general'):
        pass
    assert clock.now - (1_800_000_000.0 - 10) >= protection.PROBE_SECONDS  # it waited for the old probe to expire


def test_a_probe_that_cannot_be_waited_out_stops_the_scope(data_dir, clock):
    directory = files(data_dir, 'reddit')
    directory.mkdir(parents=True)
    (directory / 'scopes.json').write_text(json.dumps(
        {'general': {'status': 'probe', 'pid': dead_pid(), 'started_at': clock.now - 1}}))
    with pytest.raises(SnsError) as caught:
        with guard('reddit', clock, seconds=30).request(scope='general'):
            pass
    assert caught.value.kind == 'scope_limit'


# ⑤ unblock -----------------------------------------------------------------------------------------------------

def test_unblock_clears_the_person_block_it_read_and_nothing_else(data_dir, clock):
    g = guard('reddit', clock)
    with g.request(scope='wiki') as slot:
        slot.block('challenge')
        slot.hold(scope='wiki', until=clock.now + 500)
    checker = guard('reddit', clock)
    with checker.verify_unblock(scope='general') as check:
        assert check.person['reason'] == 'challenge'
        check.clear()
    later = guard('reddit', clock)
    later.check()                       # the person block is gone
    with pytest.raises(SnsError) as caught:
        with later.request(scope='wiki'):
            pass                        # the scope stop stays until its time
    assert caught.value.kind == 'scope_limit'
    clock.advance(501)
    with guard('reddit', clock).request(scope='wiki'):
        pass


def test_a_block_recorded_during_the_check_survives_its_clear(data_dir, clock):
    g = guard('threads', clock)
    with g.request() as slot:
        slot.block('checkpoint')
    clock.advance(5)
    checker = guard('threads', clock)
    with checker.verify_unblock() as check:
        check.block('checkpoint')       # the check itself met a new checkpoint
        check.clear()
    with pytest.raises(SnsError):
        guard('threads', clock).check()


def test_an_account_hold_refuses_the_check_and_both_stay(data_dir, clock):
    g = guard('threads', clock)
    with g.request() as slot:
        slot.hold(until=clock.now + 300)
        slot.block('checkpoint')
    with pytest.raises(SnsError) as caught:
        with guard('threads', clock).verify_unblock():
            pass
    assert caught.value.kind == 'blocked' and caught.value.details['verification_reason'] == 'rate_limited'
    snapshot = guard('threads', clock).snapshot()
    assert snapshot['person'] and snapshot['hold']
    clock.advance(301)
    with guard('threads', clock).verify_unblock() as check:
        check.clear()
    guard('threads', clock).check()


def test_one_check_per_invocation_and_a_failed_check_keeps_the_block(data_dir, clock):
    g = guard('threads', clock)
    with g.request() as slot:
        slot.block('checkpoint')
    checker = guard('threads', clock)
    with pytest.raises(RuntimeError):
        with checker.verify_unblock():
            raise RuntimeError('the check did not come back clean')
    with pytest.raises(SnsError):
        with checker.verify_unblock():
            pass
    with pytest.raises(SnsError):
        guard('threads', clock).check()


def test_requests_inside_the_check_share_its_critical_section(data_dir, clock):
    g = guard('x', clock)
    with g.request(scope='Viewer') as slot:
        slot.classify('challenge')
        slot.block('challenge', viewer='42')
    checker = guard('x', clock)
    with checker.verify_unblock(scope='Viewer') as check:
        with checker.request(setup=True, reserve=1) as inner:   # e.g. reopening the tab inside the check
            inner.charge(20)
        assert check.person['viewer'] == '42'
        check.clear()
    assert checker.setup == 21


def test_unblock_sets_unreadable_files_aside_and_keeps_a_block_until_its_check(data_dir, clock):
    guard('threads', clock).check()
    (files(data_dir) / 'blocks.json').write_text('{broken')
    (files(data_dir) / 'pace.json').write_text('[]')
    checker = guard('threads', clock)
    with checker.verify_unblock() as check:
        assert check.person['reason'] == 'unreadable'
        aside = sorted(p.name for p in files(data_dir).iterdir() if '.unreadable-' in p.name)
        assert [name.split('.unreadable-')[0] for name in aside] == ['blocks.json', 'pace.json']
        check.clear()
    guard('threads', clock).check()


# state for doctor and the legacy converter -------------------------------------------------------------------

def test_state_reports_blocks_scopes_and_the_next_request(data_dir, clock):
    g = guard('x', clock)
    with g.request(scope='SearchTimeline') as slot:
        slot.fact('SearchTimeline', Fact(limit=50, remaining=10, reset_at=clock.now + 600))
    state = g.state()
    assert state['blocked'] is False and state['scopes']['SearchTimeline']['remaining'] == 10
    assert state['next_request_at'] >= clock.now


def test_merge_keeps_the_stricter_side_and_is_idempotent(data_dir, clock):
    g = guard('threads', clock)
    with g.request() as slot:
        slot.hold(until=clock.now + 100)
    source = {'path': '/old/blocked.json', 'sha256': 'abc', 'at': 1}
    g.merge(person={'reason': 'checkpoint', 'at': clock.now - 50}, hold={'until': clock.now + 50}, source=source)
    g.merge(person={'reason': 'checkpoint', 'at': clock.now - 50}, hold={'until': clock.now + 50}, source=source)
    snapshot = g.snapshot()
    assert snapshot['person']['reason'] == 'checkpoint' and snapshot['person']['source'] == source
    assert snapshot['hold']['until'] == clock.now + 100       # the longer hold stays
    assert [entry['kind'] for entry in snapshot['provenance']] == ['imported']


def test_merge_of_scopes_takes_the_later_stop(data_dir, clock):
    g = guard('reddit', clock)
    g.merge(scopes={'general': {'blocked_until': clock.now + 300}}, source={'path': 'b', 'sha256': '1'})
    g.merge(scopes={'general': {'blocked_until': clock.now + 100}}, source={'path': 'b', 'sha256': '2'})
    assert g.snapshot()['scopes']['general']['blocked_until'] == clock.now + 300


def test_merge_refuses_a_reason_this_platform_does_not_have(data_dir, clock):
    with pytest.raises(ValueError):
        guard('threads', clock).merge(person={'reason': 'challenge', 'at': 1}, source={'path': 'a', 'sha256': 'b'})


def test_exports_are_recorded_and_forgotten(data_dir, clock):
    g = guard('threads', clock)
    g.note_export('/old/blocked.json', 'f00')
    assert [(e['kind'], e['path'], e['sha256']) for e in g.snapshot()['provenance']] == \
        [('exported', '/old/blocked.json', 'f00')]
    g.forget_export('/old/blocked.json')
    assert g.snapshot()['provenance'] == []


def test_accounts_keep_separate_state(data_dir, clock):
    with guard('threads', clock, account='u0').request() as slot:
        slot.block('checkpoint')
    guard('threads', clock, account='u1').check()


# --- repairs from the core review (Codex, 2026-10-21) ---------------------------------------------------------------

def test_a_lost_answer_keeps_the_probe_until_it_can_be_reclaimed(data_dir, clock):
    g = guard('reddit', clock)
    with pytest.raises(RuntimeError):
        with g.request(scope='general'):
            raise RuntimeError('the connection dropped: no answer')
    entry = g.snapshot()['scopes']['general']
    assert entry['status'] == 'probe'  # the request may still be in flight in the browser
    started = entry['started_at']
    later = guard('reddit', clock, seconds=200)
    with later.request(scope='general') as slot:
        slot.classify('ok')
    assert clock.now >= started + protection.PROBE_SECONDS


def test_an_answered_probe_without_headers_is_unknown_again(data_dir, clock):
    g = guard('reddit', clock)
    with g.request(scope='general') as slot:
        slot.classify('ok')
    assert g.snapshot()['scopes']['general']['status'] == 'unknown'


def test_a_live_owners_probe_is_waited_for_even_past_the_longest_call(data_dir, clock):
    directory = files(data_dir, 'reddit')
    directory.mkdir(parents=True)
    alive = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        (directory / 'scopes.json').write_text(json.dumps(
            {'general': {'status': 'probe', 'pid': alive.pid, 'started_at': clock.now - 500}}))
        with pytest.raises(SnsError) as caught:
            with guard('reddit', clock, seconds=10).request(scope='general'):
                pass
        assert caught.value.kind == 'scope_limit'
    finally:
        alive.kill()
        alive.wait()


def test_a_later_fact_does_not_lift_a_spent_scope_before_its_reset(data_dir, clock):
    g = guard('x', clock)
    with g.request(scope='SearchTimeline') as slot:
        slot.fact('SearchTimeline', Fact(limit=50, remaining=0, reset_at=clock.now + 600))
    with g.request(scope='UserTweets') as slot:  # another request reports a fresh window for the same scope
        slot.fact('SearchTimeline', Fact(limit=50, remaining=40, reset_at=clock.now + 60))
    with pytest.raises(SnsError) as caught:
        with guard('x', clock).request(scope='SearchTimeline'):
            pass
    assert caught.value.kind == 'scope_limit' and caught.value.details['reset'] >= clock.now + 590


def test_charged_and_cancelled_requests_reach_the_log(data_dir, clock):
    g = guard('threads', clock)
    with g.request(setup=True) as slot:
        slot.charge(30)
    with g.request() as slot:
        slot.cancel()
    assert g.count == 30 and g.recent()['last_day'] == 30


def test_the_checks_own_request_is_counted_once(data_dir, clock):
    g = guard('naver_blog', clock)
    with g.request() as slot:
        slot.block('network_blocked')
    checker = guard('naver_blog', clock)
    with checker.verify_unblock() as check:
        with checker.request() as inner:  # the client's one verification request
            inner.classify('ok')
        check.clear()
    assert checker.count == 1 and checker.recent()['last_day'] == 2  # the block's request and the check


def test_pacing_never_lets_a_request_take_over_a_live_commands_probe(data_dir, clock):
    directory = files(data_dir, 'reddit')
    directory.mkdir(parents=True)
    alive = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        (directory / 'scopes.json').write_text(json.dumps(
            {'general': {'status': 'probe', 'pid': alive.pid, 'started_at': clock.now}}))
        (directory / 'pace.json').write_text(json.dumps({'next_allowed_at': clock.now + 1.9}))
        with pytest.raises(SnsError):
            with guard('reddit', clock, seconds=8).request(scope='general'):
                pass
        assert json.loads((directory / 'scopes.json').read_text())['general']['pid'] == alive.pid
    finally:
        alive.kill()
        alive.wait()


def test_a_cancelled_probe_is_not_a_lost_one(data_dir, clock):
    g = guard('reddit', clock)
    with g.request(scope='general') as slot:
        slot.cancel()  # the tab was gone: nothing was sent
    assert g.snapshot()['scopes']['general']['status'] == 'unknown'


def test_an_unmetered_scope_is_paced_and_holdable_but_never_probed_or_reported(data_dir, clock):
    g = guard('reddit', clock)
    with g.request(scope='share') as slot:
        assert 'share' not in json.loads((files(data_dir, 'reddit') / 'scopes.json').read_text() or '{}') \
            if (files(data_dir, 'reddit') / 'scopes.json').exists() else True
        slot.classify('ok')
    assert 'share' not in g.limits()
    with g.request(scope='share') as slot:
        error = slot.hold(scope='share', until=clock.now + 300)
    assert error.kind == 'scope_limit'
    with pytest.raises(SnsError):
        with guard('reddit', clock).request(scope='share'):
            pass
    with guard('reddit', clock).request(scope='general') as slot:  # the other buckets go on
        slot.classify('ok')


def test_a_block_seen_while_looking_at_a_tab_reaches_the_request_log(data_dir, clock):
    g = guard('x', clock)
    with g.observe() as slot:
        slot.classify('challenge')
        slot.block('challenge')
    assert [line['outcome'] for line in log_lines(data_dir, 'x')][-1] == 'challenge'


def test_a_lock_that_cannot_be_opened_is_unreadable_state_not_a_time_limit(data_dir, clock):
    directory = files(data_dir)
    directory.mkdir(parents=True)
    (directory / 'lock').mkdir()  # a directory where the lock file should be
    with pytest.raises(SnsError) as caught:
        with guard('threads', clock).request():
            pass
    assert caught.value.kind == 'blocked' and caught.value.reason == 'unreadable'
