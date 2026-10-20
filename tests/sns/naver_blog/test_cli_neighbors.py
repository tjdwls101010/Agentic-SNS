"""feed and buddies through the real cli with a fake Aside: the neighbor feed page by page (deep pages are verified only
here, with synthetic pages), neighbor lists, groups and followers. These are the account's own surfaces, so each reading
asks who is logged in first (current-user, one request) and a continuation checks it again; the cached account is
only a hint and a login switched inside one Aside profile is a changed login."""
import json

import pytest

from tests.sns.naver_blog.scene import M, VIEWER, response
from tests.sns.naver_blog.shapes import buddies, buddy_page, feed_items, feed_page
from tests.sns.support.cli import command_of, more_line

FEED = f'/api/blogs/{VIEWER}/feed/v1'


def first_line(out):
    return out.splitlines()[0]


def test_feed_reads_the_accounts_neighbor_posts_and_pages_on(naver):
    naver.logged_in()
    naver.respond(M, FEED, json=feed_page(feed_items(20), 45), query={'groupId': 0, 'page': 1, 'itemCount': 20})
    naver.respond(M, FEED, json=feed_page(feed_items(20, 20), 45, 2), query={'page': 2})
    naver.respond(M, FEED, json=feed_page(feed_items(5, 40), 45, 3), query={'page': 3})
    code, out, _ = naver.run('naver-blog', 'feed', '--limit', '45')
    assert code == 0, out
    head = first_line(out)
    assert '45 shown' in head and 'stopped=exhausted' in head and 'requests=4' in head
    assert 'coverage: Naver Blog reports 45 in total' in out
    assert 'own-money' in out and 'url: https://blog.naver.com/friend1/224000000499' in out
    assert 'only the blogs this account follows' in out
    assert naver.paths()[0] == '/api/current-user'


def test_feed_continues_by_handle_and_checks_the_account_again(naver):
    naver.logged_in()
    naver.respond(M, FEED, json=feed_page(feed_items(20), 25), query={'page': 1})
    naver.respond(M, FEED, json=feed_page(feed_items(5, 20), 25, 2), query={'page': 2})
    code, out, _ = naver.run('naver-blog', 'feed')
    naver.logged_in()
    code, again, _ = naver.run(*command_of(more_line(out)))
    naver.logged_in()
    code, third, _ = naver.run(*command_of(more_line(again)))
    assert code == 0 and '5 shown' in first_line(third) and 'stopped=exhausted' in first_line(third)
    assert more_line(third) is None


def test_a_page_past_the_end_comes_without_items(naver):
    naver.logged_in()
    naver.respond(M, FEED, json=feed_page(feed_items(20), 20), query={'page': 1})
    naver.respond(M, FEED, json=response('feed_page-1'), query={'page': 2})
    code, out, _ = naver.run('naver-blog', 'feed', '--limit', '30')
    assert code == 0 and '20 shown' in first_line(out) and 'stopped=exhausted' in first_line(out)


def test_no_neighbor_posts_is_an_explicit_empty_result(naver):
    naver.logged_in()
    naver.respond(M, FEED, json=feed_page([], 0))
    code, out, _ = naver.run('naver-blog', 'feed')
    assert code == 7 and 'may follow no blog yet' in json.loads(out)['message']


def test_feed_always_asks_who_is_logged_in_first_even_with_a_warm_hint(naver):
    naver.hint()
    naver.logged_in()
    naver.respond(M, FEED, json=feed_page(feed_items(3), 3))
    code, out, _ = naver.run('naver-blog', 'feed')
    assert code == 0 and naver.paths() == ['/api/current-user', FEED]


def test_the_feed_is_read_for_the_account_the_browser_names_not_the_hint(naver):
    naver.hint(viewer='stale_blog')
    naver.logged_in()
    naver.respond(M, FEED, json=feed_page(feed_items(3), 3))
    code, out, _ = naver.run('naver-blog', 'feed')
    assert code == 0 and naver.paths()[1] == FEED


def test_feed_logged_out_is_exit_4(naver):
    naver.logged_in(loggedIn=False)
    code, out, _ = naver.run('naver-blog', 'feed')
    assert code == 4 and naver.paths() == ['/api/current-user']


