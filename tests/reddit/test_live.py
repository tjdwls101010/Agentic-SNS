"""Opt-in live smoke against the real account (REDDIT_LIVE=1). Real targets come from the environment only, never
from files: REDDIT_LIVE_SUB (a public community), REDDIT_LIVE_THREAD (a post with hundreds of comments),
REDDIT_LIVE_VISIBLE_USER and REDDIT_LIVE_HIDDEN_USER (an account whose history is hidden). Every request it makes must
also be written to the development ledger by whoever runs it."""
import json
import os
import subprocess
import sys

import pytest

from conftest import CLI

LIVE = os.environ.get('REDDIT_LIVE') == '1'
pytestmark = pytest.mark.skipif(not LIVE, reason='live smoke is opt-in (REDDIT_LIVE=1)')


def cli(*args):
    env = {k: v for k, v in os.environ.items() if k not in ('REDDIT_ASIDE_BIN', 'REDDIT_DATA_DIR', 'REDDIT_TEST_NO_WAIT')}
    done = subprocess.run([sys.executable, str(CLI), *args, '--json'] if args[0] != 'doctor' else
                          [sys.executable, str(CLI), *args], capture_output=True, text=True, env=env, timeout=600)
    return done.returncode, json.loads(done.stdout)


def test_doctor():
    code, envelope = cli('doctor')
    assert code == 0 and envelope['results'][0]['login'] == 'ready'


def test_a_community_page_and_its_continuation():
    code, envelope = cli('sub', os.environ['REDDIT_LIVE_SUB'], '--limit', '5')
    assert code == 0 and len(envelope['results']) == 5 and envelope['request_count'] <= 2 and envelope['next']
    ids = [r['id'] for r in envelope['results']]
    after = envelope['next'].split('--after ')[1].split()[0]
    code, second = cli('sub', os.environ['REDDIT_LIVE_SUB'], '--limit', '5', '--after', after)
    assert code == 0 and second['request_count'] == 0 and not set(ids) & {r['id'] for r in second['results']}


def test_a_large_thread_to_the_end(tmp_path):
    out = tmp_path / 'thread.ndjson'
    code, envelope = cli('comments', os.environ['REDDIT_LIVE_THREAD'], '--out', str(out), '--max-requests', '60')
    thread = envelope['thread']
    assert code == 0 and envelope['stop_reason'] == 'exhausted' and thread['unexpanded'] == 0
    assert thread['continue_threads'] == 0 and thread['stalled'] == 0 and envelope['request_count'] <= 60


def test_profiles():
    code, envelope = cli('profile', 'u/' + os.environ['REDDIT_LIVE_VISIBLE_USER'], '--limit', '3')
    assert code == 0 and envelope['results']
    code, envelope = cli('profile', 'u/' + os.environ['REDDIT_LIVE_HIDDEN_USER'])
    assert code == 9 and envelope['reason'] == 'history_not_visible' and envelope['results'] == []
