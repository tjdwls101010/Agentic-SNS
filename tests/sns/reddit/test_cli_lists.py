"""sub and feed through the real cli: a page of 100 shown 25 at a time, the rest served from the handle, date windows on
sort new (a sort left out reads as new and says so), the account a continuation was read with, and the failures a
listing can end in."""
import json

from tests.sns.reddit.scene import VIEWER
from tests.sns.reddit.shapes import epoch, listing, post
from tests.sns.support.cli import command_of, more_line


def more_words(out):
    line = more_line(out)
    return command_of(line) if line else None


def test_a_page_of_100_is_shown_25_and_the_rest_waits_in_the_handle(reddit):
    reddit.me().json('/r/example/hot.json', listing([post(f'p{i}') for i in range(100)], after='t3_p99'),
                     query={'limit': 100})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example')
    assert code == 0
    first = out.splitlines()[0]
    assert first.startswith('reddit sub · sort=hot · 25 shown · stopped=limit_reached · requests=2 · limit general 98 of 100 left')
    assert out.count('\n[p') == 25 and 'url: https://www.reddit.com/r/example/comments/p0/t/' in out
    assert reddit.paths() == ['/api/me.json', '/r/example/hot.json']
    reddit.me()  # a continued reading checks the account it was read with
    code, out, _ = reddit.run(*more_words(out))
    assert code == 0 and '25 shown' in out.splitlines()[0] and '[p1] r/example · u/someone' in out
    assert 'title p25' in out and 'title p0' not in out
    assert reddit.paths() == ['/api/me.json', '/r/example/hot.json', '/api/me.json'], 'the waiting records cost no listing'


def test_a_continuation_costs_the_account_check_and_no_listing_request(reddit):
    reddit.me().json('/r/example/hot.json', listing([post(f'p{i}') for i in range(30)], after='t3_p29'))
    code, out, _ = reddit.run('reddit', 'sub', 'r/example')
    reddit.me()
    code, out, _ = reddit.run(*more_words(out))
    assert code == 0 and 'requests=1 ' in out.splitlines()[0]
    assert reddit.paths() == ['/api/me.json', '/r/example/hot.json', '/api/me.json']


def test_limit_and_the_next_page(reddit):
    reddit.me().json('/r/example/new.json', listing([post('a'), post('b')], after='t3_b'), query={'limit': 100})
    reddit.me().json('/r/example/new.json', listing([post('c')]), query={'after': 't3_b'})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--limit', '2')
    assert code == 0 and '2 shown' in out
    code, out, _ = reddit.run(*more_words(out))
    assert code == 0 and 'title c' in out and 'stopped=exhausted' in out and more_words(out) is None
    assert reddit.paths() == ['/api/me.json', '/r/example/new.json', '/api/me.json', '/r/example/new.json']


def test_a_window_on_sort_new_closes_on_older_posts(reddit):
    reddit.me().json('/r/example/new.json', listing([
        post('pin', epoch('2025-01-01T00:00:00'), stickied=True),
        post('new', epoch('2026-10-08T01:00:00')),
        post('in1', epoch('2026-10-07T14:59:00')),
        post('in2', epoch('2026-10-04T15:00:00')),
        post('old', epoch('2026-10-04T13:00:00'))], after='t3_old'), query={'limit': 100})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--since', '2026-10-05', '--until',
                              '2026-10-07', env={'TZ': 'Asia/Seoul'})
    assert code == 0
    lines = out.splitlines()
    assert 'stopped=window_reached' in lines[0] and 'sort=new ·' in lines[0] and '(window)' not in lines[0]
    assert lines[1].startswith('window 2026-10-05..2026-10-07 KST · closed (as served)')
    assert 'title in1' in out and 'title in2' in out and 'title new' not in out and 'title old' not in out


def test_a_listing_that_ends_before_the_window_is_partial(reddit):
    reddit.me().json('/r/example/new.json', listing([post('a', epoch('2026-10-01T00:00:00'))]), query={'limit': 100})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--since', '2026-01-01')
    assert code == 8 and 'ended before' in out and 'not covered' in out and 'title a' in out


def test_a_window_without_a_sort_reads_newest_first_and_says_so(reddit):
    reddit.me().json('/r/example/new.json', listing([post('a', epoch('2026-10-08T01:00:00')),
                                                     post('old', epoch('2026-10-01T00:00:00'))], after='t3_old'),
                     query={'limit': 100})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--since', '2026-10-05')
    assert code == 0 and 'sort=new (window)' in out.splitlines()[0] and 'stopped=window_reached' in out.splitlines()[0]
    assert 'title a' in out and 'title old' not in out
    assert reddit.paths()[-1] == '/r/example/new.json', 'the request itself is sort new'


