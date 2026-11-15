"""Moving the state out of the skill folder (decision A5) without losing what protects the account.

An install from before the move kept its state in data/ beside SKILL.md, and installing or updating the skill removes
that folder. Each case runs the real cli.py of a copy of the skill (its own SKILL_DIR) whose data/ holds old state,
with the fake Aside and a temporary XDG_STATE_HOME, and asks what a person relies on: a recorded block still stops
every request, the request log and pacing go on, nothing is taken twice and nothing is lost when two installs differ.
"""
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sns import protection
from sns.clock import Deadline
from sns.reddit import PLATFORM
from tests.sns.support.browser import Browser

SKILL = Path(__file__).resolve().parents[3] / '.claude/skills/sns'
ACCOUNT = 'u0'
NOW = time.time()
ME = {'status': 200, 'url': 'https://www.reddit.com/api/me.json', 'location': None,
      'body': json.dumps({'kind': 't2', 'data': {'name': 'example_viewer', 'id': 'v1'}}),
      'ratelimit': {'used': '1', 'remaining': '99.0', 'reset': '300'}}


def install(root, name='install'):
    """A copy of the skill as an installer leaves it (no data/), at root/<name>/sns."""
    target = root / name / 'sns'
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SKILL, target, ignore=shutil.ignore_patterns('__pycache__', 'data'))
    return target


def old_state(skill, *, person=None, hold=None, scopes=None, pace=None, log=(), session=None, counter=None,
              broken=None, platform='reddit'):
    """Write an old data/ the way the previous version stored it."""
    base = skill / 'data' / platform / ACCOUNT
    folder = base / 'protection'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'blocks.json').write_text(json.dumps({'person': person, 'hold': hold}))
    (folder / 'scopes.json').write_text(json.dumps(scopes or {}))
    if pace is not None:
        (folder / 'pace.json').write_text(json.dumps({'next_allowed_at': pace}))
    (folder / 'requests.jsonl').write_text(''.join(json.dumps(line) + '\n' for line in log))
    (folder / 'lock').write_text('')
    for name, text in (broken or {}).items():
        (folder / name).write_text(text)
    for name, value in (session or {}).items():
        (base / 'session').mkdir(parents=True, exist_ok=True)
        (base / 'session' / name).write_text(json.dumps(value))
    if counter is not None:
        (skill / 'data' / 'handles').mkdir(parents=True, exist_ok=True)
        (skill / 'data' / 'handles' / 'counter').write_text(str(counter))
    return base


class World:
    """One computer: a state home every install shares, a fake Aside, and runs of a given install's cli.py."""

    def __init__(self, root):
        self.root = root
        self.state_home = root / 'xdg'
        self.browser = Browser(root / 'browser')
        self.browser.root.mkdir(parents=True, exist_ok=True)

    def env(self, **extra):
        self.browser.write()
        return {'PATH': '/usr/bin:/bin', 'HOME': str(self.root / 'home'), 'XDG_STATE_HOME': str(self.state_home),
                **self.browser.env(), **extra}

    def run(self, skill, *args, platform='reddit', **extra):
        done = subprocess.run([sys.executable, str(skill / 'scripts/cli.py'), platform, *args], capture_output=True,
                              text=True, env=self.env(**extra), timeout=120)
        return done.returncode, json.loads(done.stdout)

    def start(self, skill, *args, platform='reddit', **extra):
        return subprocess.Popen([sys.executable, str(skill / 'scripts/cli.py'), platform, *args],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env(**extra))

    def requests(self):
        """Every call that could reach a site: page functions and fetches, tab openings (not the CLI's own lookups)."""
        return [c for c in self.browser.calls() if c['op'] not in ('account_status', 'version', 'tabs')]

    def fetches(self):
        return [c for c in self.browser.calls() if c['op'] == 'reddit.fetch']

    def guard(self):
        """The shared protection state, read through the store's own interface."""
        with pytest.MonkeyPatch.context() as patched:
            patched.setenv('SNS_DATA_DIR', str(self.state_home / 'agentic-sns'))
            return protection.open('reddit', ACCOUNT, PLATFORM.policy, Deadline(30), title=PLATFORM.title,
                                   site=PLATFORM.site)

    def state(self, platform='reddit'):
        adapter = importlib.import_module(f'sns.{platform}').PLATFORM
        with pytest.MonkeyPatch.context() as patched:
            patched.setenv('SNS_DATA_DIR', str(self.state_home / 'agentic-sns'))
            guard = protection.open(platform, ACCOUNT, adapter.policy, Deadline(30), title=adapter.title,
                                    site=adapter.site)
            return guard.state(), guard.recent(), guard.snapshot()['provenance']


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.delenv('SNS_DATA_DIR', raising=False)
    return World(tmp_path)


