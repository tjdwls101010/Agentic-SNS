"""The Naver Blog client: every request goes out through fetch.js, one `aside repl` run per request, inside the account
guard, and comes back classified.

Naver needs no token, signature or tab — a referer per host is its whole header contract — so each request is one REPL
`fetch` with the browser's cookies, sent from outside any tab. A blog's own domain address answers not_exist_blog;
the client then reads blog.naver.com/{id} once for the canonical id and retries under it, so every caller sees the
same canonical ids.

The client follows the protocol reading.Platform documents (a tab-less fetch platform): start() has nothing to open,
viewer() asks Naver who the browser is (one request, current-user), verify() is the unblock check's one request. A 429
is recorded as a hold and a network block as a person block before the request's slot closes.
"""
import base64
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from sns.errors import SnsError, diagnostic

from sns.naver_blog.web import targets
from sns.naver_blog.web.classify import at, classify
from sns.naver_blog.web.pages import Fetched, Policy
from sns.naver_blog.web.routes import allowed, build, frame_blog_id, image_host, operation

FETCH = Path(__file__).with_name('fetch.js').read_text(encoding='utf-8')
_CHECK = 'Check that Aside is running, then run doctor.'
_LOGIN = 'Log in to Naver in the Aside browser, then run doctor.'


def policy(name):
    row = operation(name)
    return Policy(row.pagination, row.page_size, row.ceiling)


def _envelope(value):
    """What the fetch snippet returned, checked: a refusal or a network failure raises, a malformed answer is Aside's."""
    if not isinstance(value, dict):
        raise SnsError('aside', 'Aside returned output this skill cannot read.', _CHECK, reason='invalid')
    if value.get('error') == 'refused':
        raise SnsError('failed', f'The read-only gate refused a request ({value.get("message")}).',
                       'This is a bug in the skill; report the command you ran.', reason='drift')
    if value.get('error') == 'network':
        raise SnsError('failed', 'The request did not reach Naver (network failure).',
                       'Check the network, then run the same command again.', reason='transient')
    if 'body_file' in value or (type(value.get('status')) is not int or not 100 <= value['status'] <= 599
                                or not isinstance(value.get('url'), str) or not isinstance(value.get('body'), str)
                                or not isinstance(value.get('location'), (str, type(None)))
                                or not isinstance(value.get('content_type'), (str, type(None)))
                                or not isinstance(value.get('b64'), (str, type(None)))):
        raise SnsError('aside', 'Aside returned a response envelope this skill cannot read.', _CHECK, reason='invalid')
    return value


def _outcome(error):
    """The request-log label of an answer that raised."""
    return {'rate_limit': 'rate_limited', 'restricted': 'restricted'}.get(error.reason) or \
        {'login': 'login_required', 'unavailable': 'unavailable', 'argument': 'argument'}.get(error.kind, 'failed')


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


