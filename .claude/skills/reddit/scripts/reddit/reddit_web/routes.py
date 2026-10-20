"""What may be requested, in which of Reddit's buckets it counts, and how each read surface becomes a request.

Only read endpoints the commands use are allowed: a path is checked here before it is sent and again when a redirect
leads elsewhere. Wiki pages count in their own bucket; every other .json read in the general one. A share link is
requested as a page: Reddit sends no rate-limit headers for it and does not count it in a .json bucket.
"""
import re
from dataclasses import dataclass, field

from reddit.errors import RedditError

FEED_SORTS = ('best', 'hot', 'new', 'top', 'rising')
SUB_SORTS = ('hot', 'new', 'top', 'rising', 'controversial')
COMMENT_SORTS = ('best', 'top', 'new', 'controversial', 'old', 'qa')
PROFILE_TYPES = ('overview', 'posts', 'comments')
PROFILE_SORTS = ('new', 'hot', 'top', 'controversial')
SEARCH_TYPES = ('posts', 'subs', 'users')
SEARCH_SORTS = ('relevance', 'hot', 'top', 'new', 'comments')
TIMES = ('hour', 'day', 'week', 'month', 'year', 'all')
ME_COLLECTIONS = ('subs', 'saved', 'upvoted')
PAGE_SIZE = 100          # what a listing page asks for; what is not shown waits in the handle
THREAD_LIMIT = 500       # comments a post read asks for
THREAD_DEPTH = 10
BATCH = 100              # ids one morechildren request may carry

_SUB = r'[A-Za-z0-9_]+'
_ID = r'[A-Za-z0-9]+'
_ROUTES = (
    (r'/(best|hot|new|top|rising)\.json', 'general'),
    (rf'/r/{_SUB}(\+{_SUB})*/(hot|new|top|rising|controversial|search)\.json', 'general'),
    (rf'/r/{_SUB}/about(/rules|/moderators)?\.json', 'general'),
    (rf'/r/{_SUB}/wiki/[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)?\.json', 'wiki'),
    (rf'/(r/{_SUB}/)?comments/{_ID}(/[^/]+/{_ID})?\.json', 'general'),
    (rf'/duplicates/{_ID}\.json', 'general'),
    (r'/user/[A-Za-z0-9_-]+/(about|overview|submitted|comments|saved|upvoted)\.json', 'general'),
    (r'/(search|subreddits/search|subreddits/mine/subscriber|api/me|api/morechildren)\.json', 'general'),
)


@dataclass(frozen=True)
class Request:
    path: str | None
    query: dict = field(default_factory=dict)
    expect: str = 'listing'      # the response shape (see classify)
    personal: bool = False       # the user's own surface: an empty modhash there means logged out
    url: str | None = None       # a share link, requested as a page

    @property
    def bucket(self):
        return 'share' if self.url else bucket_of(self.path)

    @property
    def metered(self):
        return self.url is None


def bucket_of(path, code=2):
    """The bucket of an allowed path; anything else is refused (code 2 for a path this skill built, 6 when Reddit's
    redirect led there)."""
    if (not isinstance(path, str) or not re.fullmatch(r'/(?!/)[A-Za-z0-9_+./-]+\.json', path)
            or any(part in ('.', '..') for part in path.split('/'))):
        raise RedditError(code, 'Not a Reddit path this skill reads.', 'Report this as a skill bug.' if code == 2
                          else 'Open the link in the Aside browser and pass its permalink.')
    for pattern, bucket in _ROUTES:
        if re.fullmatch(pattern, path):
            return bucket
    raise RedditError(code, 'Not a Reddit endpoint this skill reads.', 'Report this as a skill bug.' if code == 2
                      else 'Open the link in the Aside browser and pass its permalink.')


def _query(**values):
    return {key: value for key, value in values.items() if value is not None}


def feed(sort, time=None, after=None):
    return Request(f'/{sort}.json', _query(limit=PAGE_SIZE, t=time, after=after), personal=True)


def listing(sub, sort, time=None, after=None):
    return Request(f'/r/{sub}/{sort}.json', _query(limit=PAGE_SIZE, t=time, after=after))


def _comment_sort(sort):
    return 'confidence' if sort == 'best' else sort


def post(post_id, sort, comment_id=None, context=None):
    suffix = f'/_/{comment_id}' if comment_id else ''
    return Request(f'/comments/{post_id}{suffix}.json',
                   _query(limit=THREAD_LIMIT, depth=THREAD_DEPTH, sort=_comment_sort(sort), context=context),
                   expect='post_pair')


def subtree(post_id, comment_id, sort):
    """One comment and what hangs under it ('continue this thread')."""
    return post(post_id, sort, comment_id, context=0)


def morechildren(post_id, ids, sort):
    if not 1 <= len(ids) <= BATCH or any(not re.fullmatch(_ID, i) for i in ids):
        raise RedditError(2, 'A comment expansion takes 1 to 100 comment ids.', 'Report this as a skill bug.')
    return Request('/api/morechildren.json', {'api_type': 'json', 'link_id': f't3_{post_id}', 'children': ','.join(ids),
                                              'sort': _comment_sort(sort)}, expect='morechildren')


def profile(user, kind, sort, time=None, after=None):
    path = {'overview': 'overview', 'posts': 'submitted', 'comments': 'comments'}[kind]
    return Request(f'/user/{user}/{path}.json', _query(limit=PAGE_SIZE, sort=sort, t=time, after=after))


def search(text, kind, sort, time=None, sub=None, nsfw=False, after=None):
    values = _query(limit=PAGE_SIZE, q=text, type={'posts': 'link', 'subs': 'sr', 'users': 'user'}[kind], sort=sort,
                    t=time, after=after)
    if sub:
        values['restrict_sr'] = 1
    if nsfw:
        values['include_over_18'] = 'on'
    return Request(f'/r/{sub}/search.json' if sub else '/search.json', values)


def related(post_id, after=None):
    return Request(f'/duplicates/{post_id}.json', _query(limit=PAGE_SIZE, after=after), expect='duplicates')


def mine(collection, name, after=None):
    """The user's own lists; saved and upvoted are read under the logged-in name the account check returned."""
    path = '/subreddits/mine/subscriber.json' if collection == 'subs' else f'/user/{name}/{collection}.json'
    return Request(path, _query(limit=PAGE_SIZE, after=after), personal=True)


def community(sub):
    return Request(f'/r/{sub}/about.json', expect='thing:t5')


def rules(sub):
    return Request(f'/r/{sub}/about/rules.json', expect='rules')


def moderators(sub):
    return Request(f'/r/{sub}/about/moderators.json', expect='moderators')


def pinned(sub):
    """The first page of hot: Reddit puts a community's pinned posts at its top (P2 R5: one request with the whole
    records, where about/sticky.json costs a redirect and a request per slot)."""
    return Request(f'/r/{sub}/hot.json', {'limit': 10})


def wiki_page(sub, page):
    return Request(f'/r/{sub}/wiki/{page}.json', expect='wiki_page')


def wiki_index(sub):
    return Request(f'/r/{sub}/wiki/pages.json', expect='wiki_index')


def user(name):
    return Request(f'/user/{name}/about.json', expect='thing:t2')


def me():
    return Request('/api/me.json', expect='me')


def share(url):
    return Request(None, url=url, expect='page')
