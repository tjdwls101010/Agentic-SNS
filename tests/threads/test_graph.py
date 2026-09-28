"""Relationship lists through the CLI: a server-capped follower sample and paginated following."""
from .fixtures.builders import envelope, person, users
from .helpers import calls, data, run_cli


def test_followers_are_a_server_capped_sample_with_the_reported_total(routes):
    routes.set('BarcelonaFriendshipsFollowersTabQuery',
               envelope(users('followers', [person(i) for i in (50, 51)], cursor=False,
                              counts={'followers': 1000, 'following': None})))
    routes.write()
    result = run_cli('graph', '@fixture_user', 'followers', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    body = data(result)
    assert [u['id'] for u in body['results']] == ['50', '51']
    assert (body['stop_reason'], body['reported_total'], body['next']) == ('server_capped', 1000, None)
    assert body['budget']['used'] == 2


def test_following_continues_through_the_refetchable_query_by_offset(routes):
    routes.set('BarcelonaFriendshipsFollowingTabQuery',
               envelope(users('following', [person(60), person(61)], cursor='2', counts={'following': 4})))
    routes.set('BarcelonaFriendshipsFollowingTabRefetchableQuery:after=2',
               envelope(users('following', [person(62), person(63)], root='fetch__XDTUserDict')))
    routes.write()
    result = run_cli('graph', '@fixture_user', 'following', '--limit', '3', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    assert [u['id'] for u in data(result)['results']] == ['60', '61', '62']
    refetch = calls(routes.path.parent / 'requests.ndjson')[-1]
    assert refetch['name'] == 'BarcelonaFriendshipsFollowingTabRefetchableQuery'
    assert {k: v for k, v in refetch['variables'].items() if not k.startswith('__relay')} == \
        {'id': '42', 'first': 10, 'after': '2'}


def test_a_following_cursor_that_is_not_an_offset_is_drift(routes):
    routes.set('BarcelonaFriendshipsFollowingTabQuery',
               envelope(users('following', [person(60)], cursor='opaque', counts={'following': 4})))
    routes.write()
    result = run_cli('graph', '@fixture_user', 'following', '--json')
    assert result.returncode == 6
    assert data(result)['error'] == 'envelope_drift'