CHALLENGE = {'reason': 'challenge', 'at': NOW - 600, 'viewer': None}


def test_a_recorded_block_in_an_old_data_still_stops_every_request(world):
    """① The first command after the update finds the old block: exit 5, no request; doctor says where it came from."""
    skill = install(world.root)
    old_state(skill, person=CHALLENGE)
    code, result = world.run(skill, 'doctor')
    assert code == 5 and result['error'] == 'blocked' and world.fetches() == []
    code, result = world.run(skill, 'sub', 'r/python')
    assert code == 5 and world.fetches() == []
    assert (skill / 'data' / 'reddit' / ACCOUNT / 'protection' / 'blocks.json').exists()  # the old data/ stays as is


def test_the_block_outlives_the_skill_folder(world):
    """② The skill folder is removed and copied again (an update): the block is kept outside it."""
    skill = install(world.root)
    old_state(skill, person=CHALLENGE)
    world.run(skill, 'doctor')
    skill = install(world.root)  # a fresh copy: no data/ at all
    code, result = world.run(skill, 'doctor')
    assert code == 5 and result['error'] == 'blocked' and world.fetches() == []


@pytest.mark.parametrize('order', [('first', 'second'), ('second', 'first')])
def test_two_installs_with_different_stops_keep_both_whatever_runs_first(world, order):
    """③ One install recorded a person block, the other a hold and a scope stop: whichever runs first, the state ends
    with all three and no request goes out."""
    installs = {'first': install(world.root, 'first'), 'second': install(world.root, 'second')}
    old_state(installs['first'], person=CHALLENGE)
    old_state(installs['second'], hold={'reason': 'rate_limit', 'at': NOW, 'until': NOW + 3600},
              scopes={'general': {'status': 'unknown', 'blocked_until': NOW + 1800}})
    for name in order:
        code, _ = world.run(installs[name], 'sub', 'r/python')
        assert code == 5
    state, _, _ = world.state()
    assert state['person']['reason'] == 'challenge'
    assert state['hold']['until'] == pytest.approx(NOW + 3600)
    assert state['scopes']['general']['blocked_until'] == pytest.approx(NOW + 1800)
    assert world.fetches() == []


def test_a_changed_old_data_is_taken_in_again_even_back_to_content_seen_before(world):
    """④ A copy of the old version still writing there, or an old data/ put back: each change is taken in again; a
    return to content taken once before is a change too (the last taking from that path is what counts)."""
    skill = install(world.root)
    first = {'general': {'status': 'unknown', 'blocked_until': NOW + 900}}
    old_state(skill, scopes=first)
    world.run(skill, 'doctor')
    _, _, provenance = world.state()
    assert len([e for e in provenance if e['kind'] == 'imported']) == 1
    world.run(skill, 'doctor')  # nothing changed: nothing taken
    assert len([e for e in world.state()[2] if e['kind'] == 'imported']) == 1
    old_state(skill, scopes={'general': {'status': 'unknown', 'blocked_until': NOW + 2400}})
    world.run(skill, 'doctor')
    assert world.state()[0]['scopes']['general']['blocked_until'] == pytest.approx(NOW + 2400)
    old_state(skill, scopes=first)  # back to the first content
    world.run(skill, 'doctor')
    assert len([e for e in world.state()[2] if e['kind'] == 'imported']) == 3
    assert world.state()[0]['scopes']['general']['blocked_until'] == pytest.approx(NOW + 2400)  # the later end stays


