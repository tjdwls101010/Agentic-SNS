"""What a typed X target is, decided without any request: an account, a post, a list, a community or a space.

Hosts are x.com and twitter.com (bare, www., mobile., m.), https only, without a port or user info; a URL without a
scheme is read as https. t.co is refused: its destination is only known by opening it.
"""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from sns.errors import SnsError

ORIGIN = 'https://x.com'
_HOSTS = {prefix + host for prefix in ('', 'www.', 'mobile.', 'm.') for host in ('x.com', 'twitter.com')}
_HANDLE = re.compile(r'[A-Za-z0-9_]{1,15}')
# X's own top-level paths, which are never handles
_RESERVED = {'home', 'i', 'messages', 'notifications', 'settings', 'search', 'explore', 'compose', 'login', 'logout',
             'signup', 'tos', 'privacy', 'account', 'intent', 'share', 'hashtag', 'jobs'}
# A profile URL's tab path → the profile tab it shows; the graph paths name the account only
_TABS = {'with_replies': 'replies', 'media': 'media', 'highlights': 'highlights', 'articles': 'articles',
         'lists': 'lists', 'lists/memberships': 'memberships'}
_PLURAL = {'list': 'lists', 'community': 'communities', 'space': 'spaces'}
_ACCOUNT_PATHS = set(_TABS) | {'followers', 'following', 'verified_followers', 'followers_you_follow', ''}
_FIXES = {
    'account': 'Pass an @handle or an x.com profile URL.',
    'post': 'Pass an x.com post URL (/<handle>/status/<id>) or the numeric post id.',
    'list': 'Pass an x.com/i/lists/<id> URL or the numeric list id.',
    'community': 'Pass an x.com/i/communities/<id> URL or the numeric community id.',
    'space': 'Pass an x.com/i/spaces/<id> URL.',
}


@dataclass(frozen=True)
class Account:
    handle: str
    tab: str | None = None

    @property
    def url(self):
        return f'{ORIGIN}/{self.handle}'


@dataclass(frozen=True)
class Post:
    post_id: str
    handle: str | None = None

    @property
    def url(self):
        return f'{ORIGIN}/{self.handle or "i/web"}/status/{self.post_id}'


@dataclass(frozen=True)
class Place:
    kind: str
    place_id: str

    @property
    def list_id(self):
        return self.place_id

    @property
    def community_id(self):
        return self.place_id

    @property
    def space_id(self):
        return self.place_id

    @property
    def url(self):
        return f'{ORIGIN}/i/{_PLURAL[self.kind]}/{self.place_id}'


def _refuse(kind, message=None):
    return SnsError('argument', message or f'That is not an X {kind}.', _FIXES[kind])


def _path(value, kind):
    """The path of an X URL, or None when `value` is not a URL; foreign or unsafe URLs are refused."""
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise SnsError('argument', 'The target contains a line break or another control character.', 'Pass it on one line.')
    if '://' not in value and '/' not in value and not value.lower().startswith(('x.com', 'twitter.com')):
        return None
    try:
        url = urlsplit(value if '://' in value else 'https://' + value.lstrip('/'))
        port = url.port
    except ValueError:
        raise _refuse(kind, 'That is not a valid URL.') from None
    host = (url.hostname or '').lower()
    if host == 't.co':
        raise SnsError('argument', 'A t.co short link hides where it goes.', 'Open it and pass the x.com URL it lands on.')
    if url.scheme != 'https':
        raise _refuse(kind, 'Only https X URLs are read.')
    if host not in _HOSTS or url.username or url.password or port is not None:
        raise _refuse(kind, 'That is not an x.com or twitter.com URL.')
    return url.path.strip('/')


def parse_account(value):
    value = (value or '').strip()
    path = _path(value, 'account')
    tab = None
    if path is not None:
        head, _, rest = path.partition('/')
        if rest not in _ACCOUNT_PATHS:
            raise _refuse('account', 'That URL is not a profile.')
        tab, value = _TABS.get(rest), head
    handle = value[1:] if value.startswith('@') else value
    if handle.isdigit():
        raise SnsError('argument', 'Numeric user ids are not accepted.', 'Pass the @handle or the profile URL.')
    if not _HANDLE.fullmatch(handle) or handle.lower() in _RESERVED:
        raise _refuse('account', f'"{value}" is not an X handle.')
    return Account(handle, tab)


def parse_post(value):
    value = (value or '').strip()
    path = _path(value, 'post')
    if path is None:
        if value.isascii() and value.isdigit():
            return Post(value)
        raise _refuse('post')
    match = re.fullmatch(r'(?:([A-Za-z0-9_]{1,15})|i/web)/status/(\d+)(?:/(?:photo|video)/\d+|/analytics)?', path)
    if not match:
        raise _refuse('post')
    handle = match[1] if match[1] and match[1].lower() not in _RESERVED else None
    return Post(match[2], handle)


def _place(value, kind, pattern):
    value = (value or '').strip()
    path = _path(value, kind)
    if path is None:
        if kind != 'space' and value.isascii() and value.isdigit():
            return Place(kind, value)
        raise _refuse(kind)
    match = re.fullmatch(pattern, path)
    if not match:
        raise _refuse(kind)
    return Place(kind, match[1])


def parse_list(value):
    return _place(value, 'list', r'i/lists/(\d+)')


def parse_community(value):
    return _place(value, 'community', r'i/communities/(\d+)')


def parse_space(value):
    return _place(value, 'space', r'i/spaces/([A-Za-z0-9]{8,20})(?:/peek)?')


def locate(url):
    """(command, argument) when `url` is an x.com / twitter.com link and the command that reads it, else None. A pure
    function of the text: no request, and no refusal (a link this platform's parsers would refuse is still X's)."""
    value = (url or '').strip()
    try:
        parts = urlsplit(value if '://' in value else 'https://' + value.lstrip('/'))
        host = (parts.hostname or '').lower()
    except ValueError:
        return None
    if host not in _HOSTS:
        return None
    path = parts.path.strip('/')
    for command, pattern in (('post', r'(?:[A-Za-z0-9_]{1,15}|i/web)/status/\d+(?:/.*)?'), ('list', r'i/lists/\d+'),
                             ('community', r'i/communities/\d+'), ('about', r'i/spaces/[A-Za-z0-9]{8,20}(?:/peek)?')):
        if re.fullmatch(pattern, path):
            return command, value
    head = path.split('/')[0]
    if _HANDLE.fullmatch(head) and head.lower() not in _RESERVED:
        return 'profile', value
    return None
