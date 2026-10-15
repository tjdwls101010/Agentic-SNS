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


@pytest.mark.skipif(not os.environ.get('FACEBOOK_LIVE_REPLIES_POST'), reason='needs FACEBOOK_LIVE_REPLIES_POST')
def test_replies_batches():
    code, post = cli('post', os.environ['FACEBOOK_LIVE_REPLIES_POST'], cap=4)
    assert code == 0, post
    with_replies = [c for c in post['results'][1:] if c.get('replies_handle')]
    assert with_replies, 'no comment with replies on the first page'
    target = max(with_replies, key=lambda c: c['reply_count'] or 0)
    code, first = cli('replies', str(target['replies_handle']), cap=2)
    assert code == 0 and first['results'] and first['thread']['parent_id'] == target['id']
    assert all(r['depth'] == 1 and r['parent_id'] == target['id'] for r in first['results'])
    if first.get('next'):
        code, second = cli(*[w for w in shlex.split(first['next'])[3:] if w != '--json'], cap=2)
        assert code == 0 and second['results']
        assert not {r['id'] for r in second['results']} & {r['id'] for r in first['results']}


def test_search_filters_and_inside_a_group():
    code, recent = cli('search', 'AI', '--type', 'posts', '--recent', '--limit', '3', cap=2)
    assert code == 0 and recent['results'] and all('kind' not in r for r in recent['results'])
    code, scoped = cli('search', 'pandas', '--type', 'posts', '--in-group', os.environ.get('FACEBOOK_LIVE_GROUP', '2968116436545420'),
                       '--limit', '3', cap=3)
    assert code == 0, scoped
    group = os.environ.get('FACEBOOK_LIVE_GROUP', '2968116436545420')
    for record in scoped['results']:
        assert record['url'] is None or '/groups/' in record['url'], record['url']


def test_page_about_and_group_card():
    code, page = cli('about', os.environ.get('FACEBOOK_LIVE_PAGE', '100064620046507'), '--section', 'directory_bio', cap=3)
    assert code == 0 and page['results'] and all(f['section'] == 'directory_bio' for f in page['results'])
    code, card = cli('about', 'https://www.facebook.com/groups/' + os.environ.get('FACEBOOK_LIVE_GROUP', '2968116436545420') + '/',
                     cap=3)
    assert code == 0, card
    [group] = card['results']
    assert group['kind'] == 'group' and group['name'] and group['privacy'] and group['member_count_text']
    assert isinstance(group['rules'], list)