def test_two_commands_starting_together_finish_and_send_nothing_past_the_block(world):
    """⑤ Both take the protection lock once to import; neither waits on the other forever."""
    skill = install(world.root)
    old_state(skill, person=CHALLENGE)
    world.browser.write()
    real = {'SNS_TEST_NO_WAIT': ''}  # under the fake's virtual clock a lock wait passes the deadline at once
    runs = [world.start(skill, 'sub', 'r/python', **real), world.start(skill, 'doctor', **real)]
    codes = [run.wait(timeout=60) for run in runs]
    assert codes == [5, 5] and world.fetches() == []


def test_the_request_log_pacing_session_and_handle_numbers_go_on(world):
    """⑥ The old log's last day joins the new one once (taking the same lines again adds nothing); pacing keeps the later
    next request; the old session is used where this one has none; handle numbers go on from the larger counter."""
    skill = install(world.root)
    log = [{'at': NOW - 120, 'id': 'r1', 'n': 1, 'outcome': 'ok'}, {'at': NOW - 60, 'id': 'r2', 'n': 2, 'outcome': 'ok'},
           {'at': NOW - 2 * 86400, 'id': 'r0', 'n': 5, 'outcome': 'ok'}]
    old_state(skill, log=log, pace=NOW - 5, session={'viewer.json': {'viewer': 'old_viewer', 'at': NOW}},
              counter=4321)
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(skill, 'doctor')
    assert code == 0, result
    check = result['results'][0]
    assert check['requests_last_day'] == 3 + 1  # the old day's 3 (not the 2-day-old line) and doctor's own
    assert [i['path'] for i in check['imported_from']] == [str(skill / 'data' / 'reddit' / ACCOUNT / 'protection')]
    session = world.state_home / 'agentic-sns' / 'reddit' / ACCOUNT / 'session'
    assert (session / 'viewer.json').exists()
    old_state(skill, log=log + [{'at': NOW - 30, 'id': 'r3', 'n': 1, 'outcome': 'ok'}], pace=NOW - 5)
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(skill, 'doctor')
    assert code == 0 and result['results'][0]['requests_last_day'] == 3 + 1 + 1 + 1  # only r3 and doctor are new
    counter = world.state_home / 'agentic-sns' / 'handles' / 'counter'
    assert int(counter.read_text()) >= 4321


def test_a_run_with_its_own_state_directory_takes_nothing_in(world, tmp_path):
    """⑦ Tests and contrast runs name SNS_DATA_DIR: the real old data/ is not theirs to import."""
    skill = install(world.root)
    old_state(skill, person=CHALLENGE)
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(skill, 'doctor', SNS_DATA_DIR=str(tmp_path / 'own'))
    assert code == 0, result
    assert result['results'][0]['imported_from'] == []
    assert not (world.state_home / 'agentic-sns').exists()


def test_two_installs_updated_in_turn_with_their_data_put_back_keep_both_blocks(world):
    """⑨ `npx skills add` removes the folder before new code runs; the README says to move data/ aside and put it back
    after the update. Two installs updated that way, one after the other, keep both of their blocks."""
    for name, stops in (('first', {'person': CHALLENGE}),
                        ('second', {'hold': {'reason': 'rate_limit', 'at': NOW, 'until': NOW + 3600}})):
        old = install(world.root, name)
        old_state(old, **stops)
        kept = world.root / f'{name}-data-kept'
        shutil.move(str(old / 'data'), kept)          # moved aside before the update
        new = install(world.root, name)               # the update replaces the folder
        shutil.move(str(kept), new / 'data')          # put back after it
        code, _ = world.run(new, 'sub', 'r/python')
        assert code == 5
    state, _, _ = world.state()
    assert state['person']['reason'] == 'challenge' and state['hold']['until'] == pytest.approx(NOW + 3600)
    assert world.fetches() == []


def test_unreadable_old_state_blocks_until_a_person_lifts_it_once(world):
    """Old state that cannot be read is not skipped: it is a person block, and doctor --unblock lifts it once; the same
    old files are not taken in again afterwards."""
    skill = install(world.root)
    old_state(skill, broken={'blocks.json': '{not json'})
    code, result = world.run(skill, 'sub', 'r/python')
    assert code == 5 and result['error'] == 'blocked' and world.fetches() == []
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(skill, 'doctor', '--unblock')
    assert code == 0, result
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(skill, 'doctor')
    assert code == 0, result


