"""Opt-in live smoke against the real account (SNS_LIVE=reddit or all; sends real requests through Aside). Real targets
come from the environment only, never from files: SNS_LIVE_REDDIT_SUB (a public community), SNS_LIVE_REDDIT_THREAD (a post
with hundreds of comments), SNS_LIVE_REDDIT_VISIBLE_USER and SNS_LIVE_REDDIT_HIDDEN_USER (an account whose history is
hidden). A block or a login wall ends the session: tell the person instead of retrying."""
import json
import os
import subprocess
import sys

import pytest

from tests.sns.support.cli import CLI

pytestmark = pytest.mark.live('reddit')
_FAKE = ('SNS_ASIDE_BIN', 'SNS_DATA_DIR', 'SNS_TEST_NO_WAIT', 'SNS_FAKE_SCENARIO', 'SNS_FAKE_LOG')


def target(name):
    value = os.environ.get(f'SNS_LIVE_REDDIT_{name}')
    if not value:
        pytest.skip(f'SNS_LIVE_REDDIT_{name} is not set')
    return value


def cli(*args):
    env = {k: v for k, v in os.environ.items() if k not in _FAKE}
    done = subprocess.run([sys.executable, str(CLI), 'reddit', *args, '--json'] if args[0] != 'doctor' else
                          [sys.executable, str(CLI), 'reddit', *args], capture_output=True, text=True, env=env,
                          timeout=600)
    return done.returncode, json.loads(done.stdout)


def test_doctor():
    code, envelope = cli('doctor')
    assert code == 0 and envelope['results'][0]['login'] == 'ready'


def test_a_community_page_and_its_continuation():
    sub = target('SUB')
    code, envelope = cli('sub', sub, '--limit', '5')
    assert code == 0 and len(envelope['results']) == 5 and envelope['request_count'] <= 3 and envelope['next']
    ids = [r['id'] for r in envelope['results']]
    after = envelope['next'].split('--after ')[1].split()[0]
    code, second = cli('sub', sub, '--limit', '5', '--after', after)
    assert code == 0 and second['request_count'] <= 2 and not set(ids) & {r['id'] for r in second['results']}


def test_a_large_thread_to_the_end(tmp_path):
    out = tmp_path / 'thread.ndjson'
    for _ in range(6):  # the time limit ends a run; the same command resumes
        code, envelope = cli('comments', target('THREAD'), '--out', str(out))
        if envelope['stop_reason'] == 'exhausted':
            break
    thread = envelope['thread']
    assert code == 0 and envelope['stop_reason'] == 'exhausted' and thread['unexpanded'] == 0
    assert thread['continue_threads'] == 0 and thread['stalled'] == 0


def test_profiles():
    code, envelope = cli('profile', 'u/' + target('VISIBLE_USER'), '--limit', '3')
    assert code == 0 and envelope['results']
    code, envelope = cli('profile', 'u/' + target('HIDDEN_USER'))
    assert code == 9 and 'hidden' in envelope['message'] and envelope['results'] == []
