"""The endpoint ledger: what each operation asks for and what its answer must look like.

Every row is transcribed from the approved snapshot, and a test compares the two, so a
new endpoint is a row here rather than a branch in transport, walk or a command. The row
also owns the query: callers pass identifiers, never assembled parameters, because a
composed value like the comment box's objectId is wrong in a way nothing downstream sees.
"""
from dataclasses import dataclass, field, replace
from urllib.parse import urlencode

from ._errors import NaverBlogError

# Naver's only header contract is a referer per host; there is no CSRF token, signature or bundle id.
REFERER = {
    'm.blog.naver.com': 'https://m.blog.naver.com/',
    'section.blog.naver.com': 'https://section.blog.naver.com/',
    'apis.naver.com': 'https://m.blog.naver.com/',
    'blog.naver.com': 'https://blog.naver.com/',
}

# browser/fetch.js enforces the same list; both sides must agree or a typo widens the surface.
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
    required: tuple = ()
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
    # 'measured' was seen on 2026-09-07 in the logged-in session; 'legacy' comes from the
    # earlier anonymous recon and has not been re-confirmed against a logged-in account.
    source: str = 'measured'

    @property
    def paginated(self):
        return self.pagination in ('page', 'page_marked')

    def at_ceiling(self, position):
        """Is a short page here the server's 1,000-item ceiling rather than the end of the results?

        Naver stops serving somewhere in the last page before 1,000 rather than exactly at it:
        post search went short at position 1,000, tag search went empty at 990. Both are the
        ceiling, so the test is whether one more page would cross it, not whether we reached it.
        """
        return bool(self.cap) and position + (self.page_size or 0) > self.cap


def _catalog(*operations):
    ledger = {}
    for operation in operations:
        if operation.op in ledger:
            raise ValueError('Duplicate operation row: ' + operation.op)
        ledger[operation.op] = operation
    return ledger


