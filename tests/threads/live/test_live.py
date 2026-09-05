import pytest

from threads_skill.threads import parser
from threads_skill._target import parse_target
from threads_skill._cmds_browse import run
from threads_skill._cmds_post import run as run_post

pytestmark = pytest.mark.live


def args(*values):
    parsed = parser().parse_args(values)
    if hasattr(parsed, 'target'):
        parsed.target = parse_target(parsed.target, 'post' if parsed.command == 'post' else 'user')
    return parsed


def test_home_and_following():
    for feed in ('foryou', 'following'):
        result = run(args('home', '--feed', feed, '--limit', '3'))
        assert result['ok'], result
        assert len(result['results']) == 3
        assert result['budget']['used'] <= (1 if feed == 'foryou' else 2)
        assert all(post['id'] and post['url'] for post in result['results'])


def test_graph_followers_and_following():
    followers = run(args('graph', '@zuck', 'followers', '--limit', '20'))
    assert followers['ok'], followers.get('message')
    assert followers['stop_reason'] == 'server_capped'
    print('followers reported_total:', followers['reported_total'], '; received:', len(followers['results']))
    following = run(args('graph', '@zuck', 'following', '--limit', '25'))
    assert following['ok'], following.get('message')
    assert len({u['id'] for u in following['results']}) == 25
    assert following['budget']['used'] == 3


def test_following_pagination():
    result = run(args('graph', '@zuck', 'following', '--limit', '25'))
    assert result['ok'], result.get('message')
    assert len({u['id'] for u in result['results']}) == 25
    assert result['budget']['used'] == 3


def test_post_page():
    result = run_post(args('post', 'https://www.threads.com/@zuck/post/Dcy_A8pGo-m'))
    assert result['ok'], result.get('message')
    assert result['budget']['used'] == 1
    coverage = result['completeness']
    assert coverage['received_direct'] == coverage['shown_direct'] + coverage['unshown_received']
    assert result['stop_reason'] == 'not_paginable'
    print('post coverage:', coverage)


def test_profile_ssr_cursor_and_about():
    result = run(args('user', '@zuck', '--limit', '6'))
    assert result['ok'], result
    ids = [post['id'] for post in result['results']]
    assert len(ids) == len(set(ids)) == 6
    assert result['budget']['used'] <= 3
    print('profile SSR -> Direct:', result['budget']['used'], 'requests;', len(ids), 'unique posts')
    about = run_post(args('about', '@zuck'))
    assert about['ok'], about
    assert set(about['results'][0]['counts']) == {'followers', 'following', 'mutuals'}
