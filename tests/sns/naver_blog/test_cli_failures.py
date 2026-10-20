"""How a reading ends when Naver pushes back or changes, through the real cli: a 429 is a hold that passes by itself (exit 5
before records, a stop where more: resumes after), a login wall is exit 4 and records no block, the time limit ends a
reading that more: resumes, Naver's own ceiling is a natural end, and a composite command exits with its worst section."""
import json
import time

import pytest

from tests.sns.naver_blog.scene import ACCOUNT, M, response
from tests.sns.naver_blog.shapes import post_items, post_list, search_page
from tests.sns.support.cli import command_of, more_line


def first_line(out):
    return out.splitlines()[0]


def test_a_429_before_any_record_is_exit_5_naming_when_it_passes(naver, data_dir):
    naver.respond(M, '/api/search/v1/post', status=429, body='')
    code, out, _ = naver.run('naver-blog', 'search', '카페', '--json')
    envelope = json.loads(out)
    assert code == 5 and envelope['error'] == 'blocked' and envelope['limit']['scope'] is None
    assert 1700 < envelope['limit']['reset'] - time.time() < 1815 and 'doctor --unblock does not lift' in envelope['fix']


def test_a_429_after_records_keeps_them_and_stops_where_more_resumes(naver, data_dir):
    naver.logged_in()
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30)), query={'page': 1})
    naver.respond(M, '/api/search/v1/post', status=429, body='', query={'page': 2})
    code, out, _ = naver.run('naver-blog', 'search', '카페', '--limit', '40')
    assert code == 0 and '30 shown' in first_line(out) and 'stopped=rate_limited' in first_line(out)
    assert more_line(out) and 'limit' in first_line(out)
    sent = len(naver.fetches())
    code, again, _ = naver.run(*command_of(more_line(out)))
    assert code == 5 and len(naver.fetches()) == sent, 'nothing is sent while the hold stands'


def test_more_goes_on_once_the_hold_has_passed(naver, data_dir):
    naver.logged_in()
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30)), query={'page': 1})
    naver.respond(M, '/api/search/v1/post', status=429, body='', query={'page': 2})
    code, out, _ = naver.run('naver-blog', 'search', '카페', '--limit', '40')
    path = data_dir / 'naver_blog' / ACCOUNT / 'protection' / 'blocks.json'
    blocks = json.loads(path.read_text())
    blocks['hold']['until'] = time.time() - 5
    path.write_text(json.dumps(blocks))
    naver.logged_in()
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(10, 31)), query={'page': 2})
    code, again, _ = naver.run(*command_of(more_line(out)))
    assert code == 0 and '10 shown' in first_line(again) and 'stopped=exhausted' in first_line(again)


def test_a_login_hop_is_exit_4_and_records_no_block(naver, data_dir):
    naver.respond(M, '/api/search/v1/post', status=302, location='https://nid.naver.com/nidlogin.login', body='')
    code, out, _ = naver.run('naver-blog', 'search', '카페')
    assert code == 4
    blocks = data_dir / 'naver_blog' / ACCOUNT / 'protection' / 'blocks.json'
    assert not blocks.exists() or json.loads(blocks.read_text()) == {'person': None, 'hold': None}


def test_the_time_limit_before_any_record_is_exit_6(naver):
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30)))
    code, out, _ = naver.run('naver-blog', 'search', '카페', '--json', env={'SNS_DEADLINE_SECONDS': '2'})
    envelope = json.loads(out)
    assert code == 6 and envelope['stop_reason'] == 'time_limit' and naver.fetches() == []


def test_a_changed_response_before_records_is_6(naver):
    naver.respond(M, '/api/search/v1/post', json={'isSuccess': True, 'result': {'items': []}})
    code, out, _ = naver.run('naver-blog', 'search', '카페')
    assert code == 6 and json.loads(out)['error'] == 'failed'


def test_a_changed_response_after_records_is_8_and_more_continues(naver):
    naver.logged_in()
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30)), query={'page': 1})
    naver.respond(M, '/api/search/v1/post', json={'isSuccess': True, 'result': {}}, query={'page': 2})
    code, out, _ = naver.run('naver-blog', 'search', '카페', '--limit', '40')
    assert code == 8 and 'coverage: incomplete' in out and 'more: ' in out and '30 shown' in first_line(out)


