"""search through the real cli with a fake Aside: every type and its argument rules, one blog's own search, continuation
(and when it needs the account), windows, restrictions."""
import json

import pytest

from tests.sns.naver_blog.scene import M, VIEWER, response
from tests.sns.naver_blog.shapes import DAY0, post_items, search_page
from tests.sns.support.cli import command_of, more_line


def first_line(out):
    return out.splitlines()[0]


def test_post_search_shows_ten_of_a_page_and_offers_more_without_a_listing_request(naver):
    naver.hint()
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30)),
                  query={'keyword': '성수 카페 후기', 'sortType': 'sim', 'page': 1, 'itemCount': 30})
    code, out, _ = naver.run('naver-blog', 'search', '성수', '카페', '후기')
    assert code == 0, out
    head = first_line(out)
    assert head.startswith('naver-blog search · type=posts · sort=sim · 10 shown · stopped=limit_reached · requests=1')
    assert 'coverage: Naver Blog reports 7749 in total' in out
    assert out.count('excerpt (Naver\'s, cut by length)') == 10 and 'url: https://blog.naver.com/blog_a1/224000000001' in out
    assert naver.paths() == ['/api/search/v1/post'], 'a warm hint stamps the handle without asking who is logged in'
    naver.logged_in()  # a continued reading checks the account it was read with
    code, again, _ = naver.run(*command_of(more_line(out)))
    assert code == 0 and '10 shown' in first_line(again) and '224000000011' in again
    assert naver.paths() == ['/api/search/v1/post', '/api/current-user'], 'the waiting records cost no listing'


def test_a_handle_from_another_query_is_refused(naver):
    naver.hint()
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30)))
    _, out, _ = naver.run('naver-blog', 'search', '성수')
    handle = command_of(more_line(out))[-1]
    code, out, _ = naver.run('naver-blog', 'search', '연남', '--after', handle)
    assert code == 2 and json.loads(out)['error'] == 'argument'


def test_dated_post_search_is_filtered_by_naver_and_ends_by_itself(naver):
    naver.logged_in()   # a window goes on until it closes: the account is known first
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(3)),
                  query={'sortType': 'date', 'startDate': '2026-10-01', 'endDate': '2026-10-19',
                         'isBuyWithMyOwnMoney': 'true'})
    code, out, _ = naver.run('naver-blog', 'search', '내돈내산', '--sort', 'date', '--since', '2026-10-01', '--until',
                             '2026-10-19', '--own-money')
    assert code == 0, out
    assert 'requests=2' in first_line(out) and 'stopped=exhausted' in first_line(out)   # the account, then the page
    assert 'window 2026-10-01..2026-10-19 KST' in out.splitlines()[1]


def test_blog_search_uses_v2_and_takes_only_an_order(naver):
    blogs = [{'blogId': f'b{i}', 'domainIdOrBlogId': f'b{i}', 'blogNo': i, 'blogName': f'블로그 {i}', 'nickname': f'n{i}',
              'blogStatus': '최근 게시물 2건', 'relationType': None} for i in range(3)]
    naver.respond(M, '/api/search/v2/blog', json=search_page(blogs, total=3, totalPage=1),
                  query={'keyword': '카페', 'sortType': 'date', 'page': 1})
    code, out, _ = naver.run('naver-blog', 'search', '카페', '--type', 'blogs', '--sort', 'date')
    assert code == 0, out
    assert '[b1] b0' in out and 'url: https://blog.naver.com/b0' in out and 'stopped=exhausted' in first_line(out)


@pytest.mark.parametrize('args', [['--type', 'blogs', '--since', '2026-10-01'], ['--type', 'blogs', '--own-money'],
                                  ['--type', 'tags', '--sort', 'date'], ['--type', 'tags', '--own-money'],
                                  ['--blog', 'b', '--type', 'tags', '--sort', 'date'],
                                  ['--blog', 'b', '--type', 'tags', '--since', '2026-10-01'],
                                  ['--blog', 'b', '--own-money'], ['--blog', 'b', '--type', 'blogs'],
                                  ['--out', 'f.ndjson', '--after', '3'], ['--since', '2026-10-15', '--until', '2026-10-10']])
