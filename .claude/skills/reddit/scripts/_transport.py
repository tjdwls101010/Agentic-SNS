"""Read-only paths and one response classifier above the Aside bridge."""
from contextlib import contextmanager
import json
import math
import re
from urllib.parse import parse_qsl, urlsplit

from ._aside import run_snippet
from ._budget import Budget
from ._errors import RedditError
from ._target import Target, parse_target


def _listing(body):
    pending = [(body, False)]
    while pending:
        listing, replies_only = pending.pop()
        if (not isinstance(listing, dict) or listing.get('kind') != 'Listing'
                or not isinstance(listing.get('data'), dict)
                or not isinstance(listing['data'].get('children'), list)):
            return False
        kinds = ('t1', 'more') if replies_only else ('t1', 't2', 't3', 't5', 'more')
        for child in listing['data']['children']:
            if (not isinstance(child, dict) or child.get('kind') not in kinds
                    or not isinstance(child.get('data'), dict)):
                return False
            if child['kind'] == 't1':
                replies = child['data'].get('replies')
                if replies is not None and replies != '':
                    pending.append((replies, True))
    return True


def classify(envelope, expect, *, personal=False, budget=None):
    """Return parsed body or a public error; optional active Budget persists blocking decisions."""
    status, raw, url = envelope['status'], envelope['body'], envelope['url']
    if status == 429:
        try:
            seconds = float(envelope['ratelimit']['reset'])
            if not math.isfinite(seconds) or seconds < 0:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            seconds = 600
        if budget:
            budget.block('rate_limit', seconds)
        raise RedditError(5, 'Reddit rate limit reached.', f'Stop requests; retry after {math.ceil(seconds)} seconds.')
    html = raw.lstrip().startswith('<')
    if status == 403 and html and 'js_challenge' in (raw + url).lower():
        if budget:
            budget.block('challenge')
        raise RedditError(5, 'Reddit browser challenge.', 'Check Reddit in Aside, then run doctor --unblock.')
    if status >= 500 or not raw or html:
        raise RedditError(6, 'Reddit returned an unavailable or non-JSON response.')
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        raise RedditError(6, 'Reddit returned invalid JSON.') from None
    if status == 404:
        raise RedditError(9, 'Reddit target does not exist.')
    if status == 403 and isinstance(body, dict):
        reason = body.get('reason')
        if reason in ('private', 'gold_only', 'quarantined', 'banned', 'suspended', 'user_suspended'):
            raise RedditError(9, f'Reddit target is closed: {reason}.')
        raise RedditError(6, f'Reddit rejected the request: reason={str(reason)[:120]}.')
    if not 200 <= status < 300:
        raise RedditError(6, f'Unexpected Reddit HTTP status {status}.')
    if expect == 'me' and isinstance(body, dict) and body.get('kind') == 't2' and isinstance(body.get('data'), dict):
        if not body['data'].get('name'):
            raise RedditError(4, 'Reddit login is required.')
        if not isinstance(body['data']['name'], str):
            raise RedditError(6, 'Reddit returned a malformed account name.')
    if personal and _listing(body) and body['data'].get('modhash') == '':
        raise RedditError(4, 'Reddit login is required.')
    empty = False
    if expect == 'listing':
        valid = _listing(body)
        empty = valid and not body['data']['children']
    elif expect in {'thing:t2', 'thing:t5', 'me'}:
        kind = 't2' if expect == 'me' else expect.split(':')[1]
        valid = isinstance(body, dict) and body.get('kind') == kind and isinstance(body.get('data'), dict)
    elif expect in {'post_pair', 'duplicates'}:
        valid = (isinstance(body, list) and len(body) == 2 and all(_listing(item) for item in body)
                 and len(body[0]['data']['children']) == 1 and body[0]['data']['children'][0]['kind'] == 't3')
        if valid:
            kinds = {'t3'} if expect == 'duplicates' else {'t1', 'more'}
            valid = all(child['kind'] in kinds for child in body[1]['data']['children'])
    elif expect == 'rules':
        valid = (isinstance(body, dict) and isinstance(body.get('rules'), list)
                 and all(isinstance(rule, dict) for rule in body['rules']))
    elif expect == 'morechildren':
        data = body.get('json') if isinstance(body, dict) else None
        valid = isinstance(data, dict) and data.get('errors') == [] and isinstance(data.get('data'), dict)
        things = data['data'].get('things') if valid else None
        valid = (valid and isinstance(things, list) and all(isinstance(thing, dict)
                 and thing.get('kind') in ('t1', 'more') and isinstance(thing.get('data'), dict) for thing in things))
        valid = valid and _listing({'kind': 'Listing', 'data': {'children': things}})
        empty = valid and not things
    else:
        raise RedditError(2, f'Unknown expected response: {expect}.')
    if not valid:
        raise RedditError(6, f'Reddit response does not match {expect}.')
    if empty:
        raise RedditError(7, 'Reddit returned an explicitly empty result.')
    return body