def test_a_block_a_person_cleared_here_is_not_brought_back_by_the_old_copy(world):
    """A person cleared the old block with doctor --unblock; the old data/ still holds it and later changes (an old copy
    writes its log): the cleared block does not come back, a newer one would."""
    skill = install(world.root)
    old_state(skill, person=CHALLENGE)
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(skill, 'doctor', '--unblock')
    assert code == 0, result
    old_state(skill, person=CHALLENGE, log=[{'at': NOW - 10, 'id': 'late', 'n': 1, 'outcome': 'ok'}])
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(skill, 'doctor')
    assert code == 0, result
    old_state(skill, person={**CHALLENGE, 'at': time.time() + 1})
    code, result = world.run(skill, 'doctor')
    assert code == 5


def test_a_cleared_block_does_not_hide_another_installs_older_block(world):
    """A person cleared install A's block; install B's own block, recorded before that clear, is another block and is
    taken in when B first runs (review of P2: a clear used to hide every older block)."""
    first, second = install(world.root, 'first'), install(world.root, 'second')
    old_state(first, person=CHALLENGE)
    old_state(second, person={**CHALLENGE, 'at': NOW - 900})
    shutil.move(str(second / 'data'), world.root / 'second-data')  # B has not run yet
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(first, 'doctor', '--unblock')
    assert code == 0, result
    shutil.move(str(world.root / 'second-data'), second / 'data')
    code, _ = world.run(second, 'sub', 'r/python')
    assert code == 5 and world.state()[0]['person']['at'] == pytest.approx(NOW - 900)


def test_one_unreadable_old_file_does_not_drop_what_the_others_hold(world):
    """An old scopes.json that cannot be read is a block for unreadable state; the hold beside it still comes in, so
    doctor --unblock cannot make its check through it (review of P2)."""
    skill = install(world.root)
    old_state(skill, hold={'reason': 'rate_limit', 'at': NOW, 'until': NOW + 3600}, broken={'scopes.json': '[broken'})
    code, _ = world.run(skill, 'sub', 'r/python')
    assert code == 5
    state, _, _ = world.state()
    assert state['person']['reason'] == 'unreadable' and state['hold']['until'] == pytest.approx(NOW + 3600)
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(skill, 'doctor', '--unblock')
    assert code == 5 and world.requests() == []  # the hold stands: the check is not made


def test_any_command_takes_in_every_platforms_old_state(world):
    """A reddit command run once after the update also takes in an X block, so the next reinstall cannot drop it before
    the first X command (review of P2)."""
    skill = install(world.root)
    old_state(skill, platform='x', person={'reason': 'account_locked', 'at': NOW - 60, 'viewer': None})
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(skill, 'doctor')
    assert code == 0, result
    assert world.state('x')[0]['person']['reason'] == 'account_locked'
    skill = install(world.root)  # the next reinstall: no data/ any more
    code, result = world.run(skill, 'doctor', platform='x')
    assert code == 5 and result['error'] == 'blocked'
    assert [c for c in world.requests() if c['op'] != 'reddit.fetch'] == []


def test_the_same_line_twice_in_one_old_log_is_one_request(world):
    skill = install(world.root)
    line = {'at': NOW - 120, 'id': 'r1', 'n': 3, 'outcome': 'ok'}
    old_state(skill, log=[line, line])
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(skill, 'doctor')
    assert code == 0 and result['results'][0]['requests_last_day'] == 3 + 1


def test_pacing_keeps_the_later_next_request(world):
    skill = install(world.root)
    old_state(skill, pace=NOW + 3000)
    world.run(skill, 'doctor')  # a doctor that has to wait that long ends at its time limit; the pace is what matters
    with pytest.MonkeyPatch.context() as patched:
        patched.setenv('SNS_DATA_DIR', str(world.state_home / 'agentic-sns'))
        guard = protection.open('reddit', ACCOUNT, PLATFORM.policy, Deadline(30), title=PLATFORM.title,
                                site=PLATFORM.site)
        assert guard.state()['next_request_at'] >= NOW + 3000 - 1