OPERATIONS = _catalog(
    Operation('search_posts', 'm.blog.naver.com', '/api/search/v1/post',
              params={'itemCount': 30}, required=('keyword', 'sortType'), success='isSuccess',
              leaf='result.list', leaf_type='list', pagination='page', page_size=30,
              page_param='page', cap=SEARCH_CEILING),
    Operation('search_blogs', 'm.blog.naver.com', '/api/search/v1/blog',
              params={'itemCount': 30}, required=('keyword',), success='isSuccess',
              leaf='result.list', leaf_type='list', pagination='page', page_size=30,
              page_param='page', cap=SEARCH_CEILING),
    Operation('search_tags', 'm.blog.naver.com', '/api/tags/search/post',
              params={'itemCount': 30}, required=('query',), success='isSuccess',
              leaf='result.items', leaf_type='list', pagination='page', page_size=30,
              page_param='page', cap=SEARCH_CEILING),
    Operation('search_posts_section', 'section.blog.naver.com', '/ajax/SearchList.naver',
              params={'type': 'post', 'countPerPage': 30}, required=('keyword', 'orderBy'),
              leaf='result.searchList', leaf_type='list', pagination='page', page_size=30,
              page_param='currentPage', cap=SEARCH_CEILING, role='fallback'),
    Operation('search_blogs_section', 'section.blog.naver.com', '/ajax/SearchList.naver',
              params={'type': 'blog', 'countPerPage': 30}, required=('keyword', 'orderBy'),
              leaf='result.searchList', leaf_type='list', pagination='page', page_size=30,
              page_param='currentPage', cap=SEARCH_CEILING, role='fallback'),
    Operation('blog_card', 'm.blog.naver.com', '/api/blogs/{blogId}', success='isSuccess',
              leaf='result', leaf_type='dict', identity='result.blogId'),
    Operation('categories', 'm.blog.naver.com', '/api/blogs/{blogId}/category-list', success='isSuccess',
              leaf='result.mylogCategoryList', leaf_type='list'),
    # itemCount above 30 returns param_is_invalidate, and result.totalCount is always 0.
    Operation('post_list', 'm.blog.naver.com', '/api/blogs/{blogId}/post-list',
              params={'categoryNo': 0, 'itemCount': 30}, success='isSuccess',
              leaf='result.items', leaf_type='list', pagination='page', page_size=30, page_param='page'),
    Operation('popular_posts', 'm.blog.naver.com', '/api/blogs/{blogId}/popular-post-list', success='isSuccess',
              leaf='result.popularPostList', leaf_type='list'),
    Operation('notice_posts', 'm.blog.naver.com', '/api/blogs/{blogId}/notice-post-list', success='isSuccess',
              leaf='result.noticePostViewList', leaf_type='list'),
    # keyword= returns 500 on this surface; the parameter really is named query.
    Operation('blog_search', 'm.blog.naver.com', '/api/blogs/{blogId}/search/post',
              required=('query', 'sortType'), success='isSuccess',
              leaf='result.list', leaf_type='list', pagination='page_marked', page_size=20,
              page_param='page', marker='result.totalPage'),
    # The tag marker is computed against 20 while the page holds 30, so this row keeps the plain policy.
    Operation('blog_tag_search', 'm.blog.naver.com', '/api/blogs/{blogId}/search/tag',
              required=('query',), success='isSuccess', leaf='result.list', leaf_type='list',
              pagination='page', page_size=30, page_param='page', source='legacy'),
    Operation('public_buddies', 'm.blog.naver.com', '/api/blogs/{blogId}/public-buddies', success='isSuccess',
              leaf='result.buddyList', leaf_type='list', pagination='page_marked', page_size=20,
              page_param='pageNo', marker='result.totalPageCount'),
    Operation('my_buddies', 'm.blog.naver.com', '/api/blogs/{blogId}/my-buddies',
              params={'sortType': 2}, success='isSuccess', leaf='result.buddyList', leaf_type='list',
              pagination='page_marked', page_size=20, page_param='pageNo',
              marker='result.totalPageCount', login=True),
    # currentPage, countPerPage and groupId are all ignored; they are sent only to keep the request shape.
    Operation('buddy_feed', 'section.blog.naver.com', '/ajax/BuddyPostList.naver',
              params={'currentPage': 1, 'groupId': 0, 'countPerPage': 30, 'categoryNo': 0},
              leaf='result.buddyPostList', leaf_type='list', pagination='no_paging',
              total_field='result.buddyPostTotalCount', login=True),
    Operation('post_html', 'm.blog.naver.com', '/PostView.naver', required=('blogId', 'logNo'),
              accept='html', identity='var blogNo + uri'),
    Operation('comments', 'apis.naver.com', '/commentBox/cbox/web_naver_list_json.json',
              params={'ticket': 'blog', 'templateId': 'default_simple', 'pool': 'blogid',
                      'listType': 'OBJECT', 'pageType': 'more', 'pageSize': 100, 'indexSize': 10,
                      'replyPageSize': 10, 'showReply': 'true', 'initialize': 'true',
                      'useAltSort': 'true', 'lang': 'ko'},
              required=('blogNo', 'logNo'), success='success', leaf='result.commentList', leaf_type='list',
              identity='result.commentList[].objectId', pagination='page_marked', page_size=100,
              page_param='page', marker='result.pageModel.totalPages'),
    Operation('comments_info', 'm.blog.naver.com', '/api/blogs/{blogId}/posts/{logNo}/comments-info',
              success='isSuccess', leaf='result', leaf_type='dict'),
    Operation('related_category', 'm.blog.naver.com', '/api/blogs/{blogId}/v1/category-related-posts',
              params={'countPerPage': 5, 'isInitialPage': 'true', 'isFromSearchAddView': 'false'},
              required=('blogId', 'categoryNo', 'logNo'), success='isSuccess',
              leaf='result.recommendationPostList', leaf_type='list'),
    # Verified to exist and to return this envelope; the one sample held zero items, so no command calls it.
    Operation('related_tag', 'm.blog.naver.com', '/api/end-recommend/search/tag-posts',
              params={'countPerPage': 6, 'recommendationType': 'FIRST_TAG_POST', 'recommendationCategory': 'ETC'},
              required=('blogId', 'logNo', 'searchKeyword'), success='isSuccess',
              leaf='result.recommendationPostList', leaf_type='list', role='unused'),
    Operation('directories', 'section.blog.naver.com', '/ajax/DirectoryList.naver',
              leaf='result', leaf_type='list'),
    Operation('directory_posts', 'section.blog.naver.com', '/ajax/DirectoryPostList.naver',
              required=('directorySeq',), leaf='result.postList', leaf_type='list', pagination='page',
              page_size=10, page_param='pageNo', cap=SEARCH_CEILING),
    Operation('directory_top', 'section.blog.naver.com', '/ajax/DirectoryTopPostList.naver',
              required=('directorySeq',), leaf='result', leaf_type='list'),
    Operation('monthly_blogs', 'section.blog.naver.com', '/ajax/ThisMonthDirectoryBlogList.naver',
              required=('year', 'month'), leaf='result.list', leaf_type='list'),
    Operation('editor_picks', 'section.blog.naver.com', '/ajax/EditorPickList.naver',
              required=('year', 'month'), leaf='result.list', leaf_type='list'),
    Operation('feed_html', 'm.blog.naver.com', '/FeedList.naver', accept='html', login=True),
    # Only reached after a not_exist_blog: one hop, and the location is validated before it is reused.
    Operation('domain_redirect', 'blog.naver.com', '/{blogId}', accept='html'),
)

# Path placeholders are named for the reader; these all mean the same blog id.
PATH_KEYS = {'blogId', 'me', 'maybeDomainId', 'logNo'}


def operation(name):
    try:
        return OPERATIONS[name]
    except KeyError:
        raise NaverBlogError(6, 'Unknown operation: ' + str(name), 'Reinstall the Naver Blog skill.') from None


def _compose(name, values):
    """Derived parameters live here so no caller can assemble one slightly wrong."""
    if name == 'comments':
        blog_no, log_no = values.pop('blogNo'), values.pop('logNo')
        values['objectId'] = f'{blog_no}_201_{log_no}'
        values['groupId'] = str(blog_no)
    return values


def build(name, page=None, **values):
    """Return (host, path, query) for one request; identifiers in, assembled request out."""
    spec = operation(name)
    missing = [key for key in spec.required if values.get(key) in (None, '')]
    if missing:
        raise NaverBlogError(6, f'Operation {name} is missing {", ".join(missing)}.',
                             'Reinstall the Naver Blog skill.')
    path_values = {key: values.pop(key) for key in list(values) if '{' + key + '}' in spec.path}
    try:
        path = spec.path.format(**path_values) if '{' in spec.path else spec.path
    except KeyError as error:
        raise NaverBlogError(6, f'Operation {name} needs {error} in its path.',
                             'Reinstall the Naver Blog skill.') from None
    # replace() keeps the frozen row intact; the shared params dict is never mutated.
    query = dict(spec.params)
    query.update({key: value for key, value in _compose(name, dict(values)).items() if value is not None})
    if page is not None:
        if not spec.page_param:
            raise NaverBlogError(6, f'Operation {name} has no page parameter.', 'Reinstall the Naver Blog skill.')
        query[spec.page_param] = page
    return replace(spec), path, urlencode(query)
