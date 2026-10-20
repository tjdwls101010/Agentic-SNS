"""The read-only request ledger: every request the skill can make is one row here, and nothing else can be sent.

A row names its host, path template, fixed parameters, the identifiers it needs, the envelope its answer comes in,
where the records are (the leaf) and how its pages go. Callers pass identifiers, never assembled parameters: a composed
value like the comment box's objectId is wrong in a way nothing downstream sees. fetch.js holds the same route table
(a test compares the two), so a typo cannot widen what leaves the process. The app bundle ships write APIs beside
these (sympathy, buddy add/delete, block, hide, notify, command.blog.naver.com); none is a row, so none can be sent.
"""
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

from sns.errors import SnsError

SEARCH_CEILING = 1000  # search stops at 1,000 accumulated results in every order
IMAGE_HOST_SUFFIX = '.pstatic.net'
_PLACEHOLDERS = {'blogId': r'[A-Za-z0-9_-]{1,64}', 'me': r'[A-Za-z0-9_-]{1,64}', 'logNo': r'[0-9]{1,40}',
                 'code': r'[A-Za-z0-9]{1,32}'}
IMAGE_PATH = r'/[A-Za-z0-9._~%/-]{0,512}'
_BUG = 'This is a bug in the skill, not in your command; report the command you ran.'

M, SECTION, APIS = 'm.blog.naver.com', 'section.blog.naver.com', 'apis.naver.com'


@dataclass(frozen=True)
class Operation:
    op: str
    host: str
    path: str
    params: dict = field(default_factory=dict)
    required: tuple = ()
    envelope: str = 'mblog'          # mblog (isSuccess/result/error), cbox (success/code), section (XSSI), html, hop, image
    leaf: str | None = None
    leaf_type: str | None = None     # list | dict | int
    pagination: str | None = None    # plain (page+1, a short page ends it) | marked (the answer names the last page)
    page_size: int | None = None
    page_param: str = 'page'
    marker: str | None = None        # where a marked surface names its last page
    ceiling: int | None = None
    total: str | None = None         # where Naver reports a total (a drifting figure, shown, never decided on)
    empty_when_missing: bool = False  # a page past the end comes without its leaf (feed/v1): that is an empty page
    login: bool = False
    identity: str | None = None      # a field the answer must agree with the request on
    resolves_identity: bool = False  # the answer's id is authoritative (a domain address answers under its real id)
    accept: str = 'json'


def _rows(*rows):
    table = {}
    for row in rows:
        if row.op in table:
            raise ValueError('duplicate operation ' + row.op)
        table[row.op] = row
    return table


