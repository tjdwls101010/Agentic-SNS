"""blog and posts through the real cli with a fake Aside: the card with its counts, the category tree, notices and
popular posts; one blog's lists by category, window and shelf."""
import json

import pytest

from tests.sns.naver_blog.scene import M, response
from tests.sns.naver_blog.shapes import blog_posts, post_list
from tests.sns.support.cli import command_of, more_line

CARD, COUNTS, CATEGORIES = response('test_cli_blog-28'), response('test_cli_blog-29'), response('test_cli_blog-30')


def first_line(out):
    return out.splitlines()[0]


def answer_card(naver):
    naver.respond(M, '/api/blogs/cafe_note', json=CARD)
    naver.respond(M, '/api/blogs/cafe_note/contents-count', json=COUNTS)
    naver.respond(M, '/api/blogs/cafe_note/category-list', json=CATEGORIES)


def test_blog_reads_the_card_counts_categories_notices_and_popular(naver):
    answer_card(naver)
    naver.respond(M, '/api/blogs/cafe_note/notice-post-list', json=response('test_cli_blog-35'))
    naver.respond(M, '/api/blogs/cafe_note/popular-post-list', json={'isSuccess': True, 'result': {
        'popularPostList': blog_posts(2, viewCount=384)}})
    code, out, _ = naver.run('naver-blog', 'blog', 'https://blog.naver.com/cafe_note')
    assert code == 0, out
    assert 'requests=5' in first_line(out) and 'blog=cafe_note' in first_line(out)
    assert 'neighbors=1520' in out and 'posts=712' in out and 'clips=4' in out and 'mutual-neighbor' in out
    assert '[1] 맛집 · 80 posts' in out and '    [3] 성수 · 20 posts' in out and 'closed' in out
    assert 'notices: none' in out and 'views=384' in out


def test_the_card_notes_that_a_public_neighbor_list_is_private_by_default(naver):
    answer_card(naver)
    naver.respond(M, '/api/blogs/cafe_note/notice-post-list', json=response('test_cli_blog-35'))
    naver.respond(M, '/api/blogs/cafe_note/popular-post-list', json=response('test_cli_blog-36'))
    code, out, _ = naver.run('naver-blog', 'blog', 'cafe_note')
    assert code == 0 and 'private by default' in out


def test_blog_brief_is_three_requests(naver):
    answer_card(naver)
    code, out, _ = naver.run('naver-blog', 'blog', 'cafe_note', '--brief')
    assert code == 0 and 'requests=3' in first_line(out) and 'popular' not in out


def test_a_failed_section_is_shown_and_the_command_is_partial(naver):
    answer_card(naver)
    naver.respond(M, '/api/blogs/cafe_note/notice-post-list', status=502, body='')
    naver.respond(M, '/api/blogs/cafe_note/popular-post-list', json=response('test_cli_blog-36'))
    code, out, _ = naver.run('naver-blog', 'blog', 'cafe_note')
    assert code == 8 and 'notices: unavailable' in out and 'popular:' in out and 'coverage: incomplete' in out


def test_a_missing_blog_is_exit_9(naver):
    naver.respond(M, '/api/blogs/nosuch', json=response('test_cli_blog-53'))
    naver.respond('blog.naver.com', '/nosuch', status=404, body='<html></html>', content_type='text/html')
    code, out, _ = naver.run('naver-blog', 'blog', 'nosuch')
    assert code == 9 and json.loads(out)['error'] == 'unavailable'


def test_posts_list_newest_first_and_continue(naver):
    naver.hint()
    naver.respond(M, '/api/blogs/cafe_note/post-list', json=response('test_cli_blog-61'),
                  query={'categoryNo': 0, 'page': 1})
    code, out, _ = naver.run('naver-blog', 'posts', 'cafe_note')
    assert code == 0, out
    assert '10 shown' in first_line(out) and 'stopped=limit_reached' in first_line(out)
    assert 'reports' not in out, 'post-list\'s totalCount 0 is false and not shown'
    naver.logged_in()
    code, again, _ = naver.run(*command_of(more_line(out)))
    assert code == 0 and '10 shown' in first_line(again)
    assert naver.paths() == ['/api/blogs/cafe_note/post-list', '/api/current-user']


def test_posts_by_category_name_costs_one_lookup(naver):
    naver.respond(M, '/api/blogs/cafe_note/category-list', json=CATEGORIES)
    naver.respond(M, '/api/blogs/cafe_note/post-list', json=post_list(blog_posts(3)), query={'categoryNo': 3})
    code, out, _ = naver.run('naver-blog', 'posts', 'cafe_note', '--category', '성수')
    assert code == 0 and 'category=성수' in first_line(out) and 'requests=2' in first_line(out)
    assert 'coverage: category 성수 is number 3' in out