def test_naver_serving_no_more_than_a_thousand_is_a_natural_end_not_a_failure(naver):
    """server_capped was exit 8 in the old skill: the platform's own ceiling is where the listing ends, so it is exit 0
    with a coverage line saying why."""
    naver.logged_in()
    for page in range(1, 35):
        count = 30 if page < 34 else 10
        naver.respond(M, '/api/search/v1/post', json=search_page(post_items(count, 30 * (page - 1) + 1)),
                      query={'page': page})
    code, out, _ = naver.run('naver-blog', 'search', '카페', '--limit', '995')
    assert code == 0 and '995 shown' in first_line(out) and 'stopped=limit_reached' in first_line(out)
    naver.logged_in()
    code, again, _ = naver.run(*command_of(more_line(out)))
    assert code == 0 and '5 shown' in first_line(again) and 'stopped=server_capped' in first_line(again)
    assert more_line(again) is None and naver.paths().count('/api/search/v1/post') == 34


def test_a_composite_command_exits_with_its_worst_failed_section(naver):
    """blog: the card is the command; when the other sections fail too, the one that says most about the account or the
    target is the exit (the shared ranking: login, then an unreadable target, then the rest)."""
    naver.respond(M, '/api/blogs/cafe_note', json=response('test_cli_blog-28'))
    naver.respond(M, '/api/blogs/cafe_note/contents-count', status=502, body='')
    naver.respond(M, '/api/blogs/cafe_note/category-list', status=403,
                  json={'isSuccess': False, 'error': {'code': 'not_blog_owner', 'message': 'x'}})
    naver.respond(M, '/api/blogs/cafe_note/notice-post-list', json=response('test_cli_blog-35'))
    naver.respond(M, '/api/blogs/cafe_note/popular-post-list', json=response('test_cli_blog-36'))
    code, out, _ = naver.run('naver-blog', 'blog', 'cafe_note')
    assert code == 9 and 'counts: unavailable' in out and 'categories: unavailable' in out and 'popular:' in out


@pytest.mark.parametrize('failing,code', [(['counts'], 8), (['counts', 'notices'], 8)])
def test_a_secondary_section_failing_leaves_the_rest_and_is_partial(naver, failing, code):
    naver.respond(M, '/api/blogs/cafe_note', json=response('test_cli_blog-28'))
    for name, path in (('counts', 'contents-count'), ('categories', 'category-list'), ('notices', 'notice-post-list'),
                       ('popular', 'popular-post-list')):
        if name in failing:
            naver.respond(M, f'/api/blogs/cafe_note/{path}', status=502, body='')
        else:
            naver.respond(M, f'/api/blogs/cafe_note/{path}', json={
                'counts': response('test_cli_blog-29'), 'categories': response('test_cli_blog-30'),
                'notices': response('test_cli_blog-35'), 'popular': response('test_cli_blog-36')}[name])
    got, out, _ = naver.run('naver-blog', 'blog', 'cafe_note')
    assert got == code and '[b1] cafe_note' in out


def test_the_login_wall_in_a_section_outranks_a_failure_beside_it(naver):
    naver.respond(M, '/api/blogs/cafe_note', json=response('test_cli_blog-28'))
    naver.respond(M, '/api/blogs/cafe_note/contents-count', status=502, body='')
    naver.respond(M, '/api/blogs/cafe_note/category-list', status=302, location='https://nid.naver.com/nidlogin.login',
                  body='')
    naver.respond(M, '/api/blogs/cafe_note/notice-post-list', json=response('test_cli_blog-35'))
    naver.respond(M, '/api/blogs/cafe_note/popular-post-list', json=response('test_cli_blog-36'))
    code, out, _ = naver.run('naver-blog', 'blog', 'cafe_note')
    assert code == 4


def test_a_blogs_posts_that_end_are_exit_7_when_there_are_none(naver):
    naver.respond(M, '/api/blogs/cafe_note/post-list', json=post_list([]))
    code, out, _ = naver.run('naver-blog', 'posts', 'cafe_note')
    assert code == 7


def test_a_failed_windowed_read_still_states_its_window(naver):
    naver.logged_in(loggedIn=False)
    code, out, _ = naver.run('naver-blog', 'feed', '--since', '2026-10-01', '--json')
    envelope = json.loads(out)
    assert code == 4 and envelope['window']['since'] == '2026-10-01' and envelope['window']['until'] is None


def test_items_whose_shape_changed_are_a_changed_answer_not_an_empty_page(naver):
    items = [{'noLogNoHere': i, 'title': 't'} for i in range(30)]
    naver.respond(M, '/api/search/v1/post', json=search_page(items))
    code, out, _ = naver.run('naver-blog', 'search', '카페')
    envelope = json.loads(out)
    assert code == 6 and envelope['error'] == 'failed' and 'changed its answer' in envelope['message']