OPERATIONS = _rows(
    Operation('current_user', M, '/api/current-user', leaf='result', leaf_type='dict', login=True),
    Operation('search_posts', M, '/api/search/v1/post', params={'itemCount': 30}, required=('keyword', 'sortType'),
              leaf='result.list', leaf_type='list', pagination='plain', page_size=30, ceiling=SEARCH_CEILING,
              total='result.totalCount'),
    Operation('search_blogs', M, '/api/search/v2/blog', required=('keyword', 'sortType'), leaf='result.list',
              leaf_type='list', pagination='marked', page_size=20, marker='result.totalPage', ceiling=SEARCH_CEILING,
              total='result.totalCount'),
    Operation('search_clips', M, '/api/search/v1/moment', required=('keyword', 'sortType'), leaf='result.list',
              leaf_type='list', pagination='marked', page_size=20, marker='result.totalPage', ceiling=SEARCH_CEILING,
              total='result.totalCount'),
    # Tag search ignores sortType and comes newest first.
    Operation('search_tags', M, '/api/tags/search/post', params={'itemCount': 30}, required=('query',),
              leaf='result.items', leaf_type='list', pagination='plain', page_size=30, ceiling=SEARCH_CEILING,
              total='result.totalCount'),
    Operation('popular_keywords', M, '/api/v1/popular-keywords', leaf='result', leaf_type='dict'),
    Operation('related_keywords', M, '/api/related-keywords', required=('keyword',), leaf='result', leaf_type='dict'),
    Operation('blog_card', M, '/api/blogs/{blogId}', leaf='result', leaf_type='dict', identity='result.blogId',
              resolves_identity=True),
    Operation('contents_count', M, '/api/blogs/{blogId}/contents-count', leaf='result', leaf_type='dict'),
    Operation('categories', M, '/api/blogs/{blogId}/category-list', leaf='result.mylogCategoryList', leaf_type='list'),
    # itemCount above 30 is param_is_invalidate; result.totalCount is always 0 here.
    Operation('post_list', M, '/api/blogs/{blogId}/post-list', params={'itemCount': 30}, required=('categoryNo',),
              leaf='result.items', leaf_type='list', pagination='plain', page_size=30),
    Operation('popular_posts', M, '/api/blogs/{blogId}/popular-post-list', leaf='result.popularPostList',
              leaf_type='list'),
    Operation('notice_posts', M, '/api/blogs/{blogId}/notice-post-list', leaf='result.noticePostViewList',
              leaf_type='list'),
    # keyword= answers 500 here: the parameter really is query.
    Operation('blog_search', M, '/api/blogs/{blogId}/search/post', required=('query', 'sortType'), leaf='result.list',
              leaf_type='list', pagination='marked', page_size=20, marker='result.totalPage', total='result.totalCount'),
    # Its page marker is computed against 20 while a page holds 30, so the plain policy is the honest one.
    Operation('blog_tag_search', M, '/api/blogs/{blogId}/search/tag', required=('query',), leaf='result.list',
              leaf_type='list', pagination='plain', page_size=30, total='result.totalCount'),
    Operation('post_html', M, '/PostView.naver', required=('blogId', 'logNo'), envelope='html', accept='html'),
    Operation('sympathy', M, '/api/blogs/{blogId}/posts/{logNo}/sympathy-users', leaf='result', leaf_type='dict'),
    Operation('related_category', M, '/api/blogs/{blogId}/v1/category-related-posts',
              params={'countPerPage': 5, 'isInitialPage': 'true', 'isFromSearchAddView': 'false'},
              required=('blogId', 'categoryNo', 'logNo'), leaf='result.recommendationPostList', leaf_type='list'),
    Operation('comments_info', M, '/api/blogs/{blogId}/posts/{logNo}/comments-info', leaf='result', leaf_type='dict'),
    Operation('comments', APIS, '/commentBox/cbox/web_naver_list_json.json',
              params={'ticket': 'blog', 'templateId': 'default_simple', 'pool': 'blogid', 'listType': 'OBJECT',
                      'pageType': 'more', 'pageSize': 100, 'indexSize': 10, 'replyPageSize': 10, 'showReply': 'true',
                      'initialize': 'true', 'useAltSort': 'true', 'lang': 'ko'},
              required=('blogNo', 'logNo'), envelope='cbox', leaf='result.commentList', leaf_type='list',
              pagination='marked', page_size=100, marker='result.pageModel.totalPages', identity='objectId',
              total='result.count.total'),
    Operation('feed', M, '/api/blogs/{me}/feed/v1', params={'itemCount': 20}, required=('groupId',),
              leaf='result.items', leaf_type='list', pagination='plain', page_size=20, total='result.totalCount',
              empty_when_missing=True, login=True),
    Operation('buddy_groups', M, '/api/blogs/{me}/buddy-groups', leaf='result', leaf_type='list', login=True),
    Operation('my_buddies', M, '/api/blogs/{me}/my-buddies', params={'sortType': 2}, leaf='result.buddyList',
              leaf_type='list', pagination='marked', page_size=20, page_param='pageNo', marker='result.totalPageCount',
              total='result.totalMyBuddyCount', login=True),
    Operation('followers', M, '/api/blogs/{me}/me-buddies', leaf='result.buddyList', leaf_type='list',
              pagination='marked', page_size=20, page_param='pageNo', marker='result.totalPageCount',
              total='result.totalMeBuddyCount', login=True),
    Operation('public_buddies', M, '/api/blogs/{blogId}/public-buddies', leaf='result.buddyList', leaf_type='list',
              pagination='marked', page_size=50, page_param='pageNo', marker='result.totalPageCount',
              total='result.totalPublicBuddyCount'),
    Operation('directories', SECTION, '/ajax/DirectoryList.naver', envelope='section', leaf='result', leaf_type='list'),
    Operation('directory_posts', SECTION, '/ajax/DirectoryPostList.naver', required=('directorySeq',),
              envelope='section', leaf='result.postList', leaf_type='list', pagination='plain', page_size=10,
              page_param='pageNo', ceiling=SEARCH_CEILING, total='result.totalCount'),
    Operation('directory_top', SECTION, '/ajax/DirectoryTopPostList.naver', required=('directorySeq',),
              envelope='section', leaf='result', leaf_type='list'),
    Operation('monthly_issues', M, '/api/thismonthblog/year-month-list', leaf='result.yearList', leaf_type='list'),
    Operation('monthly_blogs', M, '/api/thismonthblog/directory-blogid-list', leaf='result.directoryAndBlogIdList',
              leaf_type='list'),
    Operation('monthly_profiles', M, '/api/blogs/profiles/profile-relation-list', required=('blogIdList',),
              leaf='result.blogProfileAndRelationView', leaf_type='list'),
    Operation('monthly_posts', M, '/api/blogs/posts/popular-post-list', required=('blogIdList',),
              leaf='result.popularPostList', leaf_type='list'),
    # Only after not_exist_blog: the page names the blog's own id (a 3xx location or a 200 frameset).
    Operation('blog_frame', 'blog.naver.com', '/{blogId}', envelope='hop', accept='html'),
    Operation('short_link', 'naver.me', '/{code}', envelope='hop', accept='html'),
    Operation('image', '*' + IMAGE_HOST_SUFFIX, '', envelope='image', accept='image'),
)


