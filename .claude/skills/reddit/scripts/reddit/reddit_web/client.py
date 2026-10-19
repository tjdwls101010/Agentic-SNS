"""Reddit through the browser: every request inside a guard slot, its headers reported, its answer classified, a block
recorded before the slot closes; redirects and share links followed hop by hop, each hop a request of its own."""
from dataclasses import replace
from urllib.parse import parse_qsl, urlsplit

from reddit.errors import RedditError, diagnostic
from reddit.reddit_web import routes
from reddit.reddit_web.classify import classify, outcome, rate_limit_seconds
from reddit.reddit_web.records import tree
from reddit.reddit_web.records.entities import community, moderator, rule, user, wiki_index, wiki_page
from reddit.reddit_web.records.lists import page
from reddit.reddit_web.targets import BASE, parse_target

REDIRECTS = (301, 302, 303, 307, 308)
HOPS = 3


def _location(value, code):
    """A redirect target on www.reddit.com as (path, query), or an error with `code`."""
    if isinstance(value, str) and value.startswith('/') and not value.startswith('//'):
        value = BASE + value
    if not isinstance(value, str) or any(c in value for c in ' \t\r\n\\'):
        raise RedditError(code, 'Reddit redirected to an address this skill does not follow.',
                          'Open the link in the Aside browser and pass its permalink.')
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        port = 'bad'
    if parts.scheme != 'https' or parts.netloc != 'www.reddit.com' or port is not None or \
            any(segment in ('.', '..') for segment in parts.path.split('/')):
        raise RedditError(code, 'Reddit redirected to an address this skill does not follow.',
                          'Open the link in the Aside browser and pass its permalink.')
    return parts.path, dict(parse_qsl(parts.query))


class Client:
    """One invocation's Reddit: an Aside runner (fetch(args) → envelope) and a guard (request(bucket) → slot)."""

    def __init__(self, aside, guard, verbose=False):
        self._aside = aside
        self._guard = guard
        self._verbose = verbose

    def _send(self, request):
        """One request in one guard slot: the envelope, with headers reported and blocks recorded."""
        args = {'url': request.url} if request.url else {'path': request.path, 'query': request.query}
        with self._guard.request(request.bucket, metered=request.metered) as slot:
            envelope = self._aside.fetch(args)
            slot.report(envelope['ratelimit'])
            if self._verbose:
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
                                    personal=request.personal, wiki=request.bucket == 'wiki')
            except RedditError as error:
                slot.classify(outcome(error))
                if error.reason == 'rate_limit':
                    slot.rate_limit(rate_limit_seconds(envelope['ratelimit']))
                elif error.reason == 'challenge':
                    slot.challenge()
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
            path, query = _location(envelope.get('location'), 6)
            if path.endswith('/.json'):
                path = path[:-len('/.json')] + '.json'
            if routes.bucket_of(path, 6) != request.bucket:
                raise RedditError(6, 'Reddit redirected to another kind of endpoint.', 'Report this as a skill bug.')
            request = replace(request, path=path, query=query)
        raise RedditError(6, f'Reddit redirected more than {HOPS - 1} times.', 'Open the link in the Aside browser and '
                                                                               'pass its permalink.')

    def resolve(self, target):
        """A share link's post or comment target (each hop a request, at most HOPS); other targets unchanged."""
        if target.kind != 'share':
            return target
        url = target.url
        for _ in range(HOPS):
            envelope = self._send(routes.share(url))
            if envelope['status'] in REDIRECTS:
                path, _query = _location(envelope.get('location'), 2)
            else:
                path, _query = _location(envelope['url'], 2)
            try:
                found = parse_target(BASE + path)
            except RedditError:
                found = None
            if found is not None and found.kind in ('post', 'comment'):
                return found
            if found is None or found.kind != 'share' or envelope['status'] not in REDIRECTS:
                break
            url = found.url
        raise RedditError(2, 'The share link did not lead to a post or comment.', 'Open the share link in the Aside '
                                                                                  'browser and pass the post\'s '
                                                                                  'permalink.')

    def account(self):
        """The Reddit account the browser is logged in to (one request); login required raises 4."""
        return self.get(routes.me())['data']['name']

    def listing(self, request):
        """(records, after) of one listing page; an explicitly empty page is ([], None)."""
        try:
            body = self.get(request)
        except RedditError as error:
            if error.code == 7:
                return [], None
            raise
        if request.expect == 'duplicates':
            return page(body[1])
        return page(body)

    def thread(self, post_id, sort, comment_id=None, context=None):
        """(post record, items) of a post read, or of one comment's subtree (comment_id with context 0)."""
        return tree.thread(self.get(routes.post(post_id, sort, comment_id, context)))

    def expand(self, post_id, ids, sort):
        """Items of one comment expansion; [] when Reddit sent nothing for these ids."""
        try:
            return tree.expansion(self.get(routes.morechildren(post_id, ids, sort)))
        except RedditError as error:
            if error.code == 7:
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

    def wiki_page(self, sub, page):
        return wiki_page(sub, page, self.get(routes.wiki_page(sub, page))['data'])

    def wiki_index(self, sub):
        return wiki_index(sub, self.get(routes.wiki_index(sub))['data'])
