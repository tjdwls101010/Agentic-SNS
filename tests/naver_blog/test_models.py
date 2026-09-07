"""Six surfaces name the same value six ways; normalization is what makes one reader possible."""
from naver_blog_skill._entities import build_blog, build_buddy, build_categories
from naver_blog_skill._models import build_comment, build_post, clean, link_replies, stamp

# The same post as each of Naver's surfaces spells it.
SURFACES = {
    'search': {'blogId': 'testblog', 'logNo': '99900001', 'title': '제목', 'content': '요약',
               'addDate': 1757000000000, 'commentCount': 3, 'sympathyCount': 7,
               'blogName': '블로그', 'nickname': '주인', 'categoryName': '카테고리'},
    'tag_search': {'blogId': 'testblog', 'logNo': '99900001', 'title': '제목', 'content': '요약',
                   'addDate': 1757000000000, 'commentCount': 3, 'sympathyCount': 7, 'nickname': '주인'},
    'post_list': {'logNo': '99900001', 'titleWithInspectMessage': '제목', 'briefContents': '요약',
                  'addDate': 1757000000000, 'commentCnt': 3, 'sympathyCnt': 7,
                  'categoryName': '카테고리', 'categoryNo': 108},
    'popular': {'logNo': '99900001', 'title': '제목', 'briefContents': '요약',
                'addDate': 1757000000000, 'commentCnt': 3, 'sympathyCnt': 7, 'viewCount': 500},
    'notice': {'logNo': '99900001', 'title': '제목', 'addDate': 1757000000000,
               'commentCount': 3, 'postOpenType': 'ALL'},
    'related': {'blogId': 'testblog', 'logNo': '99900001', 'title': '제목',
                'addDate': '2025-09-05T00:33:20+0900', 'commentCount': 3, 'sympathyCount': 7},
    'buddy_feed': {'blogId': 'testblog', 'logNo': '99900001', 'title': '제목', 'briefContents': '요약',
                   'addDate': 1757000000000, 'commentCnt': 3, 'sympathyCnt': 7, 'nickName': '주인'},
}


def test_every_post_surface_normalizes_to_the_same_identity_and_time():
    built = {name: build_post(raw, blog_id='testblog') for name, raw in SURFACES.items()}
    assert {post.id for post in built.values()} == {'post:testblog/99900001'}
    assert {post.title for post in built.values()} == {'제목'}
    # Epoch milliseconds and an ISO +0900 string are the same moment.
    assert len({post.created_at for post in built.values()}) == 1
    assert {post.url for post in built.values()} == {'https://blog.naver.com/testblog/99900001'}


def test_the_counts_that_exist_survive_and_the_ones_that_do_not_stay_absent():
    assert build_post(SURFACES['popular'], blog_id='testblog').view_count == 500
    # Only popular posts carry a view count; nowhere else invents one.
    assert build_post(SURFACES['search']).view_count is None
    # A notice list has no sympathy count at all, which is not a zero.
    assert build_post(SURFACES['notice'], blog_id='testblog').like_count is None
    assert build_post(SURFACES['notice'], blog_id='testblog').comment_count == 3


def test_a_read_count_of_zero_from_someone_elses_blog_is_not_reported_as_no_readers():
    assert build_post(dict(SURFACES['post_list'], readCount=0), blog_id='testblog').view_count is None
    assert build_post(dict(SURFACES['post_list'], readCount=42), blog_id='testblog').view_count == 42


def test_both_search_highlight_markups_are_removed():
    assert clean('<em class="highlight">파이썬</em> 크롤링') == '파이썬 크롤링'
    assert clean('<strong class="search_keyword">파이썬</strong> 크롤링') == '파이썬 크롤링'
    assert clean('&lt;태그&gt; &amp; 기호') == '<태그> & 기호'


def test_a_summary_cut_through_an_emoji_loses_the_broken_half_only():
    truncated = '오늘의 기록 \ud83d'
    assert clean(truncated) == '오늘의 기록'
    assert clean('오늘의 기록 💙') == '오늘의 기록 💙'


def test_all_three_of_navers_date_formats_become_one():
    assert stamp(1757000000000) == stamp('1757000000000')
    assert stamp('2026-08-05T22:47:00+0900') == '2026-08-05T22:47+09:00'
    assert stamp(None) is None and stamp('') is None
    assert stamp('not a date') is None


def test_visibility_labels_come_from_navers_own_flags():
    assert 'buddy-only' in build_post(dict(SURFACES['post_list'], allOpenPost=False, buddyOpen=True),
                                      blog_id='b').labels
    assert 'private' in build_post(dict(SURFACES['post_list'], allOpenPost=False), blog_id='b').labels
    assert 'blocked' in build_post(dict(SURFACES['post_list'], postBlocked=True), blog_id='b').labels
    assert 'buy-with-own-money' in build_post(dict(SURFACES['search'], isBuyWithMyOwnMoney=True)).labels
    assert build_post(SURFACES['search']).labels == []


