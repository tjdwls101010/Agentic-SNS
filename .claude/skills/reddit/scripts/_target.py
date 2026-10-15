"""Local Reddit target parsing; only share targets need network resolution."""
from dataclasses import dataclass
import re
from urllib.parse import unquote, urlsplit

from ._errors import RedditError

_HOSTS = {'reddit.com', 'www.reddit.com', 'old.reddit.com', 'np.reddit.com', 'sh.reddit.com', 'redd.it'}


@dataclass(frozen=True)
class Target:
    kind: str
    sub: str | None = None
    post_id: str | None = None
    comment_id: str | None = None
    user: str | None = None
    name: str | None = None


def _invalid():
    return RedditError(2, 'Invalid or unsupported Reddit target.',
                       'Use r/name, u/name, a post id or a Reddit post/comment URL.')


def _checked(value, pattern):
    if not re.fullmatch(pattern, value):
        raise _invalid()
    return value


def parse_target(value):
    """Return a Target without making requests; share.name is its canonical URL."""
    if not isinstance(value, str) or not value.strip():
        raise _invalid()
    value = value.strip().split('?', 1)[0].split('#', 1)[0]
    if re.search(r'[\\\s]', value) or value.startswith('//'):
        raise _invalid()
    host = None
    if '://' in value or any(value.lower().startswith(h + '/') for h in _HOSTS):
        try:
            parts = urlsplit(value if '://' in value else 'https://' + value)
            if parts.scheme not in {'http', 'https'} or parts.netloc.lower() not in _HOSTS:
                raise _invalid()
            host = parts.netloc.lower()
            value = parts.path
        except ValueError:
            raise _invalid() from None
    else:
        value = value.split('?', 1)[0].split('#', 1)[0]
    segments = value.strip('/').split('/')
    if any(s in {'', '.', '..'} for s in segments):
        raise _invalid()
    if host == 'redd.it':
        if len(segments) != 1:
            raise _invalid()
        return Target('post', post_id=_checked(segments[0], r'[A-Za-z0-9]{1,10}').lower())
    if len(segments) == 1 and host is None and not value.startswith('/'):
        if value == 'me':
            return Target('me', user='me')
        return Target('post', post_id=_checked(value.removeprefix('t3_'), r'[A-Za-z0-9]{1,10}').lower())
    if segments[0] in {'u', 'user'} and len(segments) == 2:
        user = 'me' if segments[1] == 'me' else _checked(segments[1], r'[A-Za-z0-9_-]{3,20}')
        return Target('me' if user == 'me' else 'user', user=user, name=user)
    sub = None
    if segments[0] == 'r' and len(segments) >= 2:
        names = segments[1].split('+')
        if len(names) > 10:
            raise _invalid()
        for name in names:
            _checked(name, r'[A-Za-z0-9_]{1,21}')
        sub = segments[1]
        if len(segments) == 2:
            return Target('subreddits' if len(names) > 1 else 'subreddit', sub=sub, name=sub)
        if len(names) != 1:
            raise _invalid()
        segments = segments[2:]
    if sub and len(segments) == 2 and segments[0] == 's':
        token = _checked(segments[1], r'[A-Za-z0-9]+')
        return Target('share', sub=sub, name=f'https://www.reddit.com/r/{sub}/s/{token}')
    if segments[0] not in {'comments', 'gallery'} or not 2 <= len(segments) <= 4:
        raise _invalid()
    if segments[0] == 'gallery' and (len(segments) != 2 or sub):
        raise _invalid()
    post_id = _checked(segments[1].removesuffix('.json'), r'[A-Za-z0-9]{1,10}').lower()
    if len(segments) >= 3:
        slug = segments[2]
        try:
            if re.search(r'%(?![0-9A-Fa-f]{2})', slug):
                raise ValueError
            decoded = unquote(slug, errors='strict')
            if decoded in {'.', '..'} or re.search(r'[/\\%\x00-\x1f\x7f]', decoded):
                raise ValueError
        except (UnicodeError, ValueError):
            raise _invalid() from None
    comment_id = None
    if len(segments) == 4:
        comment_id = _checked(segments[3].removesuffix('.json'), r'[A-Za-z0-9]{1,10}').lower()
    return Target('comment' if comment_id else 'post', sub=sub, post_id=post_id, comment_id=comment_id)