class Client:
    """One invocation's connection to Naver Blog: the connection's Aside runs the fetch snippet, its guard spaces and
    records each request, its session keeps the viewer as a hint."""

    def __init__(self, connection):
        self.connection = connection
        self.aside, self.guard, self.session = connection.aside, connection.guard, connection.session
        self.canonical = {}   # a domain address → the blog id Naver answered under

    # --- the client protocol -----------------------------------------------------------------------------------

    def start(self):
        return None  # nothing to open: the account is asked for only by the readings that need it

    def viewer(self):
        """The Naver blog id of the account the browser is logged in to (current-user: one request); logged out is a
        login failure, Naver's network block a person block. What it says is kept as a hint for 12 hours."""
        result = at(self.get('current_user'), 'result')
        name = str(result['userId'])
        self.connection.seen(name)
        self.session.remember_viewer(name)
        return name

    def verify(self, check):
        """The unblock check: one current-user request (it uses the check's reservation), clean only for the account
        the block was recorded for."""
        name = self.viewer()
        named = (check.person or {}).get('viewer')
        if named and named != name:
            raise SnsError('blocked', f'The block stays: it was recorded for {named}, but the browser is logged in '
                                      f'to {name}.', 'A person should check Naver Blog as the account that was blocked.',
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
        return {'viewer': name, 'limits': self.guard.state()['scopes'], 'requests_last_hour': recent['last_hour'],
                'requests_last_day': recent['last_day']}

    # --- one request -------------------------------------------------------------------------------------------

    def send(self, name, page=None, ids=None, *, kind='query', url=None):
        """One request of operation `name` (or an image `url`), classified; a hold or a block is recorded before the
        guard's lock is released."""
        ids = dict(ids or {})
        if url is not None:
            parts = urlsplit(url)
            host, path, query = (parts.hostname or '').lower(), parts.path, parts.query or None
            if parts.scheme != 'https' or not image_host(host) or not allowed(host, path, query):
                raise SnsError('unavailable', f'The picture is hosted at {host or "an unreadable address"}, outside '
                                              'Naver, so it is not fetched.', 'Its host is shown in post\'s [image N] '
                                                                             'line.', reason='photo_offsite')
            query = dict(parse_qsl(query)) if query else None
            accept = 'image'
        else:
            host, path, query = build(name, page=page, **ids)
            accept = operation(name).accept
        with self.guard.request(kind=kind) as slot:
            envelope = _envelope(self.aside.run(FETCH, {'host': host, 'path': path, 'query': query, 'accept': accept}))
            if self.connection.verbose:
                diagnostic('request', op=name, host=host, path=path, status=envelope['status'])
            try:
                payload = classify(name, envelope, ids)
                if name == 'current_user':
                    self._check_viewer(payload['result'], slot)
            except SnsError as error:
                slot.classify(_outcome(error))
                if error.reason == 'rate_limit':
                    raise slot.hold() from None
                raise
            slot.classify('ok')
            return payload

    def _check_viewer(self, result, slot):
        """current-user must name a logged-in account; Naver's network block is a person block (inside an unblock
        check it only fails the check: the block it would record is the one standing)."""
        if result.get('loggedIn') is not True or not result.get('userId'):
            raise SnsError('login', 'Naver login is required in the Aside browser.', _LOGIN, reason='logged_out')
        if result.get('networkBlocked') is True:
            if self.guard.checking:
                raise SnsError('blocked', 'The block stays: Naver still reports this account as network-blocked.',
                               'Tell the person: it is Naver\'s own flag, and only Naver lifts it.',
                               reason='verification', verification_reason='still_blocked')
            raise slot.block('network_blocked', viewer=str(result['userId']))

    def get(self, name, page=None, **ids):
        """The classified answer of one operation. A blog id Naver does not know is tried once as a domain address."""
        blog = ids.get('blogId')
        if blog in self.canonical:
            ids['blogId'] = self.canonical[blog]
        try:
            return self.send(name, page, ids)
        except SnsError as error:
            if error.reason not in ('not_exist_blog', 'blog_id_invalidate') or not blog or blog in self.canonical:
                raise
        canonical = frame_blog_id(self.send('blog_frame', None, {'blogId': blog}))
        self.canonical[blog] = canonical
        if canonical == blog:
            raise SnsError('unavailable', f'Blog {blog} does not exist or this account cannot read it.',
                           'Check the id.', reason='not_exist_blog')
        return self.send(name, page, {**ids, 'blogId': canonical})

    def page(self, name, number, build_record, **ids):
        """One page of a listing as a Fetched of records; what arrived beside a restriction rides on the error."""
        row = operation(name)
        try:
            payload = self.get(name, page=number, **ids)
        except SnsError as error:
            if error.reason == 'restricted' and getattr(error, 'payload', None) is not None:
                error.records = _records(build_record, at(error.payload, row.leaf) or [])
            raise
        items = at(payload, row.leaf) if row.leaf else None
        items = items if isinstance(items, list) else []
        last = at(payload, row.marker) if row.marker else None
        if row.marker and (isinstance(last, bool) or not isinstance(last, int)):
            last = _int(last)
            if last is None and items:
                raise SnsError('failed', f'A page did not say how many pages there are ({row.marker}).',
                               'Run doctor; the response shape changed.', reason='drift')
        following = None
        if name == 'comments':   # the comment box names its own next page
            model = at(payload, 'result.pageModel') or {}
            following = model.get('nextPage') if isinstance(model.get('nextPage'), int) and model['nextPage'] > number \
                else None
            last = last if last is not None else number
        total = _int(at(payload, row.total)) if row.total else None
        records = _records(build_record, items)
        return Fetched(items=records, raw_count=len(items), last_page=last if last is not None else (
            number if row.marker else None), next_page=following,
            reported_total=None if total == 0 and items else total), payload

    def target(self, text, kind):
        """A typed target, with a naver.me link resolved by one counted hop."""
        target = targets.parse(text, kind)
        if target.short:
            hop = self.send('short_link', None, {'code': target.short})
            target = targets.destination(hop.get('location'), kind)
        return target

    def resolve(self, code):
        """Where naver.me/<code> leads, without following it."""
        hop = self.send('short_link', None, {'code': code})
        return {'status': hop['status'], 'location': hop.get('location')}

    def image(self, url):
        """(bytes, content type) of one Naver photo; a response that is not a picture, or over 10 MB, is refused."""
        envelope = self.send('image', url=url, kind='image')
        if envelope['status'] != 200:
            raise SnsError('failed' if envelope['status'] >= 500 else 'unavailable',
                           f'The photo answered HTTP {envelope["status"]}.', 'Read the post again; the photo may be '
                                                                            'gone.', reason='photo_unavailable')
        if envelope.get('oversize'):
            raise SnsError('partial', f'The photo is larger than 10 MB ({envelope["oversize"]} bytes); it was not '
                                      'saved.', 'Open it in the browser instead.', reason='photo_too_large')
        if not str(envelope.get('content_type') or '').startswith('image/') or envelope.get('b64') is None:
            raise SnsError('failed', 'The photo address did not answer with a picture.', 'Read the post again.',
                           reason='drift')
        return base64.b64decode(envelope['b64']), envelope['content_type'].split(';')[0].strip()


def _records(build_record, items):
    """Records of one page as dicts; a builder may return a record (to_dict) or a dict, and None to skip an item."""
    built = (build_record(item) for item in items)
    return [r.to_dict() if hasattr(r, 'to_dict') else r for r in built if r]
