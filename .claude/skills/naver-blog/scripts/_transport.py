"""One classification path, and its order is the contract.

Naver answers a failure in whichever envelope the surface happens to use, so the same
HTTP 404 means "no such blog" on one host and nothing at all on another. classify reads
the operation's own declaration instead of guessing, and the step order decides which
reading wins when two could apply: a login wall outranks a missing target, and a policy
restriction outranks an empty list, because reporting the weaker one hides the stronger.
"""
import json
import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from ._aside import run_snippet
from ._api import allowed_path, build
from ._budget import Budget, set_blocked
from ._errors import NaverBlogError

XSSI = ")]}',"
# The one place a target-not-found code is spelled out; both the current and the older shape.
MISSING = {'not_exist_blog', 'not_exist_post', 'blog_id_invalidate', 'not_exist_category'}
BAD_ARGUMENT = {'param_is_invalidate', 'bad_request'}
NOT_LOGGED_IN = {'notlogined', 'not_logined', 'need_login', 'login_required'}


def drift(message, fix=None):
    return NaverBlogError(6, message, fix or 'Run doctor; the expected response shape changed.',
                          error='envelope_drift')


def at(value, path):
    """Read a declared leaf path. A `field[]` segment fans out over a list of objects."""
    for key in path.split('.'):
        if key.endswith('[]'):
            branch = at(value, key[:-2])
            if not isinstance(branch, list):
                return None
            rest = path.split(key + '.', 1)
            return [at(item, rest[1]) for item in branch] if len(rest) > 1 else branch
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def parse_body(body):
    """Strip the section hosts' XSSI prefix, then parse. A truncated body is not a shape change."""
    text = body.lstrip()
    if text.startswith(XSSI):
        text = text[len(XSSI):].lstrip()
    return json.loads(text)


def _envelope_error(payload):
    """The three envelopes name their failure differently; return (code, message) or None."""
    if not isinstance(payload, dict):
        return None
    error = payload.get('error')
    if isinstance(error, dict):
        return str(error.get('code') or ''), str(error.get('message') or '')
    if payload.get('success') is False or str(payload.get('code') or '') not in ('', '1000'):
        return str(payload.get('code') or ''), str(payload.get('message') or '')
    return None


def _restricted(payload):
    """Policy signals ride anywhere in the envelope; a restricted answer is not an empty one."""
    found = []

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('blockedByBifrostShield', 'isBlockedByBifrostShield', 'suicideWord') and child is True:
                    found.append(key)
                elif key == 'queryControlInfo' and isinstance(child, dict) and child.get('isForbidden') is True:
                    found.append('isForbidden')
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(payload)
    return found


