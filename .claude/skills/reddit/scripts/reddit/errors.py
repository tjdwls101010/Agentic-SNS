"""The one public error type, and the single scrub path for optional diagnostics."""
import json
import re
import sys
from urllib.parse import urlsplit, urlunsplit

# Exit code → the error kind it reports. cli.py owns the codes; every unit raises with one of them.
KINDS = {2: 'argument', 3: 'aside', 4: 'login', 5: 'blocked', 6: 'failed', 7: 'empty', 8: 'budget', 9: 'unavailable'}

_SENSITIVE = {'reddit_session', 'token_v2', 'loid', 'session_tracker', 'csrf_token', 'modhash', 'edgebucket', 'token',
              'access_token', 'cookie', 'cookies', 'authorization', 'x-modhash'}
_KEYS = '|'.join(re.escape(key) for key in sorted(_SENSITIVE, key=len, reverse=True))
_JSON_SECRET = re.compile(r'"(' + _KEYS + r')"\s*:\s*"(?:\\.|[^"\\])*"', re.I)
_FORM_SECRET = re.compile(r'(?<![A-Za-z0-9_])(' + _KEYS + r')\s*[:=]\s*[^\s;&"\']+', re.I)


class RedditError(Exception):
    """A failure every caller can report: an exit code (see KINDS), what happened, and what to do next."""

    def __init__(self, code, message, fix, reason=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fix = fix
        self.reason = reason  # a finer cause a caller may act on, e.g. 'rate_limit', 'history_not_visible'

    @property
    def kind(self):
        return KINDS.get(self.code, 'failed')


def scrub(value):
    """A copy with cookie and token fields redacted and signed query strings on redd.it media hosts removed."""
    if isinstance(value, dict):
        return {key: '[REDACTED]' if str(key).lower() in _SENSITIVE else scrub(child) for key, child in value.items()}
    if isinstance(value, list):
        return [scrub(child) for child in value]
    if not isinstance(value, str):
        return value
    value = _JSON_SECRET.sub(lambda m: '"' + m[1] + '":"[REDACTED]"', value)
    value = _FORM_SECRET.sub(lambda m: m[1] + '=[REDACTED]', value)

    def url(match):
        try:
            parts = urlsplit(match[0])
            host = (parts.hostname or '').lower()
            if host == 'redd.it' or host.endswith('.redd.it'):
                return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
        except ValueError:
            return '[INVALID URL]'
        return match[0]
    return re.sub(r'https?://[^\s"\'<>]+', url, value)


def diagnostic(stage, **details):
    """Write caller-chosen request metadata to stderr, scrubbed; never response bodies or tokens."""
    print(json.dumps(scrub({'stage': stage, **details}), ensure_ascii=False), file=sys.stderr)
