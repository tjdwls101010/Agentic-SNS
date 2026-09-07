"""Local identifiers only; a domain id's redirect is resolved by the budgeted transport."""
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from ._errors import NaverBlogError

HOSTS = {'blog.naver.com', 'm.blog.naver.com', 'www.blog.naver.com'}
# Numeric-only blog ids exist, so this cannot exclude digits; log numbers vary in length.
BLOG_ID = r'[A-Za-z0-9_-]{1,64}'
# Naver has never published a log-number width and it has varied, so length is not a format
# claim here; 40 digits is only a bound on what a single identifier may be.
LOG_NO = r'[0-9]{1,40}'
# Routes that look like a blog id but are Naver's own pages.
RESERVED = {'postview.naver', 'postlist.naver', 'nblogtop.naver', 'feedlist.naver', 'buddylist.naver',
            'mobilerrorview.naver', 'mobileerrorview.naver', 'prologue.naver', 'guestbook.naver',
            'sectionlist.naver', 'postwrite.naver', 'notice', 'admin', 'section', 'api', 'ajax'}
# The reserved routes that carry a readable target in their query; the rest are refused outright.
READABLE_ROUTES = {'postview.naver', 'postlist.naver', 'nblogtop.naver', 'prologue.naver'}


@dataclass
class Target:
    kind: str
    blog_id: str = ''
    log_no: str = ''
    category_no: str | None = None
    text: str = ''

    @property
    def handle(self):
        return f'{self.blog_id}/{self.log_no}' if self.log_no else self.blog_id

    @property
    def url(self):
        return 'https://blog.naver.com/' + self.handle


def _from_query(query):
    values = parse_qs(query)
    return {key: values[key][0] for key in ('blogId', 'logNo', 'categoryNo') if values.get(key)}


def parse_target(value, kind):
    """kind is what the command can use: 'blog', 'post', or 'either'."""
    text = str(value).strip()
    if any(text.lower().startswith(host + '/') for host in HOSTS):
        text = 'https://' + text
    query = {}
    if '://' in text:
        try:
            parsed = urlsplit(text)
            if (parsed.scheme not in ('http', 'https') or (parsed.hostname or '').lower() not in HOSTS
                    or parsed.port or parsed.username or parsed.password):
                raise ValueError
        except ValueError:
            if 'naver.me/' in text:
                raise NaverBlogError(2, 'naver.me short links are not resolved by this reader.',
                                     'Open the link once and pass the blog.naver.com URL it lands on.') from None
            raise NaverBlogError(2, 'Expected a Naver Blog URL on blog.naver.com or m.blog.naver.com.') from None
        query = _from_query(parsed.query)
        text = parsed.path
    elif 'naver.me/' in text.lower():
        raise NaverBlogError(2, 'naver.me short links are not resolved by this reader.',
                             'Open the link once and pass the blog.naver.com URL it lands on.')
    text = text.strip('/')

    blog_id = query.get('blogId', '')
    log_no = query.get('logNo', '')
    category = query.get('categoryNo')
    parts = [part for part in text.split('/') if part]
    # The path is checked even when the query already names the target: a query is not a
    # licence to visit /PostWrite.naver, and a route this reader cannot read is refused whole.
    if parts and parts[0].lower() in RESERVED:
        if parts[0].lower() not in READABLE_ROUTES or len(parts) > 1:
            raise NaverBlogError(2, 'This Naver Blog route is outside the reading surface.',
                                 'Pass a blog id, id/logNo, or a blog.naver.com post URL.')
        parts = []
    if not blog_id:
        if len(parts) == 1 and re.fullmatch(BLOG_ID, parts[0]):
            blog_id = parts[0]
        elif len(parts) == 2 and re.fullmatch(BLOG_ID, parts[0]) and re.fullmatch(LOG_NO, parts[1]):
            blog_id, log_no = parts
        elif parts:
            raise NaverBlogError(2, 'This Naver Blog route is outside the reading surface.',
                                 'Pass a blog id, id/logNo, or a blog.naver.com post URL.')
    elif len(parts) > 1 or (parts and not re.fullmatch(BLOG_ID, parts[0])):
        raise NaverBlogError(2, 'This Naver Blog route is outside the reading surface.',
                             'Pass a blog id, id/logNo, or a blog.naver.com post URL.')
    elif parts and parts[0] != blog_id:
        # The address names one blog and its query another; guessing which was meant is worse.
        raise NaverBlogError(2, 'This URL names two different blogs.',
                             f'Pass just one: {parts[0]} or {blog_id}.')
    if category is not None and not re.fullmatch(r'[0-9]{1,10}', category):
        raise NaverBlogError(2, 'A category number is digits only.',
                             'Pass --category with the number shown by the blog command.')
    if not blog_id or not re.fullmatch(BLOG_ID, blog_id):
        raise NaverBlogError(2, f'Expected a Naver Blog {kind} id or URL.')
    if log_no and not re.fullmatch(LOG_NO, log_no):
        raise NaverBlogError(2, 'A post number is digits only.')
    if kind == 'post' and not log_no:
        raise NaverBlogError(2, 'This command needs one post: pass id/logNo or a post URL.')
    if kind == 'blog' and log_no:
        # A post URL names a blog too; keeping the post number would silently widen the request.
        log_no = ''
    return Target('post' if log_no else 'blog', blog_id=blog_id, log_no=log_no, category_no=category)