@pytest.mark.parametrize('name,code', [('서울', 0), ('맛', 2), ('여행', 9)])
def test_category_names_match_exactly_first_then_by_part(naver, name, code):
    naver.respond(M, '/api/blogs/cafe_note/category-list', json=response('test_cli_blog-79'))
    naver.respond(M, '/api/blogs/cafe_note/post-list', json=post_list(blog_posts(1)))
    got, out, _ = naver.run('naver-blog', 'posts', 'cafe_note', '--category', name)
    assert got == code, out
    if code == 2:
        assert '(1)' in json.loads(out)['fix'] and '(4)' in json.loads(out)['fix']


def test_a_window_closes_on_the_newest_first_list(naver):
    naver.logged_in()   # a window goes on until it closes: the account is known first
    naver.respond(M, '/api/blogs/cafe_note/post-list', json=post_list(blog_posts(30)), query={'page': 1})
    naver.respond(M, '/api/blogs/cafe_note/post-list', json=post_list(blog_posts(30, start=30)), query={'page': 2})
    code, out, _ = naver.run('naver-blog', 'posts', 'cafe_note', '--since', '2026-09-15')
    assert code == 0, out
    assert 'stopped=window_reached' in first_line(out) and '35 shown' in first_line(out)
    assert 'requests=3' in first_line(out) and 'closed (as served)' in out.splitlines()[1]


def test_a_window_closes_as_soon_as_a_page_shows_a_post_older_than_its_start(naver):
    naver.logged_in()   # a window goes on until it closes: the account is known first
    naver.respond(M, '/api/blogs/cafe_note/post-list', json=post_list(blog_posts(30)), query={'page': 1})
    code, out, _ = naver.run('naver-blog', 'posts', 'cafe_note', '--since', '2026-10-15')
    assert code == 0, out
    assert 'stopped=window_reached' in first_line(out) and '5 shown' in first_line(out)
    assert naver.paths() == ['/api/current-user', '/api/blogs/cafe_note/post-list']


def test_a_blog_whose_posts_all_fall_inside_the_window_is_read_to_its_end(naver):
    naver.logged_in()   # a window goes on until it closes: the account is known first
    naver.respond(M, '/api/blogs/cafe_note/post-list', json=post_list(blog_posts(3)))
    code, out, _ = naver.run('naver-blog', 'posts', 'cafe_note', '--since', '2026-10-01')
    assert code == 0 and '3 shown' in first_line(out) and 'stopped=exhausted' in first_line(out)
    assert 'closed (read to the end)' in out.splitlines()[1]


def test_popular_is_one_page_with_view_counts(naver):
    naver.respond(M, '/api/blogs/cafe_note/popular-post-list', json={'isSuccess': True, 'result': {
        'popularPostList': blog_posts(3, viewCount=10)}})
    code, out, _ = naver.run('naver-blog', 'posts', 'cafe_note', '--popular')
    assert code == 0 and 'shelf=popular' in first_line(out) and 'stopped=not_paginable' in out and 'views=10' in out
    assert more_line(out) is None


def test_empty_notices_are_exit_7_and_say_so(naver):
    naver.respond(M, '/api/blogs/cafe_note/notice-post-list', json=response('test_cli_blog-35'))
    code, out, _ = naver.run('naver-blog', 'posts', 'cafe_note', '--notices')
    assert code == 7 and 'no notices posts' in json.loads(out)['message']


@pytest.mark.parametrize('args', [['--popular', '--since', '2026-10-01'], ['--notices', '--out', 'f.ndjson'],
                                  ['--popular', '--notices'], ['--popular', '--after', '3'],
                                  ['--category', '1', '--popular']])
def test_shelves_are_one_page_and_refuse_windows_files_and_handles(naver, args):
    code, out, _ = naver.run('naver-blog', 'posts', 'cafe_note', *args)
    assert code == 2 and json.loads(out).get('command') == 'posts' and naver.fetches() == []


def test_a_url_that_names_a_category_refuses_another(naver):
    code, out, _ = naver.run('naver-blog', 'posts', 'https://blog.naver.com/PostList.naver?blogId=cafe_note&categoryNo=3',
                             '--category', '4')
    assert code == 2 and naver.fetches() == []


def test_a_url_that_names_a_category_reads_it(naver):
    naver.respond(M, '/api/blogs/cafe_note/post-list', json=post_list(blog_posts(2)), query={'categoryNo': 3})
    code, out, _ = naver.run('naver-blog', 'posts', 'https://blog.naver.com/PostList.naver?blogId=cafe_note&categoryNo=3')
    assert code == 0 and '2 shown' in first_line(out) and naver.paths() == ['/api/blogs/cafe_note/post-list']
