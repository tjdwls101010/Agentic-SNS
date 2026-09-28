import json
import os
import subprocess
import sys

import pytest

from ..helpers import CLI

pytestmark = pytest.mark.live


def run(*args):
    """The real CLI with real pacing, against the logged-in account."""
    done = subprocess.run([sys.executable, str(CLI), *args, '--json'], capture_output=True, text=True,
                          env=dict(os.environ), timeout=300)
    return json.loads(done.stdout)


def test_home_and_following():
    for feed in ('foryou', 'following'):
        result = run('home', '--feed', feed, '--limit', '3')
        assert result['ok'], result
        assert len(result['results']) == 3
        assert result['budget']['used'] <= (1 if feed == 'foryou' else 2)
        assert all(post['id'] and post['url'] for post in result['results'])


def test_graph_followers_and_following():
    followers = run('graph', '@zuck', 'followers', '--limit', '20')
    assert followers['ok'], followers.get('message')
    assert followers['stop_reason'] == 'server_capped'
    print('followers reported_total:', followers['reported_total'], '; received:', len(followers['results']))
    following = run('graph', '@zuck', 'following', '--limit', '25')
    assert following['ok'], following.get('message')
    assert len({u['id'] for u in following['results']}) == 25
    assert following['budget']['used'] == 3


def test_post_page():
    result = run('post', 'https://www.threads.com/@zuck/post/Dcy_A8pGo-m')
    assert result['ok'], result.get('message')
    assert result['budget']['used'] == 1
    coverage = result['completeness']
    assert coverage['received_direct'] == coverage['shown_direct'] + coverage['unshown_received']
    assert result['stop_reason'] == 'not_paginable'
    print('post coverage:', coverage)


def test_profile_direct_continuation():
    result = run('user', '@zuck', '--limit', '20')
    assert result['ok'], result.get('message')
    assert len({p['id'] for p in result['results']}) == 20
    assert result['budget']['used'] <= 4
    print('profile SSR + Direct:', result['budget']['used'], 'requests, 20 unique posts')


def test_search_accounts():
    result = run('search', 'python', '--type', 'users', '--limit', '5')
    assert result['ok'], result.get('message')
    assert len(result['results']) == 5 and result['stop_reason'] == 'not_paginable'


def test_profile_card():
    about = run('about', '@zuck')
    assert about['results'][0]['username'] == 'zuck'
    assert set(about['results'][0]['counts']) == {'followers', 'following', 'mutuals'}


def test_reply_parent_chain():
    result = run('post', 'https://www.threads.com/@ashbridge30/post/Dcy_9M-ihsR')
    assert result['ok'] and result['budget']['used'] == 1
    assert any(p['role'] == 'parent' and p['code'] == 'Dcy_A8pGo-m' for p in result['results'])
