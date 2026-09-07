"""Where a listing stops, told apart from three things that look identical inside one page."""
import pytest

from naver_blog_skill._api import operation
from naver_blog_skill._errors import NaverBlogError
from naver_blog_skill._listing import collect, kst_day
from naver_blog_skill._walk import Page


def post(number, created_at=None):
    return {'id': f'post:testblog/{number}', 'created_at': created_at}


def pages(*sizes, start=1, total=None, dated=None):
    """Build a fetch() that serves pages of the given raw sizes."""
    counter = {'n': 0}

    def fetch(page):
        size = sizes[page - start] if page - start < len(sizes) else 0
        items = [post(9990000000 + counter['n'] + index,
                      dated[page - start][index] if dated else None) for index in range(size)]
        counter['n'] += size
        return Page(items=items, raw_count=size, reported_total=total)
    return fetch


SEARCH = operation('search_posts')
POSTS = operation('post_list')


def test_a_short_page_far_from_the_ceiling_is_real_exhaustion():
    result = collect(SEARCH, pages(30, 12), limit=100)
    assert result['stop_reason'] == 'exhausted' and len(result['results']) == 42 and result['code'] == 0


def test_the_thousand_item_ceiling_is_reported_as_a_ceiling_not_as_the_end():
    # 33 full pages reach 990, page 34 returns 10 and stops at exactly 1,000.
    result = collect(SEARCH, pages(*([30] * 33), 10), limit=2000)
    assert result['stop_reason'] == 'server_capped' and result['code'] == 8


def test_an_empty_page_at_the_ceiling_is_the_ceiling_even_before_a_thousand():
    # Tag search went empty at position 990 while still reporting 151,093 results.
    tags = operation('search_tags')
    result = collect(tags, pages(*([30] * 33), 0, total=151093), limit=2000)
    assert result['stop_reason'] == 'server_capped'


def test_a_page_past_the_ceiling_reporting_zero_is_never_an_honest_empty_result():
    result = collect(SEARCH, pages(*([30] * 33), 10, 0, total=0), limit=2000)
    assert result['stop_reason'] == 'server_capped' and result['code'] == 8
    assert len(result['results']) == 1000


def test_a_post_list_ends_on_its_raw_page_length_because_its_total_is_always_zero():
    result = collect(POSTS, pages(30, 30, 7, total=0), limit=100)
    assert result['stop_reason'] == 'exhausted' and len(result['results']) == 67


def test_display_filtering_never_decides_the_end_of_a_listing():
    """A page of 30 that the window trims to 2 is still a full page: the walk continues."""
    dated = [['2026-09-05T00:00+09:00'] * 2 + ['2026-08-01T00:00+09:00'] * 28, ['2026-09-04T00:00+09:00'] * 5]
    result = collect(POSTS, pages(30, 5, dated=dated), limit=100, since='2026-09-01')
    assert result['stop_reason'] == 'exhausted'
    assert len(result['results']) == 7


def test_a_repeated_page_stops_as_a_stall_rather_than_as_exhaustion():
    def fetch(page):
        return Page(items=[post(9990000001), post(9990000002)], raw_count=30)
    result = collect(POSTS, fetch, limit=100)
    assert result['stop_reason'] == 'pagination_stalled' and result['code'] == 8


def test_a_marked_surface_trusts_its_marker_over_a_short_page():
    buddies = operation('public_buddies')

    def fetch(page):
        # Page one is short but the marker says there are two pages, and the marker wins.
        return Page(items=[post(9990000000 + page)], raw_count=1, total_pages=2,
                    next_page=2 if page == 1 else None)
    result = collect(buddies, fetch, limit=100)
    assert result['stop_reason'] == 'exhausted' and len(result['results']) == 2


def test_a_single_page_surface_says_so_rather_than_claiming_exhaustion():
    result = collect(operation('popular_posts'), pages(10), limit=100)
    assert result['stop_reason'] == 'not_paginable'


