"""Live smoke tests against the real account, opt-in: FACEBOOK_LIVE=1 (and FACEBOOK_LIVE_POST=<a public post URL>).

They use the real skill data/ (the authoritative protection state) and the real Aside browser. Each step asserts what
it read, not only that it ran, and stays within a small request cap. Record every request_count in the budget ledger.
Unverified here: timeouts, checkpoints, concurrent invocations, response shapes not met yet.
"""
import json
import os
import shlex
import subprocess
import sys

import pytest

from conftest import CLI

pytestmark = pytest.mark.skipif(os.environ.get('FACEBOOK_LIVE') != '1', reason='live smoke is opt-in (FACEBOOK_LIVE=1)')
SPENT = []


def cli(*args, cap):
    env = {k: v for k, v in os.environ.items() if k not in ('FACEBOOK_ASIDE_BIN', 'FACEBOOK_DATA_DIR')}
    done = subprocess.run([sys.executable, str(CLI), *args, '--json'], capture_output=True, text=True, env=env, timeout=300)
    result = json.loads(done.stdout)
    charged = result['request_count'] - result.get('tab_opened_requests', 0)
    SPENT.append((' '.join(args), result['request_count']))
    print(f'LIVE {" ".join(args)} -> exit {done.returncode} requests {result["request_count"]}', file=sys.stderr)
    assert charged <= cap, result
    return done.returncode, result


def required_post_fields(record):
    assert record['id'] and record['author_url'] and isinstance(record['text'], str)
    assert record['created_at'] or record['undated']


def test_doctor_feed_post():
    env = {k: v for k, v in os.environ.items() if k not in ('FACEBOOK_ASIDE_BIN', 'FACEBOOK_DATA_DIR')}
    doctor = subprocess.run([sys.executable, str(CLI), 'doctor'], capture_output=True, text=True, env=env, timeout=300)
    assert doctor.returncode == 0, doctor.stdout
    check = json.loads(doctor.stdout)['results'][0]
    assert check['login'] == 'ready' and check['account_id'] and check['blocked'] is False

    code, feed = cli('feed', '--sort', 'recent', '--limit', '3', cap=3)
    assert code == 0 and feed['results'] and feed['stop_reason'] in ('limit_reached', 'budget')
    for record in feed['results']:
        required_post_fields(record)
    assert '--after' in feed['next']

    continuation = [word for word in shlex.split(feed['next'])[3:] if word != '--json']
    code, more = cli(*continuation, cap=3)
    assert code == 0 and more['results']
    assert not {r['id'] for r in more['results']} & {r['id'] for r in feed['results']}

    seen = [r['url'] for r in feed['results'] + more['results'] if r['url']]
    url = os.environ.get('FACEBOOK_LIVE_POST') or next((u for u in seen if '/posts/' in u), seen[0])
    code, post = cli('post', url, '--limit', '3', cap=4)
    assert code == 0, post
    first = post['results'][0]
    required_post_fields(first)
    assert first['url'] and 'kind' not in first
    comments = [r for r in post['results'][1:] if 'post_id' in r]
    assert all(c['post_id'] == first['id'] and c['depth'] == 0 for c in comments)
