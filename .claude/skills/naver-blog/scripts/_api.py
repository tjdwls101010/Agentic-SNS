"""The endpoint ledger: what each operation asks for and what its answer must look like.

Every field here is measured, not guessed, and classify/walk read the ledger instead of
hard-coding a surface. A new endpoint is a row, never a branch elsewhere.
"""
from dataclasses import dataclass, field

# Naver's only header contract is a referer per host; there is no CSRF token, signature or bundle id.
REFERER = {
    'm.blog.naver.com': 'https://m.blog.naver.com/',
    'section.blog.naver.com': 'https://section.blog.naver.com/',
    'apis.naver.com': 'https://m.blog.naver.com/',
    'blog.naver.com': 'https://blog.naver.com/',
}

# The snippet enforces the same list; both sides must agree or a typo silently widens the surface.
ALLOWED = {
    'm.blog.naver.com': ('/api/', '/PostView.naver', '/FeedList.naver'),
    'section.blog.naver.com': ('/ajax/',),
    'apis.naver.com': ('/commentBox/cbox/web_naver_list_json.json',),
    'blog.naver.com': ('/NBlogTop.naver', '/'),
}

# Search stops at 1,000 accumulated items, and past that the server reports totalCount 0.
SEARCH_CEILING = 1000


@dataclass(frozen=True)
class Operation:
    op: str
    host: str
    path: str
    params: dict = field(default_factory=dict)
    success: str | None = None
    leaf: str | None = None
    leaf_type: str | None = None
    identity: str | None = None
    pagination: str = 'single'
    page_size: int | None = None
    page_param: str | None = None
    cap: int | None = None
    marker: str | None = None
    total_field: str | None = None
    login: bool = False
    accept: str = 'json'
    role: str = 'primary'

    def url_path(self, **values):
        """Path templates carry only identifiers the caller already validated."""
        return self.path.format(**values) if '{' in self.path else self.path


def _op(*args, **kwargs):
    operation = Operation(*args, **kwargs)
    return operation.op, operation


