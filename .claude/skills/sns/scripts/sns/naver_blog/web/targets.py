"""Naver Blog targets a person can type: blog ids, id/logNo, blog URLs, and naver.me short links.

Everything here is decided locally with no request. A naver.me link cannot be read locally: it is marked short, and
the client resolves it with one counted hop, then parses the destination with these same rules.
"""
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from sns.errors import SnsError

HOSTS = {'blog.naver.com', 'm.blog.naver.com', 'www.blog.naver.com'}
SHORT_HOST = 'naver.me'
# Digit-only blog ids exist, so digits cannot be excluded.
BLOG_ID = r'[A-Za-z0-9_-]{1,64}'
# Naver has never published a log-number width and it has varied; 40 digits only bounds one identifier.
LOG_NO = r'[0-9]{1,40}'
SHORT_CODE = r'[A-Za-z0-9]{1,32}'
# Routes that look like a blog id but are Naver's own pages; only the readable ones carry a target in their query.
RESERVED = {'postview.naver', 'postlist.naver', 'nblogtop.naver', 'feedlist.naver', 'buddylist.naver',
            'mobilerrorview.naver', 'mobileerrorview.naver', 'prologue.naver', 'guestbook.naver', 'sectionlist.naver',
            'postwrite.naver', 'notice', 'admin', 'section', 'api', 'ajax'}
READABLE_ROUTES = {'postview.naver', 'postlist.naver', 'nblogtop.naver', 'prologue.naver'}
_SURFACE = 'Pass a blog id, id/logNo, a blog.naver.com URL, or a naver.me link to a post.'


@dataclass
class Target:
    """kind is what the command asked for: 'post', 'blog' or 'either'; short is a naver.me code still to resolve."""
    kind: str
    blog_id: str = ''
    log_no: str = ''
    category_no: str | None = None
    short: str = ''

    @property
    def handle(self):
        return f'{self.blog_id}/{self.log_no}' if self.log_no else self.blog_id

    @property
    def url(self):
        return 'https://blog.naver.com/' + self.handle


def parse(value, kind):
    """The target `value` names for a command of `kind`, or an argument error before any request."""
    text = str(value).strip()
    lowered = text.lower()
    if lowered.startswith((SHORT_HOST + '/', 'http://' + SHORT_HOST + '/', 'https://' + SHORT_HOST + '/')):
        code = text.split(SHORT_HOST + '/', 1)[1] if SHORT_HOST + '/' in text else text.split('/', 3)[-1]
        if not re.fullmatch(SHORT_CODE, code):
            raise SnsError('argument', 'A naver.me link is naver.me/<code> with nothing after the code.', _SURFACE)
        return Target(kind, short=code)
    if any(lowered.startswith(host + '/') or lowered == host for host in HOSTS):
        text = 'https://' + text
    query = {}
    if '://' in text:
        try:
            parsed = urlsplit(text)
            if (parsed.scheme not in ('http', 'https') or (parsed.hostname or '').lower() not in HOSTS or parsed.port
                    or parsed.username or parsed.password):
                raise ValueError
        except ValueError:
            raise SnsError('argument', 'Expected a Naver Blog URL on blog.naver.com or m.blog.naver.com.',
                           _SURFACE) from None
        values = parse_qs(parsed.query)
        query = {key: values[key][0] for key in ('blogId', 'logNo', 'categoryNo') if values.get(key)}
        text = parsed.path
    parts = [part for part in text.strip('/').split('/') if part]
    blog_id, log_no, category = query.get('blogId', ''), query.get('logNo', ''), query.get('categoryNo')
    # The path is checked even when the query names the target: a query is no licence to visit /PostWrite.naver.
    if parts and parts[0].lower() in RESERVED:
        if parts[0].lower() not in READABLE_ROUTES or len(parts) > 1:
            raise SnsError('argument', 'This Naver Blog route is outside the reading surface.', _SURFACE)
        parts = []
    if not blog_id:
        if len(parts) == 1 and re.fullmatch(BLOG_ID, parts[0]):
            blog_id = parts[0]
        elif len(parts) == 2 and re.fullmatch(BLOG_ID, parts[0]) and re.fullmatch(LOG_NO, parts[1]):
            blog_id, log_no = parts
        elif parts:
            raise SnsError('argument', 'This Naver Blog route is outside the reading surface.', _SURFACE)
    elif len(parts) > 1 or (parts and not re.fullmatch(BLOG_ID, parts[0])):
        raise SnsError('argument', 'This Naver Blog route is outside the reading surface.', _SURFACE)
    elif parts and parts[0] != blog_id:
        raise SnsError('argument', 'This URL names two different blogs.', f'Pass just one: {parts[0]} or {blog_id}.')
    if category is not None and not re.fullmatch(r'[0-9]{1,10}', category):
        raise SnsError('argument', 'A category number is digits only.', 'Pass --category with the number blog shows.')
    if not blog_id or not re.fullmatch(BLOG_ID, blog_id):
        raise SnsError('argument', f'Expected a Naver Blog {"post" if kind == "post" else "blog"} id or URL.', _SURFACE)
    if log_no and not re.fullmatch(LOG_NO, log_no):
        raise SnsError('argument', 'A post number is digits only.', _SURFACE)
    if kind == 'post' and not log_no:
        raise SnsError('argument', 'This command needs one post: pass id/logNo or a post URL.', _SURFACE)
    if kind == 'blog':
        log_no = ''  # a post URL names a blog too; keeping the post number would widen the request silently
    return Target(kind, blog_id=blog_id, log_no=log_no, category_no=category)


def destination(location, kind):
    """The target a resolved short link lands on: a blog URL by the rules above, else an argument error naming where it
    goes."""
    if not location:
        raise SnsError('unavailable', 'That naver.me link leads nowhere (no destination).', 'Check the link.',
                       reason='short_link_dead')
    try:
        host = (urlsplit(location).hostname or '').lower()
    except ValueError:
        host = ''
    if host not in HOSTS:
        raise SnsError('argument', f'That naver.me link leads to {host or "an unreadable address"}, not to a Naver Blog '
                                   f'{"post" if kind == "post" else "page"}.',
                       'Run resolve <link> to see the whole destination.', reason='not_a_blog')
    return parse(location, kind)


def locate(value):
    """(command, argument) when `value` is a Naver Blog link and that command opens it, else None. No request: a
    naver.me link may lead anywhere, so resolve is what shows where."""
    text = str(value).strip() if isinstance(value, str) else ''
    lowered = text.lower()
    if lowered.startswith(('http://naver.me/', 'https://naver.me/', 'naver.me/')):
        return 'resolve', text
    if not (lowered.split('/', 1)[0] in HOSTS or lowered.startswith(('http://', 'https://'))):
        return None
    try:
        target = parse(text, 'either')
    except SnsError:
        return None
    if target.log_no:
        return 'post', text
    return ('posts', text) if target.category_no else ('blog', text)