def _path(path):
    if (not isinstance(path, str) or not re.fullmatch(r'/(?!/)[A-Za-z0-9_+./-]+\.json', path)
            or any(part in {'.', '..'} for part in path.split('/'))):
        raise RedditError(2, 'Expected a Reddit JSON path, without a host or query string.')
    routes = (
        r'/(best|hot|new|top|rising)\.json',
        r'/r/[A-Za-z0-9_+]+/(hot|new|top|rising|controversial|search|about|about/rules)\.json',
        r'/(?:r/[A-Za-z0-9_]+/)?comments/[A-Za-z0-9]+(?:/[^/]+/[A-Za-z0-9]+)?\.json',
        r'/(comments/[A-Za-z0-9]+(?:/_/[A-Za-z0-9]+)?|duplicates/[A-Za-z0-9]+)\.json',
        r'/user/[A-Za-z0-9_-]+/(about|overview|submitted|comments|saved|upvoted)\.json',
        r'/(search|subreddits/search|subreddits/mine/subscriber|api/me|api/info|api/morechildren|api/subreddit_autocomplete_v2)\.json',
    )
    if not any(re.fullmatch(route, path) for route in routes):
        raise RedditError(2, 'Unsupported read-only Reddit endpoint.')
    return path


def _safe_url(url):
    if not isinstance(url, str) or re.search(r'[\\\s]', url):
        raise RedditError(2, 'Unsafe Reddit redirect.')
    try:
        parts = urlsplit(url)
    except ValueError:
        raise RedditError(2, 'Malformed Reddit redirect.') from None
    if parts.scheme != 'https' or parts.netloc != 'www.reddit.com':
        raise RedditError(2, 'Redirect must use https://www.reddit.com without credentials or a port.')
    if any(part in {'.', '..'} for part in parts.path.split('/')):
        raise RedditError(2, 'Unsafe Reddit redirect path.')
    if '%' in parts.path:
        parse_target(url)  # Only ignored title slugs may contain valid percent escapes.
    return parts


class Transport:
    def __init__(self, *, budget=None, max_requests=8):
        # 성진: 60회는 한 호출이 10분 창 100회 중 40회를 다른 호출에 남기는 값, 창이 커지면 올린다
        if type(max_requests) is not int or not 1 <= max_requests <= 60:
            raise RedditError(2, 'Request budget must be between 1 and 60.')
        self._budget = budget if budget is not None else Budget()
        self.max_requests = max_requests
        self.requests = 0

    @property
    def budget(self):
        return self._budget.snapshot

    def get(self, path, expect, query=None, personal=False):
        """Return parsed JSON; manual redirects get individual reservations, at most three hops."""
        _path(path)
        if expect not in {'listing', 'thing:t2', 'thing:t5', 'me', 'rules', 'morechildren', 'post_pair', 'duplicates'}:
            raise RedditError(2, f'Unknown expected response: {expect}.')
        if query is not None and not isinstance(query, dict):
            raise RedditError(2, 'Query must be a mapping.')
        for hop in range(3):
            with self._request():
                envelope = run_snippet('fetch', {'path': path, 'query': query or {}})
                self._budget.observe(envelope['ratelimit'])
                _safe_url(envelope['url'])
                if envelope['status'] not in {301, 302, 303, 307, 308}:
                    return classify(envelope, expect, personal=personal, budget=self._budget)
                location = envelope.get('location')
                if isinstance(location, str) and location.startswith('/') and not location.startswith('//'):
                    location = 'https://www.reddit.com' + location
                parts = _safe_url(location)
                path, query = _path(parts.path), dict(parse_qsl(parts.query))
                if hop == 2:
                    raise RedditError(6, 'Reddit redirect exceeds three hops.')

    @contextmanager
    def _request(self):
        if self.requests >= self.max_requests:
            raise RedditError(8, 'This command has reached its request budget.')
        with self._budget.request():
            self.requests += 1
            yield

    def resolve(self, value):
        """Resolve at most three actual requests; each hop reserves and observes its own budget."""
        target = value if isinstance(value, Target) else parse_target(value)
        if target.kind != 'share':
            return target
        url = target.name
        for hop in range(3):
            _safe_url(url)
            with self._request():
                envelope = run_snippet('resolve', {'url': url})
                self._budget.observe(envelope['ratelimit'])
                _safe_url(envelope['url'])
                redirect = envelope['status'] in {301, 302, 303, 307, 308}
                if redirect:
                    url = envelope.get('location')
                    if isinstance(url, str) and url.startswith('/') and not url.startswith('//'):
                        url = 'https://www.reddit.com' + url
                    _safe_url(url)
                elif 200 <= envelope['status'] < 300:
                    url = envelope['url']
                else:
                    classify(envelope, 'post_pair', budget=self._budget)
                try:
                    resolved = parse_target(url)
                except RedditError:
                    resolved = None
                if resolved and resolved.kind in {'post', 'comment'}:
                    return resolved
                if not redirect or hop == 2:
                    raise RedditError(2, 'Share link did not resolve within three requests.',
                                      'Open the share link in Aside and use its post permalink.')

    def doctor(self, *, unblock=False):
        """Check login with one budgeted request and report local cache/budget metadata."""
        if unblock:
            self._budget.unblock()
        body = self.get('/api/me.json', 'me')
        size = sum(p.stat().st_size for p in (self._budget.home / 'threads').glob('**/*') if p.is_file())
        return {'account': body['data']['name'], 'requests': self.requests, 'budget': self.budget, 'cache_bytes': size}