def _pattern(path):
    return '^' + re.sub(r'\\\{(\w+)\\\}', lambda m: _PLACEHOLDERS[m[1]], re.escape(path)) + '$'


# host → full-match path patterns; fetch.js holds the same table.
ROUTES = {}
for _row in OPERATIONS.values():
    if _row.envelope != 'image':
        ROUTES.setdefault(_row.host, []).append(_pattern(_row.path))
ROUTES['*' + IMAGE_HOST_SUFFIX] = ['^' + IMAGE_PATH + '$']


def image_host(host):
    return bool(host) and host.endswith(IMAGE_HOST_SUFFIX) and re.fullmatch(r'[a-z0-9-]+(\.[a-z0-9-]+)*', host) is not None


def allowed(host, path, query=None):
    """Whether (host, path, query) is on the read surface: a full match of one row, no traversal however encoded, and
    no fragment or backslash in the query (a string, as it would be sent)."""
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//'):
        return False
    if re.search(r'\.\.|\\|%2e|%2f|%5c', path, re.I):
        return False
    if query is not None and (not isinstance(query, str) or re.search(r'[#\\]', query)):
        return False
    patterns = ROUTES.get(host) or (ROUTES['*' + IMAGE_HOST_SUFFIX] if image_host(host) else [])
    return any(re.fullmatch(pattern[1:-1], path) for pattern in patterns)


def operation(name):
    try:
        return OPERATIONS[name]
    except KeyError:
        raise SnsError('failed', f'Unknown operation {name}.', _BUG, reason='drift') from None


def build(name, page=None, **ids):
    """(host, path, query) of one request from identifiers alone; query is a dict the fetch snippet encodes."""
    row = operation(name)
    missing = [key for key in row.required if ids.get(key) in (None, '')]
    if missing:
        raise SnsError('failed', f'Operation {name} is missing {", ".join(missing)}.', _BUG, reason='drift')
    values = {key: value for key, value in ids.items() if value is not None}
    path_keys = set(re.findall(r'\{(\w+)\}', row.path))
    try:
        path = row.path.format(**{key: values[key] for key in path_keys})
    except KeyError as error:
        raise SnsError('failed', f'Operation {name} needs {error} in its path.', _BUG, reason='drift') from None
    query = dict(row.params)
    if name == 'comments':
        blog_no, log_no = values.pop('blogNo'), values.pop('logNo')
        values.update(objectId=f'{blog_no}_201_{log_no}', groupId=str(blog_no))
    # A value can belong to both: category-related-posts names the blog in its path and again as a parameter.
    query.update({key: value for key, value in values.items() if key not in path_keys or key in row.required})
    if page is not None:
        if not row.pagination:
            raise SnsError('failed', f'Operation {name} has no pages.', _BUG, reason='drift')
        query[row.page_param] = page
    if not allowed(row.host, path, encoded(query)):
        raise SnsError('failed', f'Operation {name} built a request outside the read surface.', _BUG, reason='drift')
    return row.host, path, query


def encoded(query):
    """The query as the snippet sends it: form-encoded, one pair per key."""
    return urlencode(query)


def frame_blog_id(response):
    """The canonical blog id blog.naver.com/{id} names: a 3xx location's blogId, or a 200 frameset's var blogId (its
    mainFrame src names the same). 404 is no such blog; anything else, or a location off the read surface, is drift."""
    status, location = response.get('status'), response.get('location')
    found = None
    if status and 300 <= status < 400 and location:
        url = urlsplit(urljoin(response.get('url') or 'https://blog.naver.com/', location))
        if url.scheme != 'https' or (url.hostname or '') not in ('blog.naver.com', 'm.blog.naver.com'):
            raise SnsError('failed', 'A blog address redirected off the read surface.', 'Run doctor; the redirect '
                                                                                         'changed.', reason='drift')
        found = dict(parse_qsl(url.query)).get('blogId') or url.path.strip('/').split('/')[0]
    elif status == 200:
        match = re.search(r"""var\s+blogId\s*=\s*['"]([^'"]*)['"]""", response.get('body') or '')
        found = match[1] if match else None
    elif status == 404:
        raise SnsError('unavailable', 'That blog id does not exist and is not a domain address.',
                       'Check the id; open the blog once in Aside and pass the id in its address bar.',
                       reason='not_exist_blog')
    if not found or not re.fullmatch(_PLACEHOLDERS['blogId'], found):
        raise SnsError('failed', 'The blog address did not name a blog id.', 'Run doctor; the page changed.',
                       reason='drift')
    return found
