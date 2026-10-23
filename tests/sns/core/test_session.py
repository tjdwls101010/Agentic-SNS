"""The browser session store (sns.session): one tab per platform and Aside account, leases, learned ids."""
import subprocess
import sys

import pytest

from sns.clock import Deadline
from sns.errors import SnsError
from sns.session import Session


def dead_pid():
    process = subprocess.Popen([sys.executable, '-c', 'pass'])
    process.wait()
    return process.pid


def test_the_tab_record_is_per_platform_and_account(data_dir):
    Session('threads', 'u0').set_tab('T1')
    assert Session('threads', 'u0').tab == 'T1'
    assert Session('threads', 'u1').tab is None and Session('x', 'u0').tab is None


def test_leases_track_running_commands_and_drop_dead_ones(data_dir):
    session = Session('x', 'u0')
    token = session.touch()
    assert token in session.reload().active and session.token == token
    session.release(token)
    assert session.reload().active == {} and session.released == token
    (data_dir / 'x/u0/session/tab.json').write_text(
        '{"tab": "T", "token": "t", "active": {"ghost": %d}, "released": null}' % dead_pid())
    assert Session('x', 'u0').active == {}


def test_an_unreadable_record_is_a_reset_not_a_failure(data_dir):
    Session('x', 'u0').set_tab('T1')
    (data_dir / 'x/u0/session/tab.json').write_text('{broken')
    session = Session('x', 'u0')
    assert session.tab is None and session.reset is True
    session.set_tab('T2')
    assert session.reset is False


def test_learned_ids_renames_and_nonce_counts_persist(data_dir):
    session = Session('threads', 'u0')
    session.learn('Feed', '123', {'a': True})
    session.rename('Feed', 'FeedV2')
    session.note_nonce(3, 2)
    session.note_nonce(1, 1)
    again = Session('threads', 'u0')
    assert again.query('Feed')['doc_id'] == '123' and again.query('Feed')['flags'] == {'a': True}
    assert again.renamed('Feed') == 'FeedV2' and again.nonce == {'sent': 4, 'matched': 3}


def test_dirty_and_ack(data_dir):
    session = Session('facebook', 'u0')
    session.set_dirty(True)
    assert session.dirty
    session.set_dirty(False)
    assert not session.dirty
    session.acknowledge(10)
    session.acknowledge(5)
    assert session.ack == 10


def test_the_viewer_hint_lasts_twelve_hours(data_dir, monkeypatch):
    session = Session('naver_blog', 'u0')
    session.remember_viewer('blogger', blog_no='7')
    assert session.viewer_hint()['viewer'] == 'blogger'
    import time
    real = time.time
    monkeypatch.setattr(time, 'time', lambda: real() + 13 * 3600)
    assert session.viewer_hint() is None


def test_opening_waits_only_until_the_deadline(data_dir):
    directory = data_dir / 'x/u0/session'
    directory.mkdir(parents=True)
    holder = subprocess.Popen([sys.executable, '-c', 'import fcntl,time\n'
                               f'f=open({str(directory / "tab.lock")!r},"a"); fcntl.flock(f, fcntl.LOCK_EX)\n'
                               'print("held", flush=True); time.sleep(30)'], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'held'
        with pytest.raises(SnsError) as caught:
            with Session('x', 'u0', Deadline(0.3)).opening():
                pass
        assert caught.value.reason == 'time_limit'
    finally:
        holder.kill()
        holder.wait()
