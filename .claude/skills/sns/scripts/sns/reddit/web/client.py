"""Reddit through the browser: every request inside a guard slot, its limit headers reported, its answer classified, a
stop recorded before the slot closes; redirects and share links followed hop by hop, each hop a request of its own.

The client follows the protocol reading.Platform documents (a tab-less fetch platform): start() has nothing to open,
viewer() asks Reddit who the browser is (one request, bucket general), verify() is the unblock check's one request.
"""
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from sns.errors import SnsError, diagnostic

from sns.reddit.web import headers, routes
from sns.reddit.web.classify import classify, outcome
from sns.reddit.web.records import community, moderator, page, rule, user, wiki_index, wiki_page
from sns.reddit.web.targets import BASE, parse_target
from sns.reddit.web import tree

FETCH = Path(__file__).with_name('fetch.js').read_text(encoding='utf-8')
REDIRECTS = (301, 302, 303, 307, 308)
HOPS = 3
_CHECK = 'Check that Aside is running, then run doctor.'


def _location(value, argument=False):
    """A redirect target on www.reddit.com as (path, query); anything else is refused (an argument error while
    resolving a share link the user gave, a failed read otherwise)."""
    def refused():
        message = 'Reddit redirected to an address this skill does not follow.'
        fix = 'Open the link in the Aside browser and pass its permalink.'
        return SnsError('argument' if argument else 'failed', message, fix)
    if isinstance(value, str) and value.startswith('/') and not value.startswith('//'):
        value = BASE + value
    if not isinstance(value, str) or any(c in value for c in ' \t\r\n\\'):
        raise refused()
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        port = 'bad'
    if parts.scheme != 'https' or parts.netloc != 'www.reddit.com' or port is not None or \
            any(segment in ('.', '..') for segment in parts.path.split('/')):
        raise refused()
    return parts.path, dict(parse_qsl(parts.query))


def _envelope(value):
    """What the fetch snippet returned, checked: {status, url, body, location, ratelimit}."""
    if (not isinstance(value, dict) or type(value.get('status')) is not int or not 100 <= value['status'] <= 599
            or not isinstance(value.get('url'), str) or not isinstance(value.get('body'), str)
            or not isinstance(value.get('ratelimit'), dict)
            or not isinstance(value.get('location'), (str, type(None)))):
        raise SnsError('aside', 'Aside returned output this skill cannot read.', _CHECK, reason='invalid')
    return value


