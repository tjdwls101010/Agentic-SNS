"""What a user-typed Reddit target names, with no request: a post, a comment, a community (or an a+b combination), a
user, the logged-in user, a wiki, or a share link that only a request can resolve."""
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from sns.errors import SnsError

BASE = 'https://www.reddit.com'
_HOSTS = {'reddit.com', 'www.reddit.com', 'old.reddit.com', 'np.reddit.com', 'sh.reddit.com', 'redd.it'}
_POST_ID = r'[A-Za-z0-9]{1,10}'
_SUB = r'[A-Za-z0-9_]{1,21}'
_USER = r'[A-Za-z0-9_-]{3,20}'
_PAGE = r'[A-Za-z0-9_-]{1,64}(?:/[A-Za-z0-9_-]{1,64})?'

# Which target kinds each command takes: the one table the commands check their target against.
ACCEPTS = {
    'sub': ('subreddit', 'subreddits'),
    'post': ('post', 'comment', 'share'),
    'comments': ('post', 'comment', 'share'),
    'profile': ('user',),
    'about': ('subreddit', 'user'),
    'related': ('post', 'comment'),
    'search --in': ('subreddit',),
    'wiki': ('subreddit', 'wiki'),
}
# Which command opens a target of each kind (for a Reddit link given to another platform's command).
OPENED_BY = {'post': 'post', 'comment': 'post', 'share': 'post', 'subreddit': 'sub', 'subreddits': 'sub',
             'user': 'profile', 'wiki': 'wiki'}


@dataclass(frozen=True)
class Target:
    kind: str                   # post | comment | subreddit | subreddits | user | me | share | wiki
    sub: str | None = None
    post_id: str | None = None
    comment_id: str | None = None
    user: str | None = None
    url: str | None = None      # a share link's canonical URL
    page: str | None = None     # a wiki page name (None: the wiki's page list)

    @property
    def name(self):
        """How a result names it: r/<sub>, u/<user>, or the permalink of a post or comment."""
        if self.kind in ('subreddit', 'subreddits'):
            return f'r/{self.sub}'
        if self.kind in ('user', 'me'):
            return f'u/{self.user}'
        if self.kind == 'share':
            return self.url
        if self.kind == 'wiki':
            return f'r/{self.sub}/wiki' + (f'/{self.page}' if self.page else '')
        return permalink(self.post_id, self.comment_id)


def permalink(post_id, comment_id=None):
    return f'{BASE}/comments/{post_id}/' + (f'_/{comment_id}/' if comment_id else '')


def _invalid():
    return SnsError('argument', 'Invalid or unsupported Reddit target.',
                    'Use r/name, u/name, a post id, or a Reddit post, comment or share URL.')


def _checked(value, pattern):
    if not re.fullmatch(pattern, value):
        raise _invalid()
    return value


def parse_target(value):
    """A Target, or an argument error. Hosts are normalized (old., np., sh., no www); query and fragment are dropped;
    a post's title slug is ignored but must decode cleanly."""
    if not isinstance(value, str) or not value.strip():
        raise _invalid()
    value = value.strip()
    if re.search(r'[\\\s]', value) or value.startswith('//'):
        raise _invalid()
    value = value.split('#', 1)[0]
    host = None
    if '://' in value or any(value.lower().startswith(h + '/') for h in _HOSTS):
        try:
            parts = urlsplit(value if '://' in value else 'https://' + value)
            if parts.scheme not in ('http', 'https') or parts.netloc.lower() not in _HOSTS:
                raise _invalid()
        except ValueError:
            raise _invalid() from None
        host, value = parts.netloc.lower(), parts.path
    else:
        value = value.split('?', 1)[0]
    segments = value.strip('/').split('/')
    if any(s in ('', '.', '..') for s in segments):
        raise _invalid()
    if host == 'redd.it':
        if len(segments) != 1:
            raise _invalid()
        return Target('post', post_id=_checked(segments[0], _POST_ID).lower())
    if len(segments) == 1 and host is None and not value.startswith('/'):
        if value == 'me':
            return Target('me', user='me')
        return Target('post', post_id=_checked(value.removeprefix('t3_'), _POST_ID).lower())
    if segments[0] in ('u', 'user') and len(segments) == 2:
        if segments[1] == 'me':
            return Target('me', user='me')
        return Target('user', user=_checked(segments[1], _USER))
    sub = None
    if segments[0] == 'r' and len(segments) >= 2:
        names = segments[1].split('+')
        if len(names) > 10:
            raise _invalid()
        for name in names:
            _checked(name, _SUB)
        sub = segments[1]
        if len(segments) == 2:
            return Target('subreddits' if len(names) > 1 else 'subreddit', sub=sub)
        if len(names) != 1:
            raise _invalid()
        segments = segments[2:]
    if sub and segments[0] == 'wiki' and len(segments) <= 3:
        page = '/'.join(segments[1:]) or None
        if page is not None:
            _checked(page, _PAGE)
        return Target('wiki', sub=sub, page=page)
    if sub and len(segments) == 2 and segments[0] == 's':
        token = _checked(segments[1], r'[A-Za-z0-9]+')
        return Target('share', sub=sub, url=f'{BASE}/r/{sub}/s/{token}')
    if segments[0] not in ('comments', 'gallery') or not 2 <= len(segments) <= 4:
        raise _invalid()
    if segments[0] == 'gallery' and (len(segments) != 2 or sub):
        raise _invalid()
    post_id = _checked(segments[1].removesuffix('.json'), _POST_ID).lower()
    if len(segments) >= 3:
        slug = segments[2]
        try:
            if re.search(r'%(?![0-9A-Fa-f]{2})', slug):
                raise ValueError
            decoded = unquote(slug, errors='strict')
            if decoded in ('.', '..') or re.search(r'[/\\%\x00-\x1f\x7f]', decoded):
                raise ValueError
        except (UnicodeError, ValueError):
            raise _invalid() from None
    comment_id = None
    if len(segments) == 4:
        comment_id = _checked(segments[3].removesuffix('.json'), _POST_ID).lower()
    return Target('comment' if comment_id else 'post', sub=sub, post_id=post_id, comment_id=comment_id)


def require(target, command):
    """The target when its kind is one `command` takes (ACCEPTS), else an argument error naming them."""
    kinds = ACCEPTS[command]
    if target.kind not in kinds:
        names = {'post': 'a post', 'comment': 'a comment link', 'share': 'a share link', 'subreddit': 'r/<name>',
                 'subreddits': 'r/<a+b>', 'user': 'u/<name>', 'me': 'u/me', 'wiki': 'a wiki URL'}
        raise SnsError('argument', f'{command} takes ' + ', '.join(names[k] for k in kinds) + f', not {names[target.kind]}.',
                       f'Run {command.split()[0]} --help for its targets.')
    return target


def locate(value):
    """(command, argument) when `value` is a link to Reddit and the command that opens it, else None. Pure: it only
    reads the address (a bare id or name is not a link and belongs to no platform)."""
    if not isinstance(value, str) or not ('://' in value or any(value.lower().startswith(h + '/') for h in _HOSTS)):
        return None
    try:
        target = parse_target(value)
    except SnsError:
        return None
    command = OPENED_BY.get(target.kind)
    return (command, value) if command else None