def test_a_row_without_an_identity_is_dropped_rather_than_half_built():
    assert build_post({'title': '제목만'}) is None
    assert build_post({'logNo': '1'}) is None
    assert build_post('not a dict') is None


COMMENTS = [
    {'commentNo': '9990001', 'parentCommentNo': '0', 'replyLevel': 1, 'contents': '댓글',
     'userName': '사람', 'profileUserId': 'commenterone', 'regTime': '2026-08-05T22:47:00+0900',
     'sympathyCount': 0, 'replyCount': 1, 'status': 0},
    {'commentNo': '9990002', 'parentCommentNo': '9990001', 'replyLevel': 2, 'contents': '답글',
     'userName': '주인', 'regTime': '2026-08-06T09:02:00+0900', 'status': 0},
    {'commentNo': '9990003', 'parentCommentNo': '9990999', 'replyLevel': 2, 'contents': '고아 답글',
     'userName': '떠돌이', 'regTime': '2026-08-06T10:00:00+0900', 'status': 0},
]


def test_replies_arrive_flat_and_their_parent_is_named_not_nested():
    built = link_replies([build_comment(raw) for raw in COMMENTS])
    assert [c.reply_level for c in built] == [1, 2, 2]
    assert built[1].parent_comment_no == '9990001' and built[1].parent_shown
    # A reply whose parent is elsewhere is marked, so an indent never implies a quote that is absent.
    assert built[2].parent_comment_no == '9990999' and not built[2].parent_shown


def test_the_original_comment_number_is_preserved_for_the_reader():
    assert build_comment(COMMENTS[0]).comment_no == '9990001'
    assert build_comment(COMMENTS[0]).id == 'comment:9990001'


def test_status_labels_are_applied_only_from_the_booleans_naver_confirmed():
    assert build_comment(dict(COMMENTS[0], deleted=True)).labels == ['deleted']
    assert build_comment(dict(COMMENTS[0], blind=True)).labels == ['blinded']
    assert build_comment(dict(COMMENTS[0], hiddenByCleanbot=True)).labels == ['blinded']
    assert build_comment(dict(COMMENTS[0], secret=True)).labels == ['secret']


def test_a_deleted_comment_shows_no_text():
    assert build_comment(dict(COMMENTS[0], deleted=True)).text == ''


def test_an_unrecognized_status_shows_its_value_instead_of_hiding_the_text():
    # Hiding a comment on a status nobody has decoded would be a guess with a cost.
    built = build_comment(dict(COMMENTS[0], status=7))
    assert built.labels == ['status=7'] and built.text == '댓글'


def test_a_commenter_with_a_blog_gets_a_next_hop_and_one_without_does_not():
    assert build_comment(COMMENTS[0]).author_blog_id == 'commenterone'
    assert build_comment(COMMENTS[1]).author_blog_id is None
    # userIdNo comes back as an empty string, so it is never used.
    assert build_comment(dict(COMMENTS[1], userIdNo='')).author_blog_id is None


CATEGORIES = [
    {'categoryNo': 108, 'categoryName': '부모', 'parentCategoryNo': 0, 'postCnt': 40, 'openYN': 'Y'},
    {'categoryNo': 109, 'categoryName': '자식', 'parentCategoryNo': 108, 'postCnt': 12, 'openYN': 'Y'},
    {'categoryNo': 110, 'categoryName': '손자', 'parentCategoryNo': 109, 'postCnt': 2, 'openYN': 'Y'},
    {'categoryNo': 111, 'categoryName': '비공개', 'parentCategoryNo': 0, 'postCnt': 3, 'openYN': 'N'},
    {'categoryNo': 0, 'categoryName': '구분선', 'divisionLine': True, 'categoryType': 'S'},
]


def test_the_category_tree_keeps_its_depth_and_drops_its_dividers():
    rows = build_categories(CATEGORIES, 'testblog')
    assert [row.category_no for row in rows] == ['108', '109', '110', '111']
    assert [row.depth for row in rows] == [0, 1, 2, 0]
    assert rows[3].open is False and rows[0].open is True
    assert rows[0].id == 'category:testblog/108'


def test_a_blog_card_says_how_the_viewer_stands_to_it():
    assert build_blog({'blogId': 'x', 'neighbor': True}).relation == 'neighbor'
    assert build_blog({'blogId': 'x', 'neighbor': True, 'bothNeighbor': True}).relation == 'mutual-neighbor'
    assert build_blog({'blogId': 'x'}).relation is None


def test_a_blog_card_prefers_the_plain_name_over_the_highlighted_copy():
    card = build_blog({'blogId': 'x', 'blogName': '테스트 블로그',
                       'blogNameWithTag': '<em>테스트</em> 블로그'})
    assert card.name == '테스트 블로그'


def test_a_neighbour_without_an_update_time_still_builds():
    assert build_buddy({'blogId': 'buddyone', 'blogName': '이웃', 'updateTime': None}).updated_at is None
    assert build_buddy({'nickName': 'no id'}) is None