def test_the_neighbour_feed_says_it_was_capped_when_it_admits_holding_more():
    feed = operation('buddy_feed')
    result = collect(feed, pages(10, total=25), limit=100)
    assert result['stop_reason'] == 'server_capped' and result['code'] == 8
    result = collect(feed, pages(10, total=10), limit=100)
    assert result['stop_reason'] == 'not_paginable' and result['code'] == 0


def test_a_genuinely_empty_first_page_is_the_one_honest_empty_result():
    result = collect(POSTS, pages(0), limit=10)
    assert result['stop_reason'] == 'exhausted' and result['code'] == 7


def test_reaching_the_display_limit_leaves_the_walk_continuable():
    result = collect(POSTS, pages(30, 30), limit=10)
    assert result['stop_reason'] == 'limit_reached' and result['state']['page'] == 2


def test_the_same_record_is_shown_once_across_pages():
    def fetch(page):
        items = [post(9990000001), post(9990000002)] if page == 1 else [post(9990000002), post(9990000003)]
        return Page(items=items, raw_count=30 if page == 1 else 2)
    result = collect(POSTS, fetch, limit=100)
    assert [record['id'] for record in result['results']] == [
        'post:testblog/9990000001', 'post:testblog/9990000002', 'post:testblog/9990000003']


def test_a_newest_first_surface_can_prove_it_passed_below_the_window():
    dated = [['2026-09-05T00:00+09:00'] * 30, ['2026-08-01T00:00+09:00'] * 30]
    result = collect(POSTS, pages(30, 30, 30, dated=dated + [['2026-07-01T00:00+09:00'] * 30]),
                     limit=100, since='2026-09-01', monotonic=True)
    assert result['stop_reason'] == 'window_reached' and len(result['results']) == 30


def test_a_surface_whose_dates_are_not_monotonic_never_claims_the_window_was_finished():
    dated = [['2026-08-01T00:00+09:00'] * 2 + ['2026-09-05T00:00+09:00'] * 1, []]
    result = collect(POSTS, pages(3, 0, dated=dated), limit=100, since='2026-09-01', monotonic=True)
    assert result['stop_reason'] == 'exhausted'


def test_undated_items_stop_the_window_claim_too():
    dated = [[None] * 3, []]
    result = collect(POSTS, pages(3, 0, dated=dated), limit=100, since='2026-09-01', monotonic=True)
    assert result['stop_reason'] == 'exhausted'


def test_an_error_partway_keeps_what_was_already_read():
    def fetch(page):
        if page == 2:
            raise NaverBlogError(6, 'the shape changed', error='envelope_drift')
        return Page(items=[post(9990000001)] * 1, raw_count=30)
    result = collect(POSTS, fetch, limit=100)
    assert result['code'] == 8 and result['stop_reason'] == 'query_failure' and len(result['results']) == 1


def test_a_block_partway_is_reported_as_a_block_even_with_results_in_hand():
    def fetch(page):
        if page == 2:
            raise NaverBlogError(5, 'rate limited', error='rate_limit')
        return Page(items=[post(9990000001)], raw_count=30)
    result = collect(POSTS, fetch, limit=100)
    assert result['code'] == 5 and result['stop_reason'] == 'blocked'


def test_the_until_day_is_included_whole():
    assert kst_day('2026-09-07', end=True) > kst_day('2026-09-07', end=False)
    # 23:59:59.999999 KST on the named day, so a post at 23:50 that day is inside the window.
    dated = [['2026-09-07T23:50+09:00']]
    result = collect(POSTS, pages(1, dated=dated), limit=10, until='2026-09-07')
    assert len(result['results']) == 1


def test_a_backwards_window_is_refused_before_any_request():
    with pytest.raises(NaverBlogError) as caught:
        collect(POSTS, pages(30), limit=10, since='2026-09-07', until='2026-09-01')
    assert caught.value.code == 2


def test_a_malformed_date_says_what_shape_is_expected():
    with pytest.raises(NaverBlogError) as caught:
        collect(POSTS, pages(30), limit=10, since='last tuesday')
    assert caught.value.code == 2 and 'YYYY-MM-DD' in caught.value.message