def classify(spec, response, *, expect=None):
    """Return the parsed payload, or raise. `expect` names identifiers the answer must match."""
    status, body = response['status'], response.get('body', '')
    location = response.get('location') or ''
    # An exact host check, so a lookalike domain ending in nid.naver.com.example is not a login.
    hosts, paths = set(), set()
    for candidate in (location, response.get('url') or ''):
        if candidate:
            parsed = urlsplit(urljoin('https://' + spec.host, candidate))
            hosts.add((parsed.hostname or '').lower())
            paths.add(parsed.path.lower())

    # 1. Transport failure: nothing below can read a body that never arrived intact.
    if status >= 500:
        raise NaverBlogError(6, f'Naver returned HTTP {status}.', error='transient')

    # 2. Explicit block. Only 429 has ever been observed; nothing else is promoted to a block.
    if status == 429:
        raise NaverBlogError(5, 'Naver rate-limited this account.',
                             'Stop requests for 30 minutes; this block expires on its own.', error='rate_limit')

    # 3. Login. An explicit hop to the login host counts for every command.
    if 'nid.naver.com' in hosts or any(path.startswith('/nidlogin') for path in paths):
        raise NaverBlogError(4, 'Naver login is required.')

    payload, parse_failed = None, False
    if spec.accept == 'json':
        try:
            payload = parse_body(body)
        except ValueError:
            parse_failed = True
    code, message = (_envelope_error(payload) or ('', ''))

    if spec.login and code.lower() in NOT_LOGGED_IN:
        raise NaverBlogError(4, 'Naver login is required for this surface.')

    # 4. Target gone, closed, or not ours.
    if spec.accept == 'html':
        missing = re.search(r'MobileErrorView\.naver\?errorType=([A-Za-z0-9_]+)', body)
        if status == 404 and missing:
            if missing[1] == 'noPost':
                raise NaverBlogError(9, 'That post is gone, private, or buddy-only.',
                                     'Check the post number; deleted and closed posts answer alike.',
                                     error='not_exist_post', reason='noPost')
            # Any other errorType has never been seen; naming it beats guessing what it means.
            raise NaverBlogError(6, f'Naver returned an unrecognized error page ({missing[1]}).',
                                 'Open the post in Aside once and report the errorType.',
                                 error='transient', reason=missing[1])
    if status == 403 and code == 'not_blog_owner':
        raise NaverBlogError(9, 'This surface belongs to its blog owner only.',
                             'Read public-buddies instead, or pass your own blog id.',
                             error='owner_only', reason='owner_only')
    if code in MISSING:
        raise NaverBlogError(9, 'That blog or post does not exist, or is not readable.',
                             'Check the blog id; a domain address resolves to a different id.',
                             error=code, reason=code)

    # 5. Arguments the CLI should have refused before spending a request.
    if code in BAD_ARGUMENT:
        raise NaverBlogError(2, f'Naver rejected a request parameter ({code}).',
                             'This is a bug in the skill, not in your command; report the command you ran.')

    # 6. Contract error. An empty 403 is the referer contract; everything unexplained lands here.
    if status == 403:
        raise drift('Naver refused the request without a reason (the referer contract may have changed).')
    if status >= 400:
        raise NaverBlogError(6, f'Naver returned HTTP {status}.', error='transient')
    if spec.accept == 'html':
        return body
    if parse_failed or not isinstance(payload, dict):
        # A list or a bare null is valid JSON and still not an envelope this reader can read.
        raise NaverBlogError(6, 'Naver returned incomplete or unrecognized data.', error='transient')
    if code:
        # Includes every CBOX code: 3300 also comes from a wrong pool, so it is a contract error.
        raise drift(f'Naver reported {code or "an unnamed failure"}: {message[:120]}')
    if spec.success and payload.get(spec.success) is not True:
        raise drift('The response does not carry its success flag.')
    leaf = at(payload, spec.leaf) if spec.leaf else None
    if spec.leaf_type == 'list' and not isinstance(leaf, list):
        raise drift('Expected a list at ' + spec.leaf)
    if spec.leaf_type == 'dict' and not isinstance(leaf, dict):
        raise drift('Expected an object at ' + spec.leaf)
    for path, wanted in (expect or {}).items():
        got = at(payload, path)
        # A list path (result.commentList[].objectId) must have every item agree.
        values = got if isinstance(got, list) else [got]
        for value in values:
            if value is not None and str(wanted) not in str(value).split('_'):
                if str(value) != str(wanted):
                    raise drift(f'Naver answered about {value}, not the requested {wanted}.')

    # 7. Policy restriction. Results that did arrive are kept; the restriction is reported.
    restricted = _restricted(payload)
    if restricted:
        error = NaverBlogError(8, 'Naver restricted this query (' + ', '.join(sorted(set(restricted))) + ').',
                               'Rephrase the keyword; adult, forbidden and shielded queries answer this way.',
                               error='query_restricted')
        # Whatever did arrive is carried on the error: a restriction is not an empty shelf.
        error.payload = payload
        raise error
    return payload


def safe_location(host, path, location):
    """A redirect may only move within the hosts and paths this reader already allows."""
    url = urlsplit(urljoin(f'https://{host}{path}', location))
    if url.scheme != 'https' or not allowed_path(url.hostname or '', url.path):
        raise drift('A redirect left the reading surface this reader allows.')
    return url


class Transport:
    def __init__(self, max_requests=10):
        self.budget = Budget(max_requests)
        self.fetched_bytes = 0

    def get(self, name, *, page=None, expect=None, unblock=False, **values):
        spec, path, query = build(name, page=page, **values)
        response = self.fetch(spec, path, query, unblock=unblock)
        # classify first: a redirect to the login host is a login error, not an unexpected hop.
        payload = classify(spec, response, expect=self._identity_of(spec, values, expect))
        if 300 <= response['status'] < 400:
            raise drift('Naver redirected a request that should not redirect.')
        return payload

    @staticmethod
    def _identity_of(spec, values, expect):
        """The ledger names the field an answer must agree with; nobody has to remember to pass it."""
        checks = dict(expect or {})
        if spec.identity and spec.identity.startswith('result.'):
            wanted = values.get('logNo') if 'commentList' in spec.identity else values.get('blogId')
            if wanted is not None:
                checks.setdefault(spec.identity, wanted)
        return checks

    def redirect_of(self, name, **values):
        """Resolve one hop and return the canonical blog id a domain address points at."""
        spec, path, query = build(name, **values)
        response = self.fetch(spec, path, query)
        # classify runs on every status: a block, a login wall or a server fault here is
        # that, not "no such blog", and a login hop is a 3xx like any other.
        classify(spec, response)
        location = response.get('location') or ''
        if not location:
            raise NaverBlogError(9, 'That blog id does not exist and is not a domain address.',
                                 'Open the blog once in Aside and pass the id in its address bar.',
                                 error='not_exist_blog')
        url = safe_location(spec.host, path, location)
        canonical = dict(parse_qsl(url.query)).get('blogId', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', canonical):
            raise drift('A domain address redirected without naming a blog id.')
        return canonical

    def fetch(self, spec, path, query, *, unblock=False):
        with self.budget.request(unblock=unblock):
            try:
                response = run_snippet('fetch', {'host': spec.host, 'path': path,
                                                 'query': query, 'accept': spec.accept})
            except NaverBlogError:
                raise
            self.fetched_bytes += len(response.get('body', '').encode())
            if response['status'] == 429:
                set_blocked()
            return response