def test_the_home_feed_and_a_search_with_a_window_read_as_new_too(reddit):
    old = post('old', epoch('2026-10-01T00:00:00'))
    reddit.me().json('/new.json', listing([post('a', epoch('2026-10-08T01:00:00')), old], after='t3_old'))
    code, out, _ = reddit.run('reddit', 'feed', '--since', '2026-10-05')
    assert code == 0 and 'feed · sort=new (window)' in out.splitlines()[0]
    reddit.me().json('/search.json', listing([post('b', epoch('2026-10-08T01:00:00')), old], after='t3_old'),
                     query={'sort': 'new'})
    code, out, _ = reddit.run('reddit', 'search', 'sync', '--since', '2026-10-05')
    assert code == 0 and 'sort=new (window)' in out.splitlines()[0]


def test_a_window_with_another_explicit_sort_is_still_refused(reddit):
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'top', '--since', '2026-10-01')
    assert code == 2 and '--time' in json.loads(out)['fix'] and reddit.fetches() == []
    code, out, _ = reddit.run('reddit', 'feed', '--sort', 'best', '--until', '2026-10-01')
    assert code == 2 and reddit.fetches() == []


def test_the_continuation_of_an_implied_window_keeps_it(reddit):
    reddit.me().json('/r/example/new.json', listing([post('a', epoch('2026-10-08T01:00:00'))], after='t3_a'),
                     query={'limit': 100})
    reddit.json('/r/example/new.json', listing([post('b', epoch('2026-10-07T01:00:00')),
                                                post('old', epoch('2026-10-01T00:00:00'))], after='t3_old'),
                query={'after': 't3_a'})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--since', '2026-10-05', '--limit', '1')
    words = more_words(out)
    assert code == 0 and '--sort' not in words and words[words.index('--since') + 1] == '2026-10-05'
    reddit.me()
    code, out, _ = reddit.run(*words)
    assert code == 0 and 'sort=new (window)' in out.splitlines()[0] and 'title b' in out and 'title old' not in out


def test_time_is_the_servers_period(reddit):
    reddit.me().json('/r/example/top.json', listing([post('a')]), query={'t': 'week'})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'top', '--time', 'week')
    assert code == 0 and 'time=week' in out.splitlines()[0]


def test_a_continuation_read_as_another_account_stops_before_sending(reddit):
    reddit.me().json('/r/example/new.json', listing([post('a')], after='t3_a'), query={'limit': 100})
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new', '--limit', '1')
    reddit.me('someone_else')
    code, out, _ = reddit.run(*more_words(out))
    envelope = json.loads(out)
    assert code == 4 and envelope['error'] == 'login' and VIEWER in envelope['message']
    assert reddit.paths()[-1] == '/api/me.json'


def test_the_home_feed_is_personal(reddit):
    reddit.me().json('/best.json', listing([post('a')], modhash=''))
    code, out, _ = reddit.run('reddit', 'feed')
    assert code == 4 and json.loads(out)['error'] == 'login'


def test_feed_reads_the_chosen_order(reddit):
    reddit.me().json('/new.json', listing([post('a')]), query={'limit': 100})
    code, out, _ = reddit.run('reddit', 'feed', '--sort', 'new')
    assert code == 0 and out.startswith('reddit feed · sort=new · 1 shown · stopped=exhausted')


def test_the_home_feed_is_endless_so_out_needs_a_limit_unless_it_is_a_timeline(reddit, tmp_path):
    code, out, _ = reddit.run('reddit', 'feed', '--out', tmp_path / 'f.ndjson')
    assert code == 2 and '--limit' in json.loads(out)['fix'] and reddit.fetches() == []
    code, out, _ = reddit.run('reddit', 'feed', '--sort', 'hot', '--out', tmp_path / 'f.ndjson')
    assert code == 2 and reddit.fetches() == []
    reddit.me().json('/new.json', listing([post('a')]))
    code, out, _ = reddit.run('reddit', 'feed', '--sort', 'new', '--out', tmp_path / 'g.ndjson')
    assert code == 0 and '1 saved to' in out


def test_a_private_community_is_unavailable(reddit):
    reddit.me().respond({'status': 403, 'body': {'reason': 'private'}}, path='/r/example/hot.json')
    code, out, _ = reddit.run('reddit', 'sub', 'r/example')
    envelope = json.loads(out)
    assert code == 9 and envelope['error'] == 'unavailable' and envelope['message'].endswith('(private).')


def test_an_empty_listing_is_exit_7(reddit):
    reddit.me().json('/r/example/new.json', listing([]))
    code, out, _ = reddit.run('reddit', 'sub', 'r/example', '--sort', 'new')
    assert code == 7 and json.loads(out)['error'] == 'empty'


def test_combinations_and_targets(reddit):
    reddit.me().json('/r/example+other/hot.json', listing([post('a')]))
    code, out, _ = reddit.run('reddit', 'sub', 'r/example+other')
    assert code == 0
    code, out, _ = reddit.run('reddit', 'sub', 'u/someone')
    assert code == 2 and 'r/<name>' in json.loads(out)['message']


def test_more_is_one_line_the_permission_rule_allows(reddit):
    reddit.me().json('/r/example/hot.json', listing([post(f'p{i}') for i in range(30)], after='t3_p29'))
    code, out, _ = reddit.run('reddit', 'sub', 'r/example')
    line = more_line(out)
    assert line.startswith('more: uv run "') and '/scripts/cli.py" reddit sub r/example --sort hot --after ' in line
