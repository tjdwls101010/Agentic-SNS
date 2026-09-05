"""Normalize Facebook handles before any authenticated request."""
import html
import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit, unquote

from _errors import FacebookError

BASE = 'https://www.facebook.com'
_RESERVED = {'groups', 'reel', 'watch', 'hashtag', 'events', 'marketplace', 'stories',
             'story.php', 'permalink.php', 'photo', 'photo.php', 'media', 'pages', 'search',
             'notes', 'video', 'videos', 'live', 'gaming', 'help', 'policies', 'privacy',
             'ads', 'login', 'checkpoint', 'people'}


def _url(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ('http', 'https') or
                parsed.hostname not in ('facebook.com', 'www.facebook.com', 'm.facebook.com', 'mbasic.facebook.com') or
                parsed.username or parsed.password or parsed.port is not None or
                any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value or
                any(p in ('.', '..') for p in unquote(parsed.path).split('/'))):
            raise ValueError
    except ValueError:
        raise FacebookError(2, 'Expected a Facebook URL without credentials, ports, or path traversal.') from None
    return parsed


def normalize_profile(value):
    value = value.strip()
    if re.fullmatch(r'[0-9]+', value):
        return BASE + '/profile.php?id=' + value
    if value.lower() in _RESERVED:
        raise FacebookError(2, 'This Facebook surface is not a profile.')
    if re.fullmatch(r'[A-Za-z0-9.]+', value) and value not in ('.', '..'):
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
        profile = re.fullmatch(r'/([A-Za-z0-9.]+)(?:/about)?/?', parsed.path)
        if profile and profile.group(1).lower() not in _RESERVED:
            return BASE + '/' + profile.group(1)
    raise FacebookError(2, 'Expected a profile URL, vanity name, or numeric profile id.')


def normalize_group(value):
    value = value.strip()
    if re.fullmatch(r'[A-Za-z0-9._-]+', value) and value not in ('.', '..'):
        return BASE + '/groups/' + value + '/'
    parsed = _url(value)
    match = re.fullmatch(r'/groups/([A-Za-z0-9._-]+)/?', parsed.path)
    if not match:
        raise FacebookError(2, 'Expected a group id, vanity name, or group URL.')
    return BASE + '/groups/' + match.group(1) + '/'


def normalize_post(value):
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
    raise FacebookError(2, 'Expected a Facebook post permalink, not a profile or feed URL.')


def _body(transport, url):
    value = transport.html(url)['body']
    if isinstance(value, bytes):
        value = value.decode('utf-8', errors='replace')
    return html.unescape(value)


def resolve_profile_id(transport, identifier):
    url = normalize_profile(identifier)
    direct = parse_qs(urlsplit(url).query).get('id')
    if direct:
        return direct[0]
    match = re.search(r'"userID"\s*:\s*"(\d+)"', _body(transport, url))
    if not match:
        raise FacebookError(6, 'Could not resolve the target profile id.', 'Check the profile URL in the browser.')
    return match.group(1)


def resolve_group_id(transport, identifier):
    url = normalize_group(identifier)
    slug = urlsplit(url).path.split('/')[2]
    if slug.isascii() and slug.isdigit():
        return slug
    match = re.search(r'"(?:groupID|group_id)"\s*:\s*"?(\d+)', _body(transport, url))
    if not match:
        raise FacebookError(6, 'Could not resolve the target group id.', 'Use a numeric group id from search --type groups.')
    return match.group(1)


def resolve_story_id(transport, url):
    match = re.search(r'"storyID"\s*:\s*"([^"]+)"', _body(transport, normalize_post(url)))
    if not match:
        raise FacebookError(6, 'Could not resolve the post story id.', 'Check the post URL in the browser.')
    return match.group(1)