def test_a_login_switched_inside_one_aside_profile_is_a_changed_login_not_a_silent_other_feed(naver):
    naver.logged_in()
    naver.respond(M, FEED, json=feed_page(feed_items(20), 25), query={'page': 1})
    code, out, _ = naver.run('naver-blog', 'feed')
    handle = command_of(more_line(out))
    naver.logged_in(userId='other_blog')   # same Aside profile, another Naver login
    code, again, _ = naver.run(*handle)
    envelope = json.loads(again)
    assert code == 4 and envelope['error'] == 'login' and 'other_blog' in envelope['message']
    assert naver.paths().count(FEED) == 1, 'nothing was read as the other account'


def test_an_out_file_read_as_another_account_is_refused(naver, tmp_path):
    out = tmp_path / 'feed.ndjson'
    naver.logged_in()
    naver.respond(M, FEED, json=feed_page(feed_items(20), 20), query={'page': 1})
    assert naver.run('naver-blog', 'feed', '--limit', '20', '--out', str(out))[0] == 0
    naver.logged_in(userId='other_blog')
    code, text, _ = naver.run('naver-blog', 'feed', '--limit', '30', '--out', str(out))
    assert code == 4 and json.loads(text)['error'] == 'login'


def test_my_neighbors(naver):
    naver.logged_in()
    naver.respond(M, f'/api/blogs/{VIEWER}/my-buddies', json=buddy_page(buddies(20), VIEWER, pages=2),
                  query={'pageNo': 1})
    code, out, _ = naver.run('naver-blog', 'buddies')
    assert code == 0 and '20 shown' in first_line(out) and 'mutual' in out and 'stopped=limit_reached' in first_line(out)
    assert '[b1] nb0' in out and 'kind=mine' in first_line(out)


def test_a_blogs_public_neighbors_and_the_private_default(naver):
    naver.respond(M, '/api/blogs/other/public-buddies', json=response('buddy_page-1'))
    code, out, _ = naver.run('naver-blog', 'buddies', 'other')
    assert code == 7 and 'private by default' in json.loads(out)['message']
    assert naver.paths() == ['/api/blogs/other/public-buddies'], 'a public list asks no account'


def test_followers_are_the_blogs_that_added_me(naver):
    naver.logged_in()
    naver.respond(M, f'/api/blogs/{VIEWER}/me-buddies', json=response('test_cli_new-134'))
    code, out, _ = naver.run('naver-blog', 'buddies', '--followers')
    assert code == 0 and 'kind=followers' in first_line(out) and '[b1] fan1' in out


def test_groups_list_and_one_group(naver):
    naver.logged_in()
    naver.respond(M, f'/api/blogs/{VIEWER}/buddy-groups', json=response('test_cli_new-142'))
    code, out, _ = naver.run('naver-blog', 'buddies', '--groups')
    assert code == 0 and '[g1] group 1 · 맛집 친구' in out and 'stopped=not_paginable' in out
    naver.logged_in()
    naver.respond(M, f'/api/blogs/{VIEWER}/my-buddies', json=response('test_cli_new-146'), query={'groupId': 3})
    code, out, _ = naver.run('naver-blog', 'buddies', '--group', '3')
    assert code == 0 and 'group=3' in first_line(out)


@pytest.mark.parametrize('args', [['other', '--followers'], ['--group', '1', '--groups'], ['other', '--group', '1'],
                                  ['--followers', '--group', '1'], ['--groups', '--out', 'g.ndjson'],
                                  ['--groups', '--after', '3']])
def test_buddy_list_kinds_are_one_at_a_time_and_mine_only(naver, args):
    code, out, _ = naver.run('naver-blog', 'buddies', *args)
    assert code == 2 and naver.fetches() == [] and json.loads(out).get('command') == 'buddies'


def test_the_feed_of_one_group(naver):
    naver.logged_in()
    naver.respond(M, FEED, json=response('test_cli_new-160'), query={'groupId': 3})
    code, out, _ = naver.run('naver-blog', 'feed', '--group', '3')
    assert code == 7 and 'group' in json.loads(out)['message'].lower()


def test_an_owner_only_surface_is_exit_9(naver):
    naver.logged_in()
    naver.respond(M, f'/api/blogs/{VIEWER}/my-buddies', status=403,
                  json={'isSuccess': False, 'error': {'code': 'not_blog_owner', 'message': 'x'}})
    code, out, _ = naver.run('naver-blog', 'buddies')
    assert code == 9
