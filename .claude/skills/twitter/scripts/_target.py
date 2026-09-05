"""Normalize X identities without resolving arbitrary URLs."""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit
from ._errors import TwitterError


@dataclass
class Target:
    kind: str
    handle: str | None = None
    user_id: str | None = None
    tweet_id: str | None = None
    list_id: str | None = None
    community_id: str | None = None


def parse(value, kind):
    value = value.strip()
    if value.isdigit() and kind in ('post', 'list', 'community'):
        return Target(kind, **{dict(post='tweet_id', list='list_id', community='community_id')[kind]: value})
    if '://' in value or '/' in value or value.startswith(('x.com', 'twitter.com')):
        try:
            url = urlsplit('https://x.com' + value if value.startswith('/') else value if '://' in value else 'https://' + value)
            port = url.port
        except ValueError:
            raise TwitterError(2, 'Invalid X URL.', 'Pass a valid HTTPS x.com URL without a port.') from None
        hosts = {prefix + host for prefix in ('', 'www.', 'mobile.', 'm.') for host in ('x.com', 'twitter.com')}
        if url.hostname == 't.co':
            raise TwitterError(2, 'Short links are not supported.', 'Open the t.co link and pass the x.com URL.')
        if url.scheme != 'https' or url.hostname not in hosts or url.username or url.password or port is not None:
            raise TwitterError(2, 'Expected an HTTPS X URL.', 'Pass an x.com URL or @handle.')
        path = url.path.rstrip('/')
        patterns = {'user': r'/([A-Za-z0-9_]{1,15})', 'post': r'/(?:[A-Za-z0-9_]+/status|i/web/status)/(\d+)(?:/(?:photo|video)/\d+|/analytics)?', 'list': r'/i/lists/(\d+)', 'community': r'/i/communities/(\d+)'}
        match = re.fullmatch(patterns[kind], path)
        value = match[1] if match else ''
    value = value.removeprefix('@')
    if kind == 'user' and re.fullmatch(r'[A-Za-z0-9_]{1,15}', value) and not value.isdigit() and value.lower() not in {'home', 'i', 'messages', 'notifications', 'settings', 'search', 'explore'}:
        return Target(kind, handle=value)
    if kind != 'user' and value.isdigit():
        return parse(value, kind)
    raise TwitterError(2, f'Invalid {kind} target.', 'Use a handle for profiles; use an X URL or numeric ID for posts, lists and communities.')
