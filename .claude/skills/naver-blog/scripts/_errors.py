"""Public errors and the single scrub path for optional diagnostics."""
import json
import re
import sys
from urllib.parse import urlsplit, urlunsplit

_FIXES = {
    2: 'Run this command with --help.',
    3: 'Check that Aside is running, then run doctor.',
    4: 'Log in to Naver in Aside, then run doctor.',
    5: 'Stop requests. Open Naver Blog in Aside before doctor --unblock.',
    6: 'Wait briefly before retrying; no automatic retry was made.',
    7: 'Try a different target, keyword or window; this is an explicitly empty result.',
    8: 'Use the continuation command, or read the sections that did succeed.',
    9: 'Check the blog id or post number; deleted, private and buddy-only posts read the same way.',
}
# Naver's session cookies and the tracking ids that ride alongside them.
_SENSITIVE = {'nid_aut', 'nid_ses', 'nid_jkl', 'nid_inf', 'nnb', 'userkey', 'bauserkey',
              'token', 'csrf', 'sessionid', 'access_token', 'cookie', 'cookies', 'authorization'}
_KEYS = '|'.join(re.escape(key) for key in sorted(_SENSITIVE))
_JSON_SECRET = re.compile(r'"(' + _KEYS + r')"\s*:\s*"(?:\\.|[^"\\])*"', re.I)
_FORM_SECRET = re.compile(r'\b(' + _KEYS + r')\s*[:=]\s*[^\s;&"\']+', re.I)


class NaverBlogError(Exception):
    def __init__(self, code, message, fix=None, error=None, reason=None):
        super().__init__(message)
        self.code = code
        # Naver's own word for what happened, kept raw so an unfamiliar one can be reported.
        self.reason = reason
        # Results that arrived alongside a partial failure; a restriction is not an empty shelf.
        self.payload = None
        self.error = error or {2: 'arguments', 3: 'aside', 4: 'login', 5: 'blocked', 6: 'transient',
                               7: 'empty', 8: 'partial', 9: 'unavailable'}.get(code, 'failure')
        self.message = message
        self.fix = fix or _FIXES.get(code, 'Check the command with --help.')

    def as_dict(self):
        payload = {'ok': False, 'error': self.error, 'code': self.code,
                   'message': self.message, 'fix': self.fix}
        return payload | ({'reason': self.reason} if self.reason else {})


def scrub(value):
    """Scrub cookie/token fields and signed CDN query strings, without mutating input."""
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
            # pstatic image URLs carry a signature in the query; the path alone still resolves.
            if host == 'pstatic.net' or host.endswith('.pstatic.net'):
                return urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))
        except ValueError:
            return '[INVALID URL]'
        return match[0]
    return re.sub(r'https?://[^\s"\'<>]+', url, value)


def diagnostic(stage, **details):
    """Only caller-selected metadata belongs here; never source, ARGS, stdout or stderr."""
    print(json.dumps(scrub({'stage': stage, **details}), ensure_ascii=False), file=sys.stderr)
