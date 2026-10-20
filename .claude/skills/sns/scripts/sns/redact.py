"""Cookie, token and signature names of the five platforms, and the signed image hosts whose query strings are
credentials: what a diagnostic or a saved capture must never carry."""
import re
from urllib.parse import urlsplit, urlunsplit

SENSITIVE = {
    # shared
    'token', 'access_token', 'cookie', 'cookies', 'authorization', 'csrf', 'sessionid', 'bearer',
    # Meta (Threads, Facebook)
    'fb_dtsg', 'lsd', 'jazoest', 'datr', 'sb', 'c_user', 'xs', 'csrftoken', 'ds_user_id', 'mid', 'x-csrftoken',
    'x-fb-lsd', '__hs', '__hsi', '__dyn', '__csr', '__spin_t', '__s', '__aaid', '__hsdp', '__hblp', '__sjsp', '__crn',
    # X
    'ct0', 'auth_token', 'twid', 'x-csrf-token', 'x-client-transaction-id', 'guest_id', 'kdt', 'att',
    # Reddit
    'reddit_session', 'token_v2', 'loid', 'session_tracker', 'csrf_token', 'modhash', 'x-modhash', 'edgebucket',
    # Naver
    'nid_aut', 'nid_ses', 'nid_jkl', 'nid_inf', 'nnb', 'userkey', 'bauserkey', 'useridno', 'idno', 'naverid',
}
# Image hosts whose URLs carry a signature or a viewer-bound token in the query string.
SIGNED_HOSTS = ('fbcdn.net', 'cdninstagram.com', 'pbs.twimg.com', 'redd.it', 'pstatic.net')
MARK = '[REDACTED]'

_KEYS = '|'.join(re.escape(key) for key in sorted(SENSITIVE, key=len, reverse=True))
_JSON_SECRET = re.compile(r'"(' + _KEYS + r')"\s*:\s*"(?:\\.|[^"\\])*"', re.I)
_FORM_SECRET = re.compile(r'(?<![A-Za-z0-9_-])(' + _KEYS + r')\s*[:=]\s*[^\s;&"\',}]+', re.I)
_BEARER = re.compile(r'(?i)(Bearer\s+)\S+')
_URL = re.compile(r'https?://[^\s"\'<>]+')


def _signed(host):
    return any(host == cdn or host.endswith('.' + cdn) for cdn in SIGNED_HOSTS)


def _url(match):
    try:
        parts = urlsplit(match[0])
        if _signed((parts.hostname or '').lower()):
            return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
    except ValueError:
        return '[INVALID URL]'
    return match[0]


def scrub(value):
    """A copy with cookie, token and signature fields redacted and signed image query strings removed."""
    if isinstance(value, dict):
        return {key: MARK if str(key).lower() in SENSITIVE else scrub(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(child) for child in value]
    if not isinstance(value, str):
        return value
    value = _BEARER.sub(lambda m: m[1] + MARK, value)
    value = _JSON_SECRET.sub(lambda m: '"' + m[1] + '":"' + MARK + '"', value)
    value = _FORM_SECRET.sub(lambda m: m[1] + '=' + MARK, value)
    return _URL.sub(_url, value)
