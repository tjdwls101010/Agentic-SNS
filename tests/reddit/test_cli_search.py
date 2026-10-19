"""search, related and me through the real cli.py."""
import json

from conftest import VIEWER, run_cli


def listing(children, after=None, modhash='m'):
    return {'kind': 'Listing', 'data': {'after': after, 'modhash': modhash, 'children': children}}


def post(identity, **extra):
    return {'kind': 't3', 'data': {'id': identity, 'name': f't3_{identity}', 'title': f'title {identity}', 'is_self': True,
                                   'subreddit': extra.pop('subreddit', 'example'), 'author': 'someone',
                                   'permalink': f'/r/example/comments/{identity}/t/', 'created_utc': 1760000000, **extra}}


def test_search_sends_the_words_as_they_are(reddit):
    reddit.me().json('/search.json', listing([post('a')]), query={'q': '"claude code" author:someone', 'type': 'link',
                                                                    'sort': 'relevance'})
    code, out, _ = run_cli(reddit, 'search', '"claude code" author:someone')
    assert code == 0 and out.startswith('search · sort=relevance · type=posts · 1 shown')


def test_search_inside_one_community(reddit):
    reddit.me().json('/r/example/search.json', listing([post('a')]), query={'restrict_sr': '1', 'q': 'sync'})
    code, out, _ = run_cli(reddit, 'search', 'sync', '--in', 'r/example', '--sort', 'new')
    assert code == 0 and 'within=r/example' in out.splitlines()[0]


def test_search_communities_and_users(reddit):
    reddit.me().json('/search.json', listing([{'kind': 't5', 'data': {'id': 's1', 'name': 't5_s1',
                                                                       'display_name': 'ObsidianMD',
                                                                       'subscribers': 200000}}]), query={'type': 'sr'})
    code, out, _ = run_cli(reddit, 'search', 'obsidian', '--type', 'subs')
    assert code == 0 and '[s1] r/ObsidianMD · 200000 subscribers' in out


def test_search_refusals(reddit):
    for args in (['x', '--type', 'subs', '--in', 'r/example'], ['x', '--in', 'r/a+b'], ['   '],
                 ['x', '--type', 'users', '--since', '2026-01-01', '--sort', 'new']):
        code, out, _ = run_cli(reddit, 'search', *args)
        assert code == 2, args
    assert reddit.fetches() == []


def test_an_empty_search_is_not_retried(reddit):
    reddit.me().json('/search.json', listing([]))
    code, out, _ = run_cli(reddit, 'search', '"zqxv plorbnik"')
    assert code == 7 and reddit.paths() == ['/api/me.json', '/search.json']


def test_an_empty_search_in_a_window_is_empty(reddit):
    # measured 2026-10-20: an empty answer under --since came back as 8, stopped=budget
    reddit.me().json('/r/example/search.json', listing([]))
    code, out, _ = run_cli(reddit, 'search', 'x', '--in', 'r/example', '--sort', 'new', '--since', '2026-10-13', '--json')
    envelope = json.loads(out)
    assert code == 7 and envelope['error'] == 'empty' and envelope['stop_reason'] == 'exhausted'


def test_related_reads_the_other_discussions_of_a_link(reddit):
    reddit.me().json('/duplicates/aaa1.json', [listing([post('aaa1')]), listing([post('bbb2', subreddit='other')])])
    code, out, _ = run_cli(reddit, 'related', 'https://www.reddit.com/r/example/comments/aaa1/t/')
    assert code == 0 and '[p1] r/other' in out


def test_related_with_no_other_discussion_is_empty(reddit):
    reddit.me().json('/duplicates/aaa1.json', [listing([post('aaa1')]), listing([])])
    code, out, _ = run_cli(reddit, 'related', 'aaa1')
    assert code == 7


def test_me_saved_reads_under_the_logged_in_name(reddit):
    reddit.me().json(f'/user/{VIEWER}/saved.json', listing([post('a')]))
    code, out, _ = run_cli(reddit, 'me', 'saved')
    assert code == 0 and reddit.paths() == ['/api/me.json', f'/user/{VIEWER}/saved.json']


def test_me_subs_logged_out(reddit):
    reddit.me().json('/subreddits/mine/subscriber.json', listing([], modhash=''))
    code, out, _ = run_cli(reddit, 'me', 'subs')
    assert code == 4