def test_the_old_session_fills_only_what_this_one_lacks(world):
    """The old install's tab record is used where this one has none; a record this install already wrote stays."""
    skill = install(world.root)
    session = world.state_home / 'agentic-sns' / 'x' / ACCOUNT / 'session'
    session.mkdir(parents=True)
    (session / 'tab.json').write_text(json.dumps({'tab': 'NEW_TAB'}))
    old_state(skill, platform='x', session={'tab.json': {'tab': 'OLD_TAB'}, 'queries.json': {'queries': {'Q': 1}}})
    world.run(skill, 'schema', platform='x')  # a command with no connection still takes the old state in
    assert json.loads((session / 'tab.json').read_text()) == {'tab': 'NEW_TAB'}
    assert json.loads((session / 'queries.json').read_text()) == {'queries': {'Q': 1}}


def test_first_commands_of_several_platforms_at_once_all_stop_at_their_blocks(world):
    """Commands of three platforms start together on an install whose old data/ blocks all three: each takes the old
    state in under the protection locks without waiting on the others forever, and none sends anything."""
    skill = install(world.root)
    for platform, reason in (('x', 'account_locked'), ('threads', 'checkpoint'), ('reddit', 'challenge')):
        old_state(skill, platform=platform, person={'reason': reason, 'at': NOW - 60, 'viewer': None})
    world.browser.write()
    real = {'SNS_TEST_NO_WAIT': ''}  # a lock is waited for in real time here, as it is outside the tests
    runs = [world.start(skill, 'doctor', platform='x', **real), world.start(skill, 'doctor', platform='threads', **real),
            world.start(skill, 'sub', 'r/python', **real)]
    assert [run.wait(timeout=90) for run in runs] == [5, 5, 5]
    assert world.requests() == []


def test_a_second_block_waits_for_the_first_to_be_cleared_and_then_stands(world):
    """Two installs' different blocks both came in before a person cleared the first: only one block stands at a time,
    so the second stays owed and takes its place at the next command after the clear (review of P2, second round)."""
    first, second = install(world.root, 'first'), install(world.root, 'second')
    old_state(first, person=CHALLENGE)
    old_state(second, person={**CHALLENGE, 'at': NOW - 900})
    assert world.run(first, 'sub', 'r/python')[0] == 5
    assert world.run(second, 'sub', 'r/python')[0] == 5
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(first, 'doctor', '--unblock')
    assert code == 0, result
    code, _ = world.run(second, 'sub', 'r/python')  # each install sees only its own old data/
    assert code == 5 and world.state()[0]['person']['at'] == pytest.approx(NOW - 900)
    assert len(world.fetches()) == 1  # the unblock check alone


def test_an_unreadable_old_file_behind_a_standing_block_still_blocks_after_that_clear(world):
    first, second = install(world.root, 'first'), install(world.root, 'second')
    old_state(first, person=CHALLENGE)
    old_state(second, broken={'scopes.json': '[broken'})
    world.run(first, 'sub', 'r/python')
    world.run(second, 'sub', 'r/python')
    world.browser.respond('reddit.fetch', ME)
    assert world.run(first, 'doctor', '--unblock')[0] == 0
    code, _ = world.run(second, 'sub', 'r/python')
    assert code == 5 and world.state()[0]['person']['reason'] == 'unreadable'


def test_a_scope_record_missing_a_field_is_unreadable_not_weakened(world):
    """A `known` scope without its limit is not accepted as 'unknown' (which would allow a probe): it is unreadable."""
    skill = install(world.root)
    old_state(skill, scopes={'general': {'status': 'known', 'remaining': 0, 'reset_at': NOW + 600}})
    code, _ = world.run(skill, 'sub', 'r/python')
    assert code == 5 and world.state()[0]['person']['reason'] == 'unreadable' and world.fetches() == []


