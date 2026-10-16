"""What a Threads response means for account protection and for the read: one place, for queries and documents.

Order of precedence: a checkpoint (the account needs a person) over a rate limit (it expires) over a login. The
checkpoint and login markers are account signals wherever they appear, so they are read from any response, query or
document; the words that mark them are read only from error fields, never from post text.
"""
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from threads.errors import ThreadsError
from threads.threads_web.targets import ORIGIN, route_allowed

CHECKPOINT_CODES = {368, 459}
RATE_LIMIT_CODES = {4, 17, 613, 80004}
UNBLOCK_FIX = 'Stop requests. After a person checks Threads in the Aside browser, run doctor --unblock.'
RATE_FIX = 'Stop requests and retry after the block expires (30 minutes); check Threads in the Aside browser first.'
LOGIN_FIX = 'Log in to Threads in the Aside browser, then run doctor.'
CHANGED_FIX = 'Threads changed this response; the skill needs an update. Tell the user which read failed.'
REJECTED_FIX = 'Retry the command once (it learns the current query); if it fails again, the skill needs an update.'
RETRY_FIX = 'Retry later; run doctor if it keeps failing.'
# The markers a document or a body carries for a block or a login: unescaped JSON keys or a form action (a key inside
# post text is escaped (\") and does not match). The tab runs the same patterns (case-insensitive) to keep what it saw.
CHECKPOINT_PATTERNS = [r'<form\b[^>]*action=["\'][^"\']*/(?:challenge|checkpoint)(?:[/"\'?])',
                       r'(?<!\\)"(?:checkpoint_required|challenge_required)"\s*:\s*true',
                       r'(?<!\\)"checkpoint_url"\s*:\s*"[^"\s]+"']
LOGIN_PATTERNS = [r'<form\b[^>]*action=["\'][^"\']*/accounts/login']
SIGNAL_MARKERS = CHECKPOINT_PATTERNS + LOGIN_PATTERNS
_CHECKPOINT_MARKERS = re.compile('|'.join(CHECKPOINT_PATTERNS), re.I)
_LOGIN_FORM = re.compile('|'.join(LOGIN_PATTERNS), re.I)


@dataclass
class Verdict:
    kind: str                       # ok | blocked | login | unavailable | failed
    error: ThreadsError | None = None
    block: str | None = None        # checkpoint | rate_limit
    reason: str | None = None       # failed: http | non_json | rejected_query | shape_changed | session_unknown
    payload: dict | None = None     # the decoded JSON of an ok query
    account_id: str | None = None   # documents: the logged-in Threads account
    username: str | None = None


@dataclass
class Redirect:
    kind: str                       # follow | unavailable | failed | refused
    path: str | None = None
    reason: str | None = None
    error: ThreadsError | None = field(default=None, repr=False)


def _checkpoint():
    return Verdict('blocked', ThreadsError(5, 'Threads showed a checkpoint for this account; requests stay blocked until '
                                              'a person clears it.', UNBLOCK_FIX, reason='checkpoint'),
                   block='checkpoint')


def _rate_limit():
    return Verdict('blocked', ThreadsError(5, 'Threads rate-limited this account; requests are blocked for 30 minutes.',
                                           RATE_FIX, reason='rate_limit'), block='rate_limit')


def _login():
    return Verdict('login', ThreadsError(4, 'Threads login is required in the Aside browser.', LOGIN_FIX,
                                         reason='login'))


def _failed(reason, message, fix=RETRY_FIX):
    return Verdict('failed', ThreadsError(6, message, fix, reason=reason), reason=reason)


def _signals(payload):
    """(lowercased error messages, error codes) from the error fields of a decoded body."""
    messages, codes = [], set()

    def walk(value, key=''):
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, child_key)
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif isinstance(value, str):
            if key not in ('path', 'line', 'column', 'debug_link', 'mids'):
                messages.append(value.lower())
            if 'code' in key and value.isdigit():
                codes.add(int(value))
        elif type(value) is int and 'code' in key:
            codes.add(value)

    if isinstance(payload, dict):
        walk({key: payload[key] for key in ('errors', 'error', 'error_code', 'error_subcode') if key in payload})
        if 'data' not in payload and isinstance(payload.get('message'), str):
            messages.append(payload['message'].lower())  # an Instagram-style {message, status: fail} body
    return ' '.join(messages), codes


def _decode(body):
    try:
        return json.loads(re.sub(r'^\s*for\s*\(;;\);', '', body))
    except ValueError:
        return None


