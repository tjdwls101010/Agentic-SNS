"""Single classification path for route reads, queries, and refresh verification."""
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from ..aside.repl import run
from ..errors import CAPTURE, ThreadsError, changed, rotated
from ..guard.blocked import set_blocked
from ..guard.budget import Budget
from ..guard.state import cache_dir
from .decode import at, drift
from .operations import OPERATIONS
from .registry import Registry
from .session import Session

ORIGIN = 'https://www.threads.com'
SNIPPETS = Path(__file__).resolve().parent / 'snippets'


def run_snippet(name, args):
    """Run one of this system's browser snippets (page, graphql, capture) through Aside."""
    if not isinstance(name, str) or Path(name).name != name:
        raise ThreadsError(3, 'Invalid browser snippet.', 'Reinstall the Threads skill.')
    name = name if name.endswith('.js') else name + '.js'
    try:
        source = (SNIPPETS / name).read_text(encoding='utf-8')
        if not source.strip():
            raise ValueError
    except (OSError, ValueError):
        raise ThreadsError(3, 'Browser snippet is missing or invalid.', 'Reinstall the Threads skill.') from None
    return run(source, args)


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
                           'Stop requests. Check Threads in Aside, then run `{cli} doctor --unblock`.', error='checkpoint')
    if status == 429 or codes & {4, 17, 613, 80004} or any(x in message for x in ('rate limit', 'too many request', 'try again later')):
        raise ThreadsError(5, 'Threads limited this account.', 'Stop requests for 30 minutes; the block expires automatically.', error='rate_limit')
    if (re.match(r'^/(accounts/login|login)(/|$)', path)
            or any(x in message for x in ('login_required', 'session expired', 'csrf'))
            or kind == 'page' and re.search(r'<form\b[^>]*action=["\'][^"\']*/accounts/login', body, re.I)):
        raise ThreadsError(4, 'Threads login is required.')
    if kind == 'page' and status == 404:
        raise ThreadsError(9, 'Threads has no page here (HTTP 404): deleted, or never existed.')
    if status >= 400:
        raise ThreadsError(6, f'Threads returned HTTP {status}.')
    if kind == 'page':
        return body
    if not isinstance(payload, dict):
        if kind == 'graphql' and body.lstrip()[:15].lower().startswith(('<!doctype html', '<html')):
            # The app shell instead of data: Threads no longer serves this query as the reader sends it.
            raise changed('Threads answered the query with a web page instead of data.')
        raise ThreadsError(6, 'Threads returned incomplete or non-JSON data.')
    data = payload.get('data')
    useful = isinstance(data, dict) and any(value is not None for value in data.values())
    if not useful:
        if 'critical' in message or 'execution error' in message:
            raise rotated('Threads no longer runs this query as registered.')
        raise changed('The query did not return its expected data.')
    return payload


def safe_path(path):
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or not path.startswith('/') or path.startswith('//') or '\\' in path or '#' in path:
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

    def page(self, path='/', *, unblock=False, profile_check=True):
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
            if profile_check and re.fullmatch(r'/@[A-Za-z0-9_.]+/?', original):
                loaders = self.session.preloaders
                if not any(p['name'] == self.registry.name('profile.page') for p in loaders):
                    # A profile rendered under another query name is a rename refresh can find, not a missing profile.
                    signature = OPERATIONS['profile.page'].signature
                    if any(signature.fits(p['variables'], p['variables'].get('userID')) for p in loaders):
                        raise rotated('The profile route renders its profile under another query name.')
                    raise ThreadsError(9, 'Authenticated route has no requested profile.')
            return html
        raise ThreadsError(6, 'Threads exceeded the three-redirect limit.')

    def query(self, operation, values, *, entry=None, provisional=False):
        """Send one declared read and return the classified payload; the caller decodes it, and an operation that
        declares an identity is checked here.

        The name sent is the registry's. `entry` carries a candidate id and flags refresh is verifying under that
        name; only refresh may pass `provisional=True`, for one replay of a renamed preloader the route itself proved,
        and even then the name must be a query that names no mutation."""
        selected = entry if entry is not None else self.registry.entry(operation)
        admitted = self.registry.admitted()
        if selected['name'] != self.registry.name(operation):
            if not provisional or not re.fullmatch(r'[A-Za-z0-9_]+Query', selected['name']) or 'Mutation' in selected['name']:
                raise ThreadsError(2, 'Only the registered read-only operations can be sent.')
            admitted = admitted + [selected['name']]
        if not self.session:
            self.page('/')
        variables = self.registry.variables(operation, values, selected)
        try:
            _, data = self._request('graphql', {'name': selected['name'], 'admitted': admitted,
                                                'doc_id': selected['doc_id'], 'variables': variables,
                                                'csrf': self.session.csrf, 'referer': ORIGIN + self.route})
        except ThreadsError as error:
            # Only an app tab loads these operations, so only a capture can find their new ids.
            if error.error == 'operation_rotated' and OPERATIONS[operation].discovery == 'capture':
                error.fix = CAPTURE
            raise
        path = OPERATIONS[operation].identity
        if path is not None:
            found = at(data, 'data.' + path)
            if not isinstance(found, dict) or str(found.get('pk')) != str(variables['userID']):
                raise drift('Profile response does not match the requested identity.')
        return data

    def rendered(self, ssr, operation, identity=None):
        """The route's own rendered result for a declared operation."""
        return ssr.select(self.registry.name(operation), OPERATIONS[operation].ssr_shape, identity)