def test_combinations_a_surface_cannot_honour_are_refused_before_any_request(naver, args):
    code, out, _ = naver.run('naver-blog', 'search', '카페', *args)
    envelope = json.loads(out)
    assert code == 2 and envelope['error'] == 'argument' and naver.fetches() == []
    assert envelope.get('command') == 'search', envelope   # refused by search's own rules, not as an unknown command


@pytest.mark.parametrize('args', [['--limit', '0'], ['--type', 'videos'], ['--since', '2026/10/15']])
def test_malformed_options_are_refused_before_any_request(naver, args):
    code, out, _ = naver.run('naver-blog', 'search', '카페', *args)
    assert code == 2 and json.loads(out)['error'] == 'argument' and naver.fetches() == []


def test_empty_search_text_is_refused(naver):
    code, out, _ = naver.run('naver-blog', 'search', ' ')
    assert code == 2 and naver.fetches() == []


def test_tag_search_is_newest_first_so_a_window_closes_on_it(naver):
    naver.logged_in()   # a window goes on until it closes: the account is known first
    items = [{'blogId': 'tb', 'logNo': 100 + i, 'title': f't{i}', 'content': 'c', 'addDate': DAY0 - i * 86400000}
             for i in range(30)]
    older = [{'blogId': 'tb', 'logNo': 200 + i, 'title': 'old', 'content': 'c', 'addDate': 1780000000000 - i} for i in range(30)]
    naver.respond(M, '/api/tags/search/post', json={'isSuccess': True, 'result': {'page': 1, 'totalCount': 9, 'items': items}},
                  query={'query': '성수카페', 'page': 1})
    naver.respond(M, '/api/tags/search/post', json={'isSuccess': True, 'result': {'page': 2, 'totalCount': 9, 'items': older}},
                  query={'query': '성수카페', 'page': 2})
    code, out, _ = naver.run('naver-blog', 'search', '성수카페', '--type', 'tags', '--since', '2026-10-15')
    assert code == 0, out
    assert 'stopped=window_reached' in first_line(out) and '5 shown' in first_line(out)
    assert 'tag search sends no blog name' in out
    assert 'closed (as served)' in out.splitlines()[1]


def test_one_blogs_own_search(naver):
    items = [{'blogId': 'own', 'logNo': 1 + i, 'title': f'안 {i}', 'contents': 'c', 'addDate': DAY0} for i in range(4)]
    naver.respond(M, '/api/blogs/own/search/post', json={'isSuccess': True, 'result': {'totalCount': 4, 'totalPage': 1, 'list': items}},
                  query={'query': '맛집', 'sortType': 'sim', 'page': 1})
    code, out, _ = naver.run('naver-blog', 'search', '맛집', '--blog', 'https://blog.naver.com/own')
    assert code == 0, out
    assert 'blog=own' in first_line(out) and '4 shown' in first_line(out)


def test_one_blogs_tag_search(naver):
    items = [{'blogId': 'own', 'logNo': 9, 'title': '태그 글', 'contents': 'c', 'addDate': DAY0}]
    naver.respond(M, '/api/blogs/own/search/tag', json={'isSuccess': True, 'result': {'totalCount': 1, 'totalPage': 1, 'list': items}},
                  query={'query': '대구술집', 'page': 1})
    code, out, _ = naver.run('naver-blog', 'search', '대구술집', '--blog', 'own', '--type', 'tags')
    assert code == 0 and '1 shown' in first_line(out)


def test_clip_search_names_each_clips_permalink(naver):
    naver.logged_in()   # a window goes on until it closes: the account is known first
    from tests.sns.naver_blog.shapes import clip_items
    naver.respond(M, '/api/search/v1/moment', json=search_page(clip_items(3), total=3, totalPage=1),
                  query={'keyword': '성수', 'sortType': 'date', 'startDate': '2026-10-01'})
    code, out, _ = naver.run('naver-blog', 'search', '성수', '--type', 'clips', '--sort', 'date', '--since', '2026-10-01')
    assert code == 0, out
    assert '[v1] clipper/clip/1600' in out and '23s' in out and 'url: https://m.blog.naver.com/clipper/clip/1600' in out


