"""What a user-typed target means on Threads, decided before any request.

Hosts are threads.com and threads.net with or without www; no port, no user info. A handle is [A-Za-z0-9_.]{1,30},
compared lowercased; a few top-level paths are reserved screens, not handles. A post is /@<name>/post/<code>, /t/<code>
or a bare shortcode, and its id is the shortcode read as base64url digits, so it needs no request.
"""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from threads.errors import ThreadsError

ORIGIN = 'https://www.threads.com'
HOSTS = {'threads.com', 'www.threads.com', 'threads.net', 'www.threads.net'}
NAME = r'[A-Za-z0-9_.]{1,30}'
CODE = r'[A-Za-z0-9_-]+'
TABS = ('threads', 'replies', 'reposts', 'media')
RESERVED = {'activity', 'settings', 'search', 'liked', 'saved'}
DIGITS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'
_READ_ROUTE = re.compile(r'/(?:|search|following/?|liked/?|saved/?|@[A-Za-z0-9_.]+(?:/(?:threads|replies|reposts|media|'
                         r'post/[A-Za-z0-9_-]+))?/?|t/[A-Za-z0-9_-]+/?)')
_HELP = 'Pass a Threads @handle, profile URL, post URL or shortcode.'


@dataclass(frozen=True)
class UserTarget:
    username: str
    tab: str  # the tab a profile URL names (/replies ...), '' when none

    @property
    def path(self):
        return '/@' + self.username

    @property
    def url(self):
        return ORIGIN + self.path


@dataclass(frozen=True)
class PostTarget:
    username: str  # '' when only the shortcode is known
    code: str

    @property
    def path(self):
        return f'/@{self.username}/post/{self.code}' if self.username else '/t/' + self.code

    @property
    def url(self):
        return ORIGIN + self.path

    @property
    def post_id(self):
        return shortcode_id(self.code)


def shortcode_id(code):
    """The numeric post id a shortcode encodes (base64url digits, most significant first)."""
    number = 0
    for char in code:
        number = number * 64 + DIGITS.index(char)
    return str(number)


def route_allowed(path):
    """Whether a local path is on the read surface (a query string is allowed)."""
    if not isinstance(path, str) or not path.startswith('/') or path.startswith('//') or '\\' in path or '#' in path:
        return False
    try:
        parts = urlsplit(path)
    except ValueError:
        return False
    if parts.scheme or parts.netloc:
        return False
    return bool(_READ_ROUTE.fullmatch(parts.path))


def _local_path(value):
    text = str(value).strip()
    if any(text.lower().startswith(host + '/') for host in HOSTS):
        text = 'https://' + text
    if '://' in text:
        try:
            parts = urlsplit(text)
            if (parts.scheme not in ('http', 'https') or parts.hostname not in HOSTS or parts.port
                    or parts.username or parts.password):
                raise ValueError
        except ValueError:
            raise ThreadsError(2, 'Expected a Threads URL on threads.com or threads.net.', _HELP) from None
        text = parts.path
    return text.rstrip('/')


def parse_user(value):
    """A profile target: @handle, handle, or a profile URL (a tab suffix selects that tab)."""
    text = _local_path(value)
    match = re.fullmatch(r'/?@?(' + NAME + r')(?:/(' + '|'.join(TABS) + r'))?', text)
    if not match or text.startswith('//') or match[1].lower() in RESERVED:
        raise ThreadsError(2, 'Expected a Threads @handle or profile URL.', _HELP)
    return UserTarget(match[1].lower(), match[2] or '')


def parse_post(value):
    """A post target: a post URL (/@name/post/code or /t/code) or a bare shortcode."""
    text = _local_path(value)
    match = re.fullmatch(r'/@(' + NAME + r')/post/(' + CODE + ')', text)
    if match:
        return PostTarget(match[1].lower(), match[2])
    match = re.fullmatch(r'(?:/t/)?(' + CODE + ')', text)
    if match:
        return PostTarget('', match[1])
    raise ThreadsError(2, 'Expected a Threads post URL or shortcode.', _HELP)