class Client:
    """One invocation's Reddit: the connection's Aside runs the fetch snippet, its guard spaces and records each request.
    `extra()` adds the platform's own fields to doctor."""

    def __init__(self, connection, extra=None):
        self.connection = connection
        self.aside, self.guard = connection.aside, connection.guard
        self._extra = extra

    # --- the client protocol -----------------------------------------------------------------------------------

    def start(self):
        return None  # nothing to open: the account is asked for only by the readings that need it

    def viewer(self):
        """The Reddit account the browser is logged in to (one request); logged out is a login failure."""
        name = self.get(routes.me())['data']['name']
        self.connection.seen(name)
        return name

    def verify(self, check):
        """The unblock check: one /api/me.json request (it uses the check's reservation), clean only for the account
        the block was recorded for."""
        name = self.viewer()
        named = (check.person or {}).get('viewer')
        if named and named != name:
            raise SnsError('blocked', f'The block stays: it was recorded for u/{named}, but the browser is logged in '
                                      f'to u/{name}.', 'A person should check Reddit as the account that was blocked.',
                           reason='verification', verification_reason='account_mismatch')

    def release(self):
        return None

    def release_tab(self):
        return True

    def report(self):
        return {}

    def doctor(self):
        """Doctor's login check is this one request (the shared doctor builds its counts before asking), so the fields
        it has already counted are reported again with the request included."""
        name = self.connection.viewer()
        recent = self.guard.recent()
        return {'viewer': name, 'reddit_account': name, 'limits': self.guard.state()['scopes'],
                'requests_last_hour': recent['last_hour'], 'requests_last_day': recent['last_day'],
                **(self._extra() if self._extra else {})}

    # --- one request -------------------------------------------------------------------------------------------

    def _send(self, request):
        """One request in one guard slot: the envelope, with the window it reported recorded and a stop recorded."""
        args = {'url': request.url} if request.url else {'path': request.path, 'query': request.query}
        bucket = request.bucket
        with self.guard.request(scope=bucket) as slot:
            envelope = _envelope(self.aside.run(FETCH, args))
            now = self.guard.clock.time()
            if request.measured:
                stated = headers.limit_fact(envelope['ratelimit'], now)
                if stated:
                    slot.fact(bucket, stated)
            if self.connection.verbose:
                diagnostic('request', path=request.path or request.url, status=envelope['status'],
                           ratelimit=envelope['ratelimit'])
            if envelope['status'] in REDIRECTS:
                slot.classify('redirect')
                return envelope
            try:
                if request.expect == 'page' and 200 <= envelope['status'] < 300:
                    body = None  # a share link answers with a page; only where it leads matters
                else:
                    body = classify(envelope, 'listing' if request.expect == 'page' else request.expect,
                                    personal=request.personal, wiki=bucket == routes.WIKI)
            except SnsError as error:
                slot.classify(outcome(error))
                if error.reason == 'rate_limit':
                    seconds = error.details.get('seconds')
                    raise slot.hold(until=None if seconds is None else now + seconds, scope=bucket) from None
                if error.reason == 'challenge':
                    raise slot.block('challenge', viewer=self.connection.known_viewer) from None
                raise
            slot.classify('ok')
            return {**envelope, 'parsed': body}

    def get(self, request):
        """The parsed body of a request, following at most HOPS - 1 redirects (each hop is a request)."""
        for hop in range(HOPS):
            envelope = self._send(request)
            if envelope['status'] not in REDIRECTS:
                return envelope['parsed']
            if hop == HOPS - 1:
                break
            path, query = _location(envelope.get('location'))
            if path.endswith('/.json'):
                path = path[:-len('/.json')] + '.json'
            if routes.bucket_of(path, redirected=True) != request.bucket:
                raise SnsError('failed', 'Reddit redirected to another kind of endpoint.', 'Report this as a skill bug.')
            request = replace(request, path=path, query=query)
        raise SnsError('failed', f'Reddit redirected more than {HOPS - 1} times.',
                       'Open the link in the Aside browser and pass its permalink.')

    def resolve(self, target):
        """A share link's post or comment target (each hop a request, at most HOPS); other targets unchanged."""
        if target.kind != 'share':
            return target
        url = target.url
        for _ in range(HOPS):
            envelope = self._send(routes.share(url))
            if envelope['status'] in REDIRECTS:
                path, _query = _location(envelope.get('location'), argument=True)
            else:
                path, _query = _location(envelope['url'], argument=True)
            try:
                found = parse_target(BASE + path)
            except SnsError:
                found = None
            if found is not None and found.kind in ('post', 'comment'):
                return found
            if found is None or found.kind != 'share' or envelope['status'] not in REDIRECTS:
                break
            url = found.url
        raise SnsError('argument', 'The share link did not lead to a post or comment.',
                       'Open the share link in the Aside browser and pass the post\'s permalink.')

    # --- what the commands read --------------------------------------------------------------------------------

    def listing(self, request):
        """(records, after) of one listing page; an explicitly empty page is ([], None)."""
        try:
            body = self.get(request)
        except SnsError as error:
            if error.kind == 'empty':
                return [], None
            raise
        return page(body[1] if request.expect == 'duplicates' else body, inbox=request.inbox)

    def thread(self, post_id, sort, comment_id=None, context=None):
        """(post record, items) of a post read, or of one comment's subtree (comment_id with context 0)."""
        return tree.thread(self.get(routes.post(post_id, sort, comment_id, context)))

    def expand(self, post_id, ids, sort):
        """Items of one comment expansion; [] when Reddit sent nothing for these ids."""
        try:
            return tree.expansion(self.get(routes.morechildren(post_id, ids, sort)))
        except SnsError as error:
            if error.kind == 'empty':
                return []
            raise

    def community(self, sub):
        return community(self.get(routes.community(sub))['data'])

    def rules(self, sub):
        return [rule(item) for item in self.get(routes.rules(sub))['rules']]

    def user(self, name):
        return user(self.get(routes.user(name))['data'])

    def moderators(self, sub):
        return [moderator(item) for item in self.get(routes.moderators(sub))['data']['children']]

    def pinned(self, sub):
        """The community's pinned posts: the stickied posts at the top of hot."""
        records, _after = self.listing(routes.pinned(sub))
        return [record for record in records if record.get('pinned')]

    def wiki_page(self, sub, name):
        return wiki_page(sub, name, self.get(routes.wiki_page(sub, name))['data'])

    def wiki_index(self, sub):
        return wiki_index(sub, self.get(routes.wiki_index(sub))['data'])
