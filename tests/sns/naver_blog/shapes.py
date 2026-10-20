"""Naver's answers in miniature (synthetic names and ids only): the pages and rows a search, a blog's lists, the feed, the
neighbor lists, the topic directory and the comment box send. A fixed shape comes from cli_responses.json (scene.response);
what varies with a test (how many items, which page) is built here."""
import json

XSSI = ")]}',\n"
DAY0 = 1792368000000   # 2026-10-19 00:00 KST in epoch milliseconds


def post_items(count, start=1, blog='blog_a', **extra):
    """Search/list items as search v1/post sends them."""
    return [{'logNo': 224000000000 + i, 'blogId': f'{blog}{i % 3}', 'blogNo': 500 + i, 'title': f'글 {i}',
             'content': f'요약 {i}', 'nickname': f'닉{i}', 'blogName': f'블로그{i}', 'addDate': DAY0 - i * 60000,
             'sympathyCount': i, 'commentCount': 1, 'isBuyWithMyOwnMoney': False, **extra}
            for i in range(start, start + count)]


def search_page(items, total=7749, **result):
    return {'isSuccess': True, 'result': {'currentPage': 1, 'totalCount': total, 'list': items,
                                          'isBlockedByBifrostShield': False,
                                          'queryControlInfo': {'isAdult': False, 'isForbidden': False}, **result}}


def blog_posts(count, start=0, blog='cafe_note', day0=DAY0, **extra):
    """A blog's own post-list rows (newest first, one a day)."""
    return [{'domainIdOrBlogId': blog, 'logNo': 224000000100 - start - i, 'blogNo': 123456,
             'titleWithInspectMessage': f'글 {start + i}', 'briefContents': '요약', 'addDate': day0 - (start + i) * 86400000,
             'sympathyCnt': 3, 'commentCnt': 1, 'categoryNo': 1, 'categoryName': '맛집', 'allOpenPost': True,
             'readCount': None, 'postBlocked': False, 'notOpen': False, 'buddyOpen': False, 'bothBuddyOpen': False,
             **extra} for i in range(count)]


def post_list(items):
    return {'isSuccess': True, 'result': {'page': 1, 'categoryNo': 0, 'totalCount': 0, 'items': items}}


def feed_items(count, start=0, day0=DAY0):
    return [{'domainIdOrBlogId': f'friend{(start + i) % 4}', 'blogNo': 700 + i, 'logNo': 224000000500 - start - i,
             'title': f'이웃 글 {start + i}', 'titleWithInspectMessage': f'이웃 글 {start + i}', 'briefContents': '요약',
             'addDate': day0 - (start + i) * 3600000, 'nickName': f'이웃{i}', 'blogName': '이웃 블로그',
             'likeCount': 2, 'commentCount': 1, 'shareCount': 0, 'groupId': 1, 'relationType': 2, 'isRss': False,
             'allOpenPost': True, 'buyWithMyOwnMoney': start + i == 1} for i in range(count)]


def feed_page(items, total, page=1):
    result = {'totalCount': total, 'page': page, 'isBetterFeedTestTarget': False}
    if items:
        result['items'] = items
    return {'isSuccess': True, 'result': result}


def buddy_page(rows, viewer, pages=1, page=1, key='totalMyBuddyCount', total=None):
    return {'isSuccess': True, 'result': {'blogId': viewer, key: total if total is not None else len(rows),
                                          'totalPageCount': pages, 'currentPage': page, 'buddyList': rows}}


def buddies(count, start=0):
    return [{'blogId': f'nb{start + i}', 'blogName': f'이웃 {start + i}', 'nickName': f'n{start + i}',
             'bothNeighbor': i % 2 == 0, 'groupId': 1, 'updateTime': None, 'officialBlog': False} for i in range(count)]


def topic_posts(count, start=0, day0=DAY0):
    return [{'domainIdOrBlogId': f'tb{i}', 'blogNo': i, 'logNo': 900 + start + i, 'title': f'주제 글 {start + i}',
             'briefContents': '요약', 'addDate': day0 - (start + i) * 3600000, 'nickname': 'n', 'sympathyCnt': 1,
             'commentCnt': 0, 'buyWithMyOwnMoney': False} for i in range(count)]


def topic_page(posts, total=1000):
    return XSSI + json.dumps({'result': {'totalCount': total, 'postList': posts}}, ensure_ascii=False)


def clip_items(count):
    return [{'blogId': 'clipper', 'blogNo': 1, 'docNo': str(1600 + i), 'title': f'<b>클립</b> {i}', 'originTitle': f'클립 {i}',
             'content': '', 'playTime': '23', 'thumbnailUrl': 'https://x', 'addDate': DAY0 - i * 1000,
             'nickname': '클립러', 'momentNo': str(9000 + i), 'videoId': 'v'} for i in range(count)]
