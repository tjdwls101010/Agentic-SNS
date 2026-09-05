"""Single classification path for route reads, queries, and refresh verification."""
import json
import re
from urllib.parse import urljoin, urlsplit

from ._aside import run_snippet
from ._blocked import cache_dir, set_blocked
from ._budget import Budget
from ._errors import ThreadsError
from ._registry import Registry
from ._session import Session

ORIGIN = 'https://www.threads.com'


def classify(response, kind):
    status, body = response['status'], response['body']
    path = urlsplit(response.get('location') or response['url']).path.lower()
    payload, errors = None, []
    if kind == 'graphql':
        try:
            payload = json.loads(re.sub(r'^\s*for\s*\(;;\);', '', body))
            if isinstance(payload, dict):
                errors = {k: payload[k] for k in ('errors', 'error', 'error_code', 'error_subcode') if k in payload}
        except ValueError:
            pass
    messages, codes = [], set()
    def walk(value, key=''):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, k)
        elif isinstance(value, list):
            for v in value:
                walk(v, key)
        elif isinstance(value, str):
            if key not in ('path', 'line', 'column'):
                messages.append(value.lower())
            if 'code' in key and value.isdigit():
                codes.add(int(value))
        elif type(value) is int and 'code' in key:
            codes.add(value)
    walk(errors)
    message = ' '.join(messages)
    challenge_html = kind == 'page' and bool(re.search(
        r'<form\b[^>]*action=["\'][^"\']*/(?:challenge|checkpoint)(?:[/"\'?])|'
        r'"(?:checkpoint_required|challenge_required)"\s*:\s*true|"checkpoint_url"\s*:\s*"[^"\s]+"', body, re.I))
    if (re.match(r'^/(challenge|checkpoint)(/|$)', path) or codes & {368, 459} or challenge_html
            or any(x in message for x in ('checkpoint', 'challenge', 'consent_required'))):
        raise ThreadsError(5, 'Threads requires a checkpoint.',
                           'Stop requests. Check Threads in Aside, then run doctor --unblock.', error='checkpoint')
    if status == 429 or codes & {4, 17, 613, 80004} or any(x in message for x in ('rate limit', 'too many request', 'try again later')):
        raise ThreadsError(5, 'Threads limited this account.', 'Stop requests for 30 minutes; the block expires automatically.', error='rate_limit')
    if (re.match(r'^/(accounts/login|login)(/|$)', path)
            or any(x in message for x in ('login_required', 'session expired', 'csrf'))
            or kind == 'page' and re.search(r'<form\b[^>]*action=["\'][^"\']*/accounts/login', body, re.I)):
        raise ThreadsError(4, 'Threads login is required.')
    if status >= 400:
        raise ThreadsError(6, f'Threads returned HTTP {status}.')
    if kind == 'page':
        return body
    if not isinstance(payload, dict):
        raise ThreadsError(6, 'Threads returned incomplete or non-JSON data.')
    data = payload.get('data')
    useful = isinstance(data, dict) and any(value is not None for value in data.values())
    if not useful:
        rotated = 'critical' in message or 'execution error' in message
        raise ThreadsError(6, 'The query did not return its expected data.',
                           'Run refresh, or refresh --capture for lazy operations.',
                           error='operation_rotated' if rotated else 'envelope_drift')
    return payload


def safe_path(path):
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or not path.startswith('/') or path.startswith('//') or '\\' in path:
        raise ThreadsError(2, 'Route must be a local Threads path.')
    if not re.fullmatch(r'/(?:|search|liked/?|saved/?|@[A-Za-z0-9_.]+(?:/(?:threads|replies|reposts|media|post/[A-Za-z0-9_-]+))?/?|t/[A-Za-z0-9_-]+/?)', parsed.path):
        raise ThreadsError(2, 'This Threads route is outside the read-only surface.')
    return path


class Transport:
    def __init__(self, max_requests=10):
        self.budget = Budget(max_requests)
        self.registry = Registry()
        self.session = None
        self.fetched_bytes = 0
        self.route = '/'

    def _request(self, snippet, args, *, unblock=False):
        with self.budget.request(unblock=unblock):
            response = run_snippet(snippet, args)
            self.fetched_bytes += len(response['body'].encode())
            try:
                data = classify(response, snippet)
                if unblock and snippet == 'page' and response['status'] == 200:
                    Session.from_html(data)
                    (cache_dir() / 'blocked.json').unlink(missing_ok=True)
            except ThreadsError as error:
                if error.code == 5 and error.error in ('checkpoint', 'rate_limit'):
                    set_blocked(error.error)
                raise
            return response, data

    def page(self, path='/', *, unblock=False):
        path = safe_path(path)
        original = path
        for _ in range(4):
            response, html = self._request('page', {'path': path}, unblock=unblock)
            if 300 <= response['status'] < 400:
                location = response.get('location')
                if not location:
                    raise ThreadsError(6, 'Redirect has no location.')
                url = urlsplit(urljoin(ORIGIN + path, location))
                if url.scheme != 'https' or url.netloc != 'www.threads.com':
                    raise ThreadsError(6, 'Redirect left the expected Threads host.')
                if ('/post/' in original or original.startswith('/t/')) and '/post/' not in url.path:
                    raise ThreadsError(9, 'The post redirected to a non-post page.')
                path = safe_path(url.path + ('?' + url.query if url.query else ''))
                continue
            self.session = Session.from_html(html)
            self.route = path
            if original.startswith('/@') and '/post/' not in original:
                if not any(p['name'] == 'BarcelonaProfilePageDirectQuery' for p in self.session.preloaders):
                    raise ThreadsError(9, 'Authenticated route has no requested profile.')
            return html
        raise ThreadsError(6, 'Threads exceeded the three-redirect limit.')

    def query(self, name, values, *, spec=None):
        selected = self.registry.get(name)
        if spec is not None:
            selected = spec
        if not self.session:
            self.page('/')
        variables = self.registry.variables(name, values, selected)
        _, data = self._request('graphql', {'name': name, 'doc_id': selected['doc_id'], 'variables': variables,
                               'csrf': self.session.csrf, 'referer': ORIGIN + self.route})
        from ._walk import at, drift, read_page
        if name == 'BarcelonaProfilePageDirectQuery':
            user = at(data, 'data.user')
            if not isinstance(user, dict) or str(user.get('pk')) != str(variables['userID']):
                raise drift('Profile response does not match the requested identity.')
        elif 'StrongId' in name:
            media = at(data, 'data.media')
            if not isinstance(media, dict) or str(media.get('pk')) != str(variables['postID']):
                raise drift('Post response does not match the requested identity.')
        else:
            read_page(data, name)
        return data
