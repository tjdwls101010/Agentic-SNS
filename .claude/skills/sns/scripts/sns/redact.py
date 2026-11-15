"""Cookie, token and signature names of the five platforms, and the signed image hosts whose query strings are
credentials: what a diagnostic or a saved capture must never carry."""
import re
from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from sns.platforms import adapters

SENSITIVE = {'token', 'access_token', 'cookie', 'cookies', 'authorization', 'csrf', 'sessionid', 'bearer'}
MARK = '[REDACTED]'


@lru_cache(maxsize=1)
def _rules():
    platforms = adapters()
    sensitive = SENSITIVE | {name for platform in platforms for name in platform.secret_fields}
    hosts = tuple(host for platform in platforms for host in platform.signed_image_hosts)
    keys = '|'.join(re.escape(key) for key in sorted(sensitive, key=len, reverse=True))
    json_secret = re.compile(r'"(' + keys + r')"\s*:\s*"(?:\\.|[^"\\])*"', re.I)
    form_secret = re.compile(r'(?<![A-Za-z0-9_-])(' + keys + r')\s*[:=]\s*[^\s;&"\',}]+', re.I)
    return sensitive, hosts, json_secret, form_secret


_BEARER = re.compile(r'(?i)(Bearer\s+)\S+')
_URL = re.compile(r'https?://[^\s"\'<>]+')


def _signed(host):
    return any(host == cdn or host.endswith('.' + cdn) for cdn in _rules()[1])


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
        return {key: MARK if str(key).lower() in _rules()[0] else scrub(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(child) for child in value]
    if not isinstance(value, str):
        return value
    value = _BEARER.sub(lambda m: m[1] + MARK, value)
    value = _rules()[2].sub(lambda m: '"' + m[1] + '":"' + MARK + '"', value)
    value = _rules()[3].sub(lambda m: m[1] + '=' + MARK, value)
    return _URL.sub(_url, value)