def response(envelope, *, mode):
    """The verdict on one response {status, url, body, location?}; mode is graphql (a query) or page (a document)."""
    status, body = envelope.get('status'), envelope.get('body') or ''
    path = urlsplit(envelope.get('location') or envelope.get('url') or '').path.lower()
    payload = _decode(body) if mode == 'graphql' or body.lstrip()[:1] in ('{', '[') else None
    message, codes = _signals(payload)
    if (re.match(r'^/(challenge|checkpoint)(/|$)', path) or codes & CHECKPOINT_CODES or _CHECKPOINT_MARKERS.search(body)
            or any(word in message for word in ('checkpoint', 'challenge', 'consent_required'))):
        return _checkpoint()
    if (status == 429 or codes & RATE_LIMIT_CODES
            or any(word in message for word in ('rate limit', 'too many request', 'try again later'))):
        return _rate_limit()
    if (re.match(r'^/(accounts/login|login)(/|$)', path)
            or any(word in message for word in ('login_required', 'session expired', 'csrf'))
            or (mode == 'page' and _LOGIN_FORM.search(body))):
        return _login()
    if mode == 'page' and status == 404:
        return Verdict('unavailable', ThreadsError(9, 'Threads has no page here (HTTP 404): deleted, or never existed.',
                                                   'Tell the user; retrying will not change it.', reason='unavailable'))
    if not isinstance(status, int) or status >= 400:
        return _failed('http', f'Threads answered with HTTP {status}.')
    if mode == 'page':
        return Verdict('ok')
    if not isinstance(payload, dict):
        if body.lstrip()[:15].lower().startswith(('<!doctype html', '<html')):
            return _failed('shape_changed', 'Threads answered the query with a web page instead of data.', CHANGED_FIX)
        return _failed('non_json', 'Threads returned incomplete or non-JSON data.')
    data = payload.get('data')
    if not (isinstance(data, dict) and any(value is not None for value in data.values())):
        if 'critical' in message or 'execution error' in message:
            return _failed('rejected_query', 'Threads no longer runs this query as sent.', REJECTED_FIX)
        return _failed('shape_changed', 'The query did not return its expected data.', CHANGED_FIX)
    return Verdict('ok', payload=payload)


def signal(kept):
    """The verdict on one response the tab kept: the strongest of its error-field summary (JSON), its marker excerpt,
    a body kept in the earlier format, and its status and address."""
    status, url = kept.get('status'), kept.get('url') or ''
    verdicts = [response({'status': status, 'url': url, 'body': kept.get('excerpt') or ''}, mode='page')]
    if kept.get('summary'):
        verdicts.append(response({'status': status, 'url': url, 'body': kept['summary']}, mode='graphql'))
    if kept.get('body'):
        mode = 'graphql' if str(kept['body']).lstrip()[:1] in ('{', '[') else 'page'
        verdicts.append(response({'status': status, 'url': url, 'body': kept['body']}, mode=mode))
    return strongest(verdicts) or verdicts[-1]


def strongest(verdicts):
    """The verdict that weighs most: a checkpoint, then a rate limit, then a login page; None when none is any."""
    rank = {'checkpoint': 3, 'rate_limit': 2}
    found = [v for v in verdicts if v.block or v.kind == 'login']
    return max(found, key=lambda v: rank.get(v.block, 1)) if found else None


def _field(html, name):
    match = re.search(r'"' + name + r'"\s*:\s*("(?:\\.|[^"\\])*")', html)
    try:
        return json.loads(match[1]) if match else ''
    except ValueError:
        return ''


def document(html):
    """The verdict on a Threads document's own markers: a block or login page, else who is logged in."""
    verdict = response({'status': 200, 'url': ORIGIN + '/', 'body': html}, mode='page')
    if verdict.kind != 'ok':
        return verdict
    csrf, account, username = (_field(html, key) for key in ('csrf_token', 'NON_FACEBOOK_USER_ID', 'username'))
    if csrf and account and account != '0' and username:
        return Verdict('ok', account_id=account, username=username)
    if 'DTSGInitialData' in html and not any((csrf, account, username)):
        return _login()
    return _failed('session_unknown', 'The Threads page does not establish a logged-in session.',
                   'Run doctor; a page without these markers does not prove a logout.')


def redirect(original, location, hop):
    """What to do with the `hop`-th redirect of a read of `original` that points at `location`."""
    if not location:
        return Redirect('failed', reason='redirect', error=ThreadsError(6, 'A Threads redirect had no location.',
                                                                         RETRY_FIX, reason='redirect'))
    if hop > 3:
        return Redirect('failed', reason='redirect', error=ThreadsError(6, 'Threads redirected more than three times.',
                                                                         RETRY_FIX, reason='redirect'))
    url = urlsplit(urljoin(ORIGIN + original, location))
    if url.scheme != 'https' or url.netloc != 'www.threads.com':
        return Redirect('failed', reason='redirect', error=ThreadsError(6, 'Threads redirected away from '
                                                                            'www.threads.com.', RETRY_FIX,
                                                                         reason='redirect'))
    if ('/post/' in original or original.startswith('/t/')) and '/post/' not in url.path:
        return Redirect('unavailable', error=ThreadsError(9, 'The post redirected to a page that is not a post: it '
                                                             'was deleted or is not visible to this account.',
                                                          'Tell the user; retrying will not change it.',
                                                          reason='unavailable'))
    path = url.path + ('?' + url.query if url.query else '')
    if not route_allowed(path):
        return Redirect('refused', error=ThreadsError(2, 'Threads redirected outside the read-only surface.',
                                                      'Tell the user; this skill does not follow it.'))
    return Redirect('follow', path=path)
