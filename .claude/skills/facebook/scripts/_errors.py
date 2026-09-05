"""Public errors and the single scrub path for optional diagnostics."""
import json
import re
import sys
from urllib.parse import urlsplit, urlunsplit

_FIXES = {
    2: 'Run this command with --help.',
    3: 'Check that Aside is running, then run doctor.',
    4: 'Log in to Facebook in Aside, then run doctor.',
    5: 'Stop requests. Check Facebook in Aside before doctor --unblock.',
    6: 'Run refresh, then retry the read command.',
    7: 'Try a different target or window; this is an explicitly empty result.',
    8: 'Use the continuation command or resume the same output file later.',
}
_SENSITIVE = {'fb_dtsg', 'lsd', 'jazoest', 'datr', 'sb', 'c_user', 'xs', 'token',
              'access_token', 'cookie', 'cookies', 'authorization'}
_KEYS = '|'.join(re.escape(key) for key in sorted(_SENSITIVE))
_JSON_SECRET = re.compile(r'"(' + _KEYS + r')"\s*:\s*"(?:\\.|[^"\\])*"', re.I)
_FORM_SECRET = re.compile(r'\b(' + _KEYS + r')\s*[:=]\s*[^\s;&"\']+', re.I)


class FacebookError(Exception):
    def __init__(self, code, message, fix=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.fix = fix or _FIXES.get(code, 'Check the command with --help.')

    def as_dict(self):
        return {'ok': False, 'error': self.code, 'message': self.message, 'fix': self.fix}


def scrub(value):
    """Scrub cookie/token fields and bearer-like CDN query strings, without mutating input."""
    if isinstance(value, dict):
        return {key: '[REDACTED]' if str(key).lower() in _SENSITIVE else scrub(child)
                for key, child in value.items()}
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
            if host == 'fbcdn.net' or host.endswith('.fbcdn.net') or host == 'fbstatic-a.akamaihd.net':
                return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
        except ValueError:
            return '[INVALID URL]'
        return match[0]
    return re.sub(r'https?://[^\s"\'<>]+', url, value)


def diagnostic(stage, **details):
    """Only caller-selected metadata belongs here; never source, ARGS, stdout or stderr."""
    print(json.dumps(scrub({'stage': stage, **details}), ensure_ascii=False), file=sys.stderr)