def build_request(surface, target=None, **options):
    """Return kwargs for Transport.get; all CLI-to-server mappings live here."""
    target = parse_target(target) if isinstance(target, str) else target
    query = {key: value for key, value in options.items() if value is not None}
    expect, personal = 'listing', False

    def require(*kinds):
        if not isinstance(target, Target) or target.kind not in kinds:
            raise RedditError(2, f'{surface} requires {" or ".join(kinds)}.', 'Prefix communities with r/ and users with u/.')

    def choice(key, default, allowed):
        value = query.pop(key, default)
        if value not in allowed:
            raise RedditError(2, f'Invalid {key}: {value}.')
        return value

    if surface == 'home':
        sort = choice('sort', 'best', {'best', 'hot', 'new', 'top', 'rising'})
        path, personal = f'/{sort}.json', True
    elif surface == 'sub':
        require('subreddit', 'subreddits')
        sort = choice('sort', 'hot', {'hot', 'new', 'top', 'rising', 'controversial'})
        path = f'/r/{target.sub}/{sort}.json'
    elif surface in {'post', 'comments', 'related', 'morechildren'}:
        require('post', 'comment')
        if surface == 'related':
            path, expect = f'/duplicates/{target.post_id}.json', 'duplicates'
        elif surface == 'morechildren':
            path, expect = '/api/morechildren.json', 'morechildren'
            ids = query.get('children')
            ids = ids.split(',') if isinstance(ids, str) else ids
            if not isinstance(ids, (list, tuple)) or not 1 <= len(ids) <= 100 or any(
                    not isinstance(i, str) or not re.fullmatch('[A-Za-z0-9]{1,10}', i) for i in ids):
                raise RedditError(2, 'morechildren needs 1 to 100 comment ids.')
            query.update(children=','.join(ids), link_id='t3_' + target.post_id, api_type='json')
        else:
            suffix = f'/_/{target.comment_id}' if surface == 'comments' and target.comment_id else ''
            path, expect = f'/comments/{target.post_id}{suffix}.json', 'post_pair'
            query = {'limit': 500, 'depth': 10, **query}
        if surface != 'related':
            sort = choice('sort', 'best', {'best', 'confidence', 'top', 'new', 'controversial', 'old', 'qa'})
            query['sort'] = 'confidence' if sort == 'best' else sort
    elif surface == 'user':
        require('user')
        kind = choice('type', 'overview', {'overview', 'posts', 'comments'})
        path = f'/user/{target.user}/{"submitted" if kind == "posts" else kind}.json'
    elif surface in {'about', 'rules'}:
        require('subreddit', 'user')
        if target.kind == 'user':
            if surface == 'rules':
                raise RedditError(2, 'Rules require a subreddit.')
            path, expect = f'/user/{target.user}/about.json', 'thing:t2'
        else:
            path = f'/r/{target.sub}/about' + ('/rules' if surface == 'rules' else '') + '.json'
            expect = 'rules' if surface == 'rules' else 'thing:t5'
    elif surface == 'search':
        kind = choice('type', 'posts', {'posts', 'subs', 'users'})
        text = query.pop('text', query.pop('q', None))
        if not isinstance(text, str) or not text.strip():
            raise RedditError(2, 'Search requires nonempty text.')
        nsfw = query.pop('nsfw', False)
        query.update(q=text, type={'posts': 'link', 'subs': 'sr', 'users': 'user'}[kind])
        if nsfw:
            query['include_over_18'] = 'on'
        path = '/search.json'
        if target is not None:
            require('subreddit')
            path = f'/r/{target.sub}/search.json'
            query['restrict_sr'] = 1
    elif surface == 'me':
        kind = choice('type', 'subs', {'subs', 'saved', 'upvoted'})
        path = '/subreddits/mine/subscriber.json' if kind == 'subs' else f'/user/me/{kind}.json'
        personal = True
    elif surface == 'doctor':
        path, expect = '/api/me.json', 'me'
    elif surface == 'info':
        path = '/api/info.json'
    else:
        raise RedditError(2, f'Unknown Reddit surface: {surface}.')
    if 'time' in query:
        query['t'] = query.pop('time')
    return {'path': _path(path), 'expect': expect, 'query': query, 'personal': personal}
