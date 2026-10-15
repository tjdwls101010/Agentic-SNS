"""Facebook's URL forms: what a profile, page, group or post looks like as typed, normalized before any request."""
import html
import re
from urllib.parse import parse_qs, unquote, urlencode, urlsplit, urlunsplit

from facebook.errors import FacebookError

BASE = 'https://www.facebook.com'
HOSTS = ('facebook.com', 'www.facebook.com', 'm.facebook.com', 'mbasic.facebook.com', 'web.facebook.com')
# First path segments that are Facebook surfaces, not profiles or pages.
RESERVED = {'groups', 'reel', 'reels', 'watch', 'hashtag', 'events', 'marketplace', 'stories', 'story.php',
            'permalink.php', 'photo', 'photo.php', 'media', 'pages', 'search', 'notes', 'video', 'videos', 'live',
            'gaming', 'help', 'policies', 'privacy', 'ads', 'login', 'checkpoint', 'people', 'friends', 'messages',
            'notifications', 'settings', 'bookmarks', 'saved', 'share', 'sharer', 'l.php'}
_FIX = 'Pass a facebook.com URL, a vanity name or a numeric id.'


def _url(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or parsed.hostname not in HOSTS or parsed.username
                or parsed.password or parsed.port is not None or any(c.isspace() or ord(c) < 32 for c in value)
                or '\\' in value or any(part in ('.', '..') for part in unquote(parsed.path).split('/'))):
            raise ValueError
    except ValueError:
        raise FacebookError(2, 'Expected a facebook.com URL without credentials, ports or path traversal.', _FIX) from None
    return parsed


def profile(value):
    """A profile or page as https://www.facebook.com/<vanity> or …/profile.php?id=<id>."""
    value = value.strip()
    if re.fullmatch(r'[0-9]+', value):
        return BASE + '/profile.php?id=' + value
    if value.lower() in RESERVED:
        raise FacebookError(2, f'"{value}" is a Facebook surface, not a profile or page.', _FIX)
    if re.fullmatch(r'[A-Za-z0-9.]+', value) and value.strip('.'):
        return BASE + '/' + value
    if value.startswith('profile.php?'):
        value = BASE + '/' + value
    parsed = _url(value)
    people = re.fullmatch(r'/people/[^/]+/([0-9]+)/?', parsed.path)
    if people:
        return BASE + '/profile.php?id=' + people.group(1)
    if parsed.path.rstrip('/') == '/profile.php':
        ident = parse_qs(parsed.query).get('id', [''])[0]
        if ident.isascii() and ident.isdigit():
            return BASE + '/profile.php?id=' + ident
    else:
        match = re.fullmatch(r'/([A-Za-z0-9.]+)(?:/(?:about|posts|photos|videos|reels)\S*)?/?', parsed.path)
        if match and match.group(1).lower() not in RESERVED and match.group(1).strip('.'):
            return BASE + '/' + match.group(1)
    raise FacebookError(2, 'Expected a profile or page: a URL, a vanity name or a numeric id.', _FIX)


def group(value):
    """A group as https://www.facebook.com/groups/<id or vanity>/."""
    value = value.strip()
    if re.fullmatch(r'[A-Za-z0-9._-]+', value) and value.strip('.'):
        return BASE + '/groups/' + value + '/'
    parsed = _url(value)
    match = re.fullmatch(r'/groups/([A-Za-z0-9._-]+)/?', parsed.path)
    if not match or not match.group(1).strip('.'):
        raise FacebookError(2, 'Expected a group: its /groups/ URL, vanity name or numeric id.', _FIX)
    return BASE + '/groups/' + match.group(1) + '/'


def post(value):
    """A post permalink in one canonical form."""
    parsed = _url(value.strip())
    query = parse_qs(parsed.query)
    path = parsed.path.rstrip('/')
    if re.fullmatch(r'/(?:[^/]+/posts|groups/[^/]+/(?:posts|permalink)|[^/]+/videos)/[^/]+', path):
        return BASE + path
    if path in ('/permalink.php', '/story.php') and query.get('story_fbid') and query.get('id'):
        return urlunsplit(('https', 'www.facebook.com', '/permalink.php',
                           urlencode({'story_fbid': query['story_fbid'][0], 'id': query['id'][0]}), ''))
    if path in ('/photo.php', '/photo') and query.get('fbid'):
        return BASE + '/photo.php?' + urlencode({'fbid': query['fbid'][0]})
    raise FacebookError(2, 'Expected a Facebook post permalink, not a profile or feed URL.', 'Open the post and copy '
                                                                                             'its own URL.')


def is_group(value):
    return '/groups/' in value


def direct_profile_id(url):
    ident = parse_qs(urlsplit(url).query).get('id')
    return ident[0] if ident else None


def direct_group_id(url):
    slug = urlsplit(url).path.split('/')[2]
    return slug if slug.isascii() and slug.isdigit() else None


def find_id(kind, page):
    """The numeric id a fetched page names for its profile, group or story; None when absent."""
    text = html.unescape(page)
    pattern = {'profile': r'"userID"\s*:\s*"(\d+)"', 'group': r'"(?:groupID|group_id)"\s*:\s*"?(\d+)',
               'post': r'"storyID"\s*:\s*"([^"]+)"'}[kind]
    match = re.search(pattern, text)
    return match.group(1) if match else None
