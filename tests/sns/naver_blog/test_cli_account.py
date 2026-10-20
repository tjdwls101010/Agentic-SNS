"""When a Naver Blog reading asks who is logged in (current-user, one request): only a reading tied to the account —
an own surface, --out, a continuation, and a public read that goes on past one screen (it may run until the time limit,
and could not then afford the request that lets it leave a more: line). The cached account is a hint, never proof."""
import json

from tests.sns.naver_blog.scene import M, VIEWER
from tests.sns.naver_blog.shapes import blog_posts, post_items, post_list, search_page
from tests.sns.support.cli import command_of, more_line


def first_line(out):
    return out.splitlines()[0]


def test_a_public_read_of_one_screen_never_asks(naver):
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(3)))
    code, out, _ = naver.run('naver-blog', 'search', '카페')
    assert code == 0 and naver.paths() == ['/api/search/v1/post']


def test_a_public_read_that_goes_on_asks_first_even_with_a_warm_hint(naver):
    naver.hint()
    naver.logged_in()
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30)))
    code, out, _ = naver.run('naver-blog', 'search', '카페', '--limit', '25')
    assert code == 0 and '25 shown' in first_line(out) and naver.paths() == ['/api/current-user', '/api/search/v1/post']


def test_a_window_asks_first_too(naver):
    naver.logged_in()
    naver.respond(M, '/api/blogs/cafe_note/post-list', json=post_list(blog_posts(3)))
    code, out, _ = naver.run('naver-blog', 'posts', 'cafe_note', '--since', '2026-10-01')
    assert code == 0 and naver.paths()[0] == '/api/current-user'


def test_a_long_read_that_meets_the_time_limit_still_leaves_its_more_line_with_a_cold_hint(naver):
    """The old order was: read until the budget is gone, then ask who is logged in to save the handle. With no budget
    the time limit ends the read, so the account is known before the first page."""
    naver.logged_in()
    for page in range(1, 31):
        naver.respond(M, '/api/blogs/cafe_note/post-list', json=post_list(blog_posts(30 if page < 30 else 5, start=30 * (page - 1))),
                      query={'page': page})
    code, out, _ = naver.run('naver-blog', 'posts', 'cafe_note', '--limit', '5000', '--json',
                             env={'SNS_DEADLINE_SECONDS': '10'})
    first = json.loads(out)
    assert code == 0 and first['stop_reason'] == 'time_limit' and 30 < len(first['results']) < 900
    assert first['next'] and naver.paths()[0] == '/api/current-user'
    naver.monkeypatch.delenv('SNS_DEADLINE_SECONDS')   # the pacing the first run left is still owed in the second
    naver.logged_in()
    code, out, _ = naver.run(*command_of('more: ' + first['next']), '--json')
    second = json.loads(out)
    assert code == 0 and second['results'][0]['id'] != first['results'][0]['id']
    assert len({r['id'] for r in first['results'] + second['results']}) == len(first['results']) + len(second['results'])


def test_a_handle_stamped_with_a_hint_is_checked_on_continuing(naver):
    naver.hint(viewer=VIEWER)
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30)))
    _, out, _ = naver.run('naver-blog', 'search', '카페')
    naver.logged_in(userId='someone_else')
    code, again, _ = naver.run(*command_of(more_line(out)))
    assert code == 4 and json.loads(again)['error'] == 'login'