def test_a_broken_person_record_does_not_take_the_hold_beside_it_down(world):
    skill = install(world.root)
    old_state(skill, person={'reason': 'not-a-reason', 'at': 'yesterday'},
              hold={'reason': 'rate_limit', 'at': NOW, 'until': NOW + 3600})
    code, _ = world.run(skill, 'sub', 'r/python')
    state, _, _ = world.state()
    assert code == 5 and state['person']['reason'] == 'unreadable' and state['hold']['until'] == pytest.approx(NOW + 3600)


def test_a_command_that_makes_no_connection_still_takes_the_old_state_in(world):
    """`schema` sends nothing and opens no connection; run once after the update, it still carries the old block over,
    so a reinstall right after it loses nothing (review of P2, second round)."""
    skill = install(world.root)
    old_state(skill, person=CHALLENGE)
    code, _ = world.run(skill, 'schema')
    assert code == 0 and world.state()[0]['person']['reason'] == 'challenge'


def test_a_valid_block_and_a_broken_file_in_one_old_state_each_stand_in_turn(world):
    """The old state holds a challenge and an unreadable scopes.json: the challenge stands first; once a person clears
    it, the block for the unreadable file takes its place (review of P2, third round)."""
    skill = install(world.root)
    old_state(skill, person=CHALLENGE, broken={'scopes.json': '[broken'})
    assert world.run(skill, 'sub', 'r/python')[0] == 5
    assert world.state()[0]['person']['reason'] == 'challenge'
    world.browser.respond('reddit.fetch', ME)
    assert world.run(skill, 'doctor', '--unblock')[0] == 0
    code, _ = world.run(skill, 'sub', 'r/python')
    assert code == 5 and world.state()[0]['person']['reason'] == 'unreadable'
    world.browser.respond('reddit.fetch', ME)
    assert world.run(skill, 'doctor', '--unblock')[0] == 0
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(skill, 'doctor')  # both stood and were cleared: the same old files are not taken again
    assert code == 0, result


@pytest.mark.parametrize('platform', ['reddit', 'x'])
def test_a_scope_record_of_an_odd_shape_is_unreadable_and_never_crashes_a_command(world, platform):
    """A status that is a list (or any non-string) is unreadable state, here or for another platform's old record."""
    skill = install(world.root)
    old_state(skill, platform=platform, scopes={'general': {'status': []}})
    code, result = world.run(skill, 'schema')
    assert code == 0, result
    assert world.state(platform)[0]['person']['reason'] == 'unreadable'


def test_an_old_unreadable_block_comes_in_like_any_other(world):
    """The old store's own block for unreadable state (no source of its own) is a block like the others."""
    skill = install(world.root)
    old_state(skill, person={'reason': 'unreadable', 'at': NOW - 60, 'viewer': None})
    code, _ = world.run(skill, 'sub', 'r/python')
    assert code == 5 and world.state()[0]['person']['reason'] == 'unreadable' and world.fetches() == []


def test_a_cleared_block_for_a_broken_file_stays_cleared_while_the_old_log_grows(world):
    """An old copy still running keeps appending to its log; the broken file it stands for is unchanged, so once a person
    cleared that block it does not come back (review of P2, fourth round)."""
    skill = install(world.root)
    old_state(skill, broken={'scopes.json': '[broken'})
    assert world.run(skill, 'sub', 'r/python')[0] == 5
    world.browser.respond('reddit.fetch', ME)
    assert world.run(skill, 'doctor', '--unblock')[0] == 0
    log = skill / 'data' / 'reddit' / ACCOUNT / 'protection' / 'requests.jsonl'
    log.write_text(json.dumps({'at': NOW - 5, 'id': 'more', 'n': 1, 'outcome': 'ok'}) + '\n')
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(skill, 'doctor')
    assert code == 0, result


def test_an_owed_block_survives_its_installs_next_update(world):
    """B's block came in while A's stood, then B was updated again (its old data/ removed) before A was cleared: the
    owed block waits in the shared state, so clearing A puts B's in its place (review of P2, fifth round)."""
    first, second = install(world.root, 'first'), install(world.root, 'second')
    old_state(first, person=CHALLENGE)
    old_state(second, person={**CHALLENGE, 'at': NOW - 900})
    assert world.run(first, 'sub', 'r/python')[0] == 5
    assert world.run(second, 'sub', 'r/python')[0] == 5
    second = install(world.root, 'second')  # updated again without its data/ put back
    world.browser.respond('reddit.fetch', ME)
    assert world.run(first, 'doctor', '--unblock')[0] == 0
    code, _ = world.run(second, 'sub', 'r/python')
    assert code == 5 and world.state()[0]['person']['at'] == pytest.approx(NOW - 900)
    assert len(world.fetches()) == 1  # the unblock check alone


