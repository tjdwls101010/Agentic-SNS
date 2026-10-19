"""session: the dedicated tab's record, the opening lock and the use token (fixtures/stores.json, session)."""
import json
import os
import subprocess
import sys
import time

from conftest import SKILL
from twitter.session import Session


def test_tab_and_learned_queries_round_trip(data_dir):
    s = Session('u0')
    s.set_tab('T1')
    s.learn('TweetDetail', 'SYNTHqTD01', None)
    again = Session('u0')
    assert again.tab == 'T1'
    assert again.query('TweetDetail')['doc_id'] == 'SYNTHqTD01'


def test_each_aside_account_has_its_own_session(data_dir):
    Session('u0').set_tab('T1')
    assert Session('u1').tab is None


def test_a_corrupt_session_is_reset_and_says_so(data_dir):
    (data_dir / 'session').mkdir(parents=True)
    (data_dir / 'session/u0.json').write_text('not json')
    s = Session('u0')
    assert s.tab is None and s.reset is True
    assert Session('u0').reset is True  # still unreadable until something is saved
    s.set_tab('T2')
    assert Session('u0').reset is False


def test_a_missing_session_is_not_a_reset(data_dir):
    assert Session('u0').reset is False


def test_opening_is_serialised_across_processes(data_dir):
    holder = subprocess.Popen([sys.executable, '-c', (
        'import time\nfrom twitter.session import Session\ns = Session("u0")\n'
        'with s.opening():\n    print("in", flush=True)\n    time.sleep(1.0)\n    s.set_tab("FIRST")\n')],
        env={**os.environ, 'PYTHONPATH': str(SKILL / 'scripts')}, stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == 'in'
    started = time.monotonic()
    s = Session('u0')
    with s.opening():
        waited = time.monotonic() - started
        assert s.reload().tab == 'FIRST'  # re-checked inside the lock: the other process already opened one
    holder.wait(timeout=10)
    assert waited >= 0.5


def test_use_tokens_tell_the_latest_command(data_dir):
    s = Session('u0')
    first = s.touch()
    second = Session('u0').touch()
    assert first != second
    assert Session('u0').token == second
    assert json.loads((data_dir / 'session/u0.json').read_text())['token'] == second


def test_acknowledged_signals_persist(data_dir):
    s = Session('u0')
    s.acknowledge(1792148826874)
    s.acknowledge(5)  # never moves back
    again = Session('u0')
    assert again.ack == 1792148826874


def test_lease_updates_wait_for_the_session_lock(data_dir):
    s = Session('u0')
    token = s.touch()
    holder = subprocess.Popen([sys.executable, '-c', (
        'import time\nfrom twitter.session import Session\ns = Session("u0")\n'
        'with s.opening():\n    print("in", flush=True)\n    time.sleep(1.0)\n    s.touch()\n')],
        env={**os.environ, 'PYTHONPATH': str(SKILL / 'scripts')}, stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == 'in'
    started = time.monotonic()
    s.release(token)  # must not overwrite the other process's lease with an older snapshot
    waited = time.monotonic() - started
    holder.wait(timeout=10)
    assert waited >= 0.5
    assert len(Session('u0').active) == 0 or token not in Session('u0').active
    assert Session('u0').released == token


def test_what_is_written_inside_account_protection_never_waits_for_the_session_lock(data_dir):
    holder = subprocess.Popen([sys.executable, '-c', (
        'import time\nfrom twitter.session import Session\ns = Session("u0")\n'
        'with s.opening():\n    print("in", flush=True)\n    time.sleep(2.0)\n')],
        env={**os.environ, 'PYTHONPATH': str(SKILL / 'scripts')}, stdout=subprocess.PIPE, text=True)
    assert holder.stdout.readline().strip() == 'in'
    s = Session('u0')
    started = time.monotonic()
    s.acknowledge(42)
    s.set_dirty(True)
    s.learn('TweetDetail', 'SYNTH9')
    assert time.monotonic() - started < 0.5  # waiting here could deadlock against a starting command
    holder.wait(timeout=10)
    again = Session('u0')
    assert again.ack == 42 and again.dirty and again.query('TweetDetail')['doc_id'] == 'SYNTH9'