OPERATIONS = dict([
    _op('search_posts', 'm.blog.naver.com', '/api/search/v1/post',
        params={'sortType': 'sim', 'itemCount': 30}, success='isSuccess',
        leaf='result.list', leaf_type='list', pagination='page', page_size=30,
        page_param='page', cap=SEARCH_CEILING),
    _op('search_blogs', 'm.blog.naver.com', '/api/search/v1/blog',
        params={'itemCount': 30}, success='isSuccess',
        leaf='result.list', leaf_type='list', pagination='page', page_size=30,
        page_param='page', cap=SEARCH_CEILING),
    _op('search_tags', 'm.blog.naver.com', '/api/tags/search/post',
        params={'itemCount': 30}, success='isSuccess',
        leaf='result.items', leaf_type='list', pagination='page', page_size=30,
        page_param='page', cap=SEARCH_CEILING),
    _op('search_posts_section', 'section.blog.naver.com', '/ajax/SearchList.naver',
        params={'type': 'post', 'orderBy': 'sim', 'countPerPage': 30},
        leaf='result.searchList', leaf_type='list', pagination='page', page_size=30,
        page_param='currentPage', cap=SEARCH_CEILING, role='fallback'),
    _op('search_blogs_section', 'section.blog.naver.com', '/ajax/SearchList.naver',
        params={'type': 'blog', 'orderBy': 'sim', 'countPerPage': 30},
        leaf='result.searchList', leaf_type='list', pagination='page', page_size=30,
        page_param='currentPage', cap=SEARCH_CEILING, role='fallback'),
    _op('blog_card', 'm.blog.naver.com', '/api/blogs/{blogId}', success='isSuccess',
        leaf='result', leaf_type='dict', identity='result.blogId'),
    _op('categories', 'm.blog.naver.com', '/api/blogs/{blogId}/category-list', success='isSuccess',
        leaf='result.mylogCategoryList', leaf_type='list'),
    _op('post_list', 'm.blog.naver.com', '/api/blogs/{blogId}/post-list',
        params={'categoryNo': 0, 'itemCount': 30}, success='isSuccess',
        leaf='result.items', leaf_type='list', pagination='page', page_size=30, page_param='page'),
    _op('popular_posts', 'm.blog.naver.com', '/api/blogs/{blogId}/popular-post-list', success='isSuccess',
        leaf='result.popularPostList', leaf_type='list'),
    _op('notice_posts', 'm.blog.naver.com', '/api/blogs/{blogId}/notice-post-list', success='isSuccess',
        leaf='result.noticePostViewList', leaf_type='list'),
    _op('blog_search', 'm.blog.naver.com', '/api/blogs/{blogId}/search/post',
        params={'sortType': 'sim'}, success='isSuccess', leaf='result.list', leaf_type='list',
        pagination='page_marked', page_size=20, page_param='page', marker='result.totalPage'),
    # The tag marker is computed against 20 while the page holds 30, so this surface keeps the plain policy.
    _op('blog_tag_search', 'm.blog.naver.com', '/api/blogs/{blogId}/search/tag', success='isSuccess',
        leaf='result.list', leaf_type='list', pagination='page', page_size=30, page_param='page'),
    _op('public_buddies', 'm.blog.naver.com', '/api/blogs/{blogId}/public-buddies', success='isSuccess',
        leaf='result.buddyList', leaf_type='list', pagination='page_marked', page_size=20,
        page_param='pageNo', marker='result.totalPageCount'),
    _op('my_buddies', 'm.blog.naver.com', '/api/blogs/{blogId}/my-buddies',
        params={'sortType': 2}, success='isSuccess', leaf='result.buddyList', leaf_type='list',
        pagination='page_marked', page_size=20, page_param='pageNo',
        marker='result.totalPageCount', login=True),
    # currentPage, countPerPage and groupId are all ignored; they are sent only to keep the request shape.
    _op('buddy_feed', 'section.blog.naver.com', '/ajax/BuddyPostList.naver',
        params={'currentPage': 1, 'groupId': 0, 'countPerPage': 30, 'categoryNo': 0},
        leaf='result.buddyPostList', leaf_type='list', pagination='no_paging',
        total_field='result.buddyPostTotalCount', login=True),
    _op('post_html', 'm.blog.naver.com', '/PostView.naver', accept='html', identity='blogId'),
    _op('comments', 'apis.naver.com', '/commentBox/cbox/web_naver_list_json.json',
        params={'ticket': 'blog', 'templateId': 'default_simple', 'pool': 'blogid',
                'listType': 'OBJECT', 'pageType': 'more', 'pageSize': 100, 'indexSize': 10,
                'replyPageSize': 10, 'showReply': 'true', 'initialize': 'true',
                'useAltSort': 'true', 'lang': 'ko'},
        success='success', leaf='result.commentList', leaf_type='list',
        identity='result.commentList.objectId', pagination='page_marked', page_size=100,
        page_param='page', marker='result.pageModel.totalPages'),
    _op('comments_info', 'm.blog.naver.com', '/api/blogs/{blogId}/posts/{logNo}/comments-info',
        success='isSuccess', leaf='result', leaf_type='dict'),
    _op('related_category', 'm.blog.naver.com', '/api/blogs/{blogId}/v1/category-related-posts',
        params={'countPerPage': 5, 'isInitialPage': 'true', 'isFromSearchAddView': 'false'},
        success='isSuccess', leaf='result.recommendationPostList', leaf_type='list'),
    # Verified to exist and to return the envelope below; the one sample held zero items, so no command calls it.
    _op('related_tag', 'm.blog.naver.com', '/api/end-recommend/search/tag-posts',
        params={'countPerPage': 6, 'recommendationType': 'FIRST_TAG_POST', 'recommendationCategory': 'ETC'},
        success='isSuccess', leaf='result.recommendationPostList', leaf_type='list', role='unused'),
    _op('directories', 'section.blog.naver.com', '/ajax/DirectoryList.naver',
        leaf='result', leaf_type='list'),
    _op('directory_posts', 'section.blog.naver.com', '/ajax/DirectoryPostList.naver',
        leaf='result.postList', leaf_type='list', pagination='page', page_size=10,
        page_param='pageNo', cap=SEARCH_CEILING),
    _op('directory_top', 'section.blog.naver.com', '/ajax/DirectoryTopPostList.naver',
        leaf='result', leaf_type='list'),
    _op('monthly_blogs', 'section.blog.naver.com', '/ajax/ThisMonthDirectoryBlogList.naver',
        leaf='result.list', leaf_type='list'),
    _op('editor_picks', 'section.blog.naver.com', '/ajax/EditorPickList.naver',
        leaf='result.list', leaf_type='list'),
    _op('feed_html', 'm.blog.naver.com', '/FeedList.naver', accept='html', login=True),
    # Only reached after a not_exist_blog: one hop, and the location is validated before it is reused.
    _op('domain_redirect', 'blog.naver.com', '/{blogId}', accept='html'),
])


def operation(name):
    return OPERATIONS[name]