def test_an_old_copys_request_in_flight_keeps_its_scope_probe(world):
    """An old copy still running has a probe out in a scope; the new copy does not send another into it meanwhile."""
    skill = install(world.root)
    old_state(skill, scopes={'general': {'status': 'probe', 'pid': os.getpid(), 'started_at': time.time()}})
    world.run(skill, 'schema')
    assert world.state()[0]['scopes']['general']['status'] == 'probe'


def test_an_old_probe_holds_a_scope_this_store_knew_as_open(world):
    """The shared scope was known with requests left, but an old copy has a request in flight in it: the probe wins
    until it is answered or reclaimable (review of P2, sixth round)."""
    skill = install(world.root)
    world.run(skill, 'schema')
    with pytest.MonkeyPatch.context() as patched:
        patched.setenv('SNS_DATA_DIR', str(world.state_home / 'agentic-sns'))
        from sns.limits import Fact
        with protection.open('reddit', ACCOUNT, PLATFORM.policy, Deadline(30), title=PLATFORM.title,
                             site=PLATFORM.site).request(scope='general') as slot:
            slot.fact('general', Fact(100, 90, time.time() + 300))
    assert world.state()[0]['scopes']['general']['status'] == 'known'
    old_state(skill, scopes={'general': {'status': 'probe', 'pid': os.getpid(), 'started_at': time.time()}})
    world.run(skill, 'schema')
    assert world.state()[0]['scopes']['general']['status'] == 'probe'


def test_a_clear_that_stopped_halfway_does_not_bring_the_cleared_block_back_twice(world):
    """The queue still lists the block that now stands (the second write of a clear did not happen): clearing that
    block drops its queued copy instead of putting it back."""
    first, second = install(world.root, 'first'), install(world.root, 'second')
    old_state(first, person=CHALLENGE)
    old_state(second, person={**CHALLENGE, 'at': NOW - 900})
    world.run(first, 'sub', 'r/python')
    world.run(second, 'sub', 'r/python')
    provenance = world.state_home / 'agentic-sns' / 'reddit' / ACCOUNT / 'protection' / 'imported.json'
    blocks = world.state_home / 'agentic-sns' / 'reddit' / ACCOUNT / 'protection' / 'blocks.json'
    queued = next(e for e in json.loads(provenance.read_text())['entries'] if e['kind'] == 'owed')
    blocks.write_text(json.dumps({'person': queued['person'], 'hold': None}))  # first write done, second not
    world.browser.respond('reddit.fetch', ME)
    assert world.run(second, 'doctor', '--unblock')[0] == 0
    world.browser.respond('reddit.fetch', ME)
    code, result = world.run(second, 'doctor')
    assert code == 0, result


def test_an_old_probe_does_not_open_a_spent_scope_before_its_reset(world):
    """A spent scope stops until its reset; an old copy's probe does not replace that stop (review of P2, last round)."""
    skill = install(world.root)
    world.run(skill, 'schema')
    with pytest.MonkeyPatch.context() as patched:
        patched.setenv('SNS_DATA_DIR', str(world.state_home / 'agentic-sns'))
        from sns.limits import Fact
        with protection.open('reddit', ACCOUNT, PLATFORM.policy, Deadline(30), title=PLATFORM.title,
                             site=PLATFORM.site).request(scope='general') as slot:
            slot.fact('general', Fact(100, 0, time.time() + 3600))
    old_state(skill, scopes={'general': {'status': 'probe', 'pid': os.getpid(), 'started_at': time.time()}})
    world.run(skill, 'schema')
    scope = world.state()[0]['scopes']['general']
    assert scope['status'] == 'known' and scope['remaining'] == 0
