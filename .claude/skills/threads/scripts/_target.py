"""Local identifiers only; redirects are resolved by the budgeted transport."""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from ._errors import ThreadsError

HOSTS = {'threads.com', 'www.threads.com', 'threads.net', 'www.threads.net'}
NAME = r'[A-Za-z0-9_.]{1,30}'
CODE = r'[A-Za-z0-9_-]+'


@dataclass
class Target:
    kind: str
    username: str = ''
    code: str = ''
    user_id: str = ''
    post_id: str = ''

    @property
    def path(self):
        if self.kind == 'user':
            return '/@' + self.username
        return f'/@{self.username}/post/{self.code}' if self.username else '/t/' + self.code


def parse_target(value, kind):
    text = str(value).strip()
    if any(text.lower().startswith(h + '/') for h in HOSTS):
        text = 'https://' + text
    if '://' in text:
        try:
            u = urlsplit(text)
            if u.scheme not in ('http', 'https') or u.hostname not in HOSTS or u.port or u.username or u.password:
                raise ValueError
            text = u.path
        except ValueError:
            raise ThreadsError(2, 'Expected a Threads URL on its standard host.') from None
    text = text.rstrip('/')
    if kind == 'user':
        match = re.fullmatch(r'/?@?(' + NAME + r')(?:/(threads|replies|reposts|media))?', text)
        if match and not text.startswith('//') and match[1] not in ('activity', 'settings', 'search', 'liked', 'saved'):
            return Target('user', username=match[1].lower())
    if kind == 'post':
        match = re.fullmatch(r'/@(' + NAME + r')/post/(' + CODE + ')', text)
        if match:
            return Target('post', username=match[1].lower(), code=match[2])
        match = re.fullmatch(r'(?:/t/)?(' + CODE + ')', text)
        if match:
            return Target('post', code=match[1])
    raise ThreadsError(2, f'Expected a Threads {kind} handle or URL; this route is outside the reading surface.')