def test_clip_search_refuses_the_own_money_flag(naver):
    code, out, _ = naver.run('naver-blog', 'search', '성수', '--type', 'clips', '--own-money')
    assert code == 2 and naver.fetches() == []


def test_a_domain_address_is_resolved_once(naver):
    naver.respond(M, '/api/blogs/mydomain/search/post', json={'isSuccess': False, 'error': {'code': 'not_exist_blog', 'message': 'x'}})
    naver.respond('blog.naver.com', '/mydomain', body="<script>var blogId = 'real_id';</script>", content_type='text/html')
    naver.respond(M, '/api/blogs/real_id/search/post', json={'isSuccess': True, 'result': {'totalCount': 0, 'totalPage': 0, 'list': []}})
    code, out, _ = naver.run('naver-blog', 'search', '맛집', '--blog', 'mydomain')
    assert code == 7 and naver.paths() == ['/api/blogs/mydomain/search/post', '/mydomain', '/api/blogs/real_id/search/post']


def test_a_restricted_query_keeps_what_arrived(naver):
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(2), isBlockedByBifrostShield=True))
    code, out, _ = naver.run('naver-blog', 'search', '민감어')
    assert code == 8 and '2 shown' in first_line(out) and 'stopped=query_restricted' in first_line(out)
    assert 'coverage: incomplete' in out and 'more:' not in out


def test_a_restricted_query_with_nothing_is_still_not_an_empty_one(naver):
    naver.respond(M, '/api/search/v1/post', json=search_page([], queryControlInfo={'isForbidden': True}))
    code, out, _ = naver.run('naver-blog', 'search', '금칙어')
    assert code == 8 and json.loads(out)['stop_reason'] == 'query_restricted'


def test_an_explicit_empty_result_is_exit_7(naver):
    naver.respond(M, '/api/search/v1/post', json=response('search_page-1'))
    code, out, _ = naver.run('naver-blog', 'search', 'zzzz없는말')
    assert code == 7 and json.loads(out)['error'] == 'empty'


@pytest.mark.parametrize('limit,shown,asked', [('3', 3, False), ('10', 10, False), ('11', 11, True), ('30', 30, True)])
def test_a_limit_reads_on_from_the_same_page_without_another_listing_request(naver, limit, shown, asked):
    naver.hint()
    naver.logged_in()
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30)))
    code, out, _ = naver.run('naver-blog', 'search', '카페', '--limit', limit)
    assert code == 0 and f'{shown} shown' in first_line(out)
    assert naver.paths() == (['/api/current-user'] if asked else []) + ['/api/search/v1/post']


def test_a_cold_hint_costs_one_current_user_request_only_to_stamp_the_handle(naver):
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30)))
    naver.logged_in()
    code, out, _ = naver.run('naver-blog', 'search', '카페')
    assert code == 0 and naver.paths() == ['/api/search/v1/post', '/api/current-user']
    assert 'requests=2' in first_line(out) and more_line(out)


def test_a_search_that_needs_no_handle_never_asks_who_is_logged_in(naver):
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(3)))
    code, out, _ = naver.run('naver-blog', 'search', '카페')
    assert code == 0 and naver.paths() == ['/api/search/v1/post'] and more_line(out) is None


def test_a_stale_hint_is_never_proof_of_who_is_logged_in(naver):
    """The handle is stamped with the hint (viewer_blog); the browser has since switched to another login: continuing
    asks, and the switch is a changed login (exit 4), not a silent read as the other account."""
    naver.hint(viewer=VIEWER)
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30)))
    _, out, _ = naver.run('naver-blog', 'search', '카페')
    naver.logged_in(userId='other_blog')
    code, again, _ = naver.run(*command_of(more_line(out)))
    envelope = json.loads(again)
    assert code == 4 and envelope['error'] == 'login' and 'other_blog' in envelope['message']


def test_chars_clips_each_excerpt_and_zero_shows_what_was_received(naver):
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(2, content='가' * 400)))
    code, out, _ = naver.run('naver-blog', 'search', '카페')
    assert code == 0 and '가' * 180 + '…' in out and '가' * 181 not in out
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(2, content='가' * 400)))
    code, out, _ = naver.run('naver-blog', 'search', '카페', '--chars', '0')
    assert '가' * 400 in out and '…' not in out
