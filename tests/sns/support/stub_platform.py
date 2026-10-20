"""Two made-up platforms that run the whole shared pipeline before any real platform exists:

alpha — tab-less fetch (like Reddit or Naver), account-scoped protection, days in KST; feed is newest first, ranked never
  ends, post reads one record.
beta — a dedicated tab (like Threads or Facebook), a server-announced bucket (like Reddit), local days; its tab is
  closed first when idle.

Their clients follow the client protocol reading.Platform documents, with the fewest moving parts; the fake Aside
answers their snippets `alpha.get` (a fetch envelope {status, body}) and `beta.state` / `beta.query` (tab calls).
"""
from types import SimpleNamespace
from urllib.parse import urlsplit

from sns import reading
from sns.clock import KST
from sns.errors import SnsError
from sns.limits import Fact, LimitPolicy
from sns.page import Page
from sns.text import limit_of, shown, time
from sns.window import WindowPolicy

GET = 'async (args) => { /* sns-snippet: alpha.get */ } // sns-snippet: alpha.get'
STATE = '() => null // sns-snippet: beta.state'
QUERY = '(args) => null // sns-snippet: beta.query'
START = 'https://beta.test/home'


def _records(items, label='p'):
    return items


def render(envelope, chars, command):
    lines = []
    for index, record in enumerate(envelope.get('results') or [], 1):
        lines.append(f'[p{index}] {record.get("id")} · {time(record.get("created_at"))} · '
                     f'{shown(record.get("text"), limit_of(chars))} · url: {record.get("url")}')
    return lines


# --- alpha: fetch ---------------------------------------------------------------------------------------------------

class AlphaClient:
    def __init__(self, connection):
        self.aside, self.guard = connection.aside, connection.guard

    def start(self):
        return None

    def get(self, args):
        with self.guard.request() as slot:
            answer = self.aside.run(GET, args)
            status, body = answer.get('status'), answer.get('body') or {}
            if status == 429:
                slot.classify('rate_limited')
                raise slot.hold(body.get('retry_at'))
            if body.get('network_blocked'):
                slot.classify('network_blocked')
                raise slot.block('network_blocked', viewer=body.get('viewer'))
            if status == 401:
                slot.classify('login_required')
                raise SnsError('login', 'Alpha login is required in the Aside browser.', 'Log in, then retry.')
            if status == 404:
                slot.classify('not_found')
                raise SnsError('unavailable', 'This alpha post does not exist.', 'Check the link.')
            if status != 200:
                slot.classify('failed')
                raise SnsError('failed', f'Alpha answered {status}.', 'Retry later.')
            slot.classify('ok')
            return body

    def viewer(self):
        viewer = self.get({'path': '/me'}).get('viewer')
        if not viewer:
            raise SnsError('login', 'Alpha login is required in the Aside browser.', 'Log in, then retry.')
        return viewer

    def page(self, path, cursor):
        body = self.get({'path': path, 'cursor': cursor})
        return Page(body.get('items') or [], next=body.get('next'), end=not body.get('next'),
                    left_out={'promoted': body['promoted']} if body.get('promoted') else {},
                    reported_total=body.get('total'))

    def verify(self, check):
        viewer = self.viewer()
        named = (check.person or {}).get('viewer')
        if named and named != viewer:
            raise SnsError('blocked', 'The block stays: it was recorded for another account.', 'A person should check.',
                           reason='verification', verification_reason='account_mismatch')

    def release(self):
        return None

    def release_tab(self):
        return True

    def report(self):
        return {}

    def doctor(self):
        return {'alpha_check': 'fine'}


def _alpha_locate(url):
    parts = urlsplit(url if '://' in url else 'https://' + url)
    if parts.hostname == 'alpha.test' and parts.path.startswith('/p/'):
        return 'post', url
    return None


ALPHA_PLATFORM = reading.Platform(
    key='alpha', title='Alpha', site='alpha.test', transport='fetch',
    policy=LimitPolicy(scope='account', hold_seconds=1800, person=('network_blocked',), pace=(0.5, 0.8)),
    window=WindowPolicy(tz=KST), connect=AlphaClient, render=render,
    schemas={'post': {'object': 'post', 'description': 'An alpha post.', 'fields': {'id': 'string'}}},
    locate=_alpha_locate)


def alpha_feed(invocation):
    options = invocation.options

    def reader(connection, state, out):
        return reading.read_list(connection, state, out, order='newest_first', command='feed', target=None,
                                 identity={}, fetch=lambda cursor: connection.client.page('/feed', cursor),
                                 notes={'promoted': 'promoted entries (ads)'})
    window = {'since': options.get('since'), 'until': options.get('until'), 'order': 'newest_first'} \
        if options.get('since') or options.get('until') else None
    return reading.run(ALPHA_PLATFORM, invocation, command='feed', target=None, identity={}, reader=reader,
                       window=window)


def alpha_ranked(invocation):
    def reader(connection, state, out):
        return reading.read_list(connection, state, out, order='ranked', command='ranked', target=None, identity={},
                                 fetch=lambda cursor: connection.client.page('/ranked', cursor))
    return reading.run(ALPHA_PLATFORM, invocation, command='ranked', target=None, identity={}, reader=reader,
                       endless=True)


def alpha_post(invocation):
    target = invocation.options['target']
    if not _alpha_locate(target):
        raise SnsError('argument', 'An alpha post is https://alpha.test/p/<id>.', 'Pass a post URL.')

    def reader(connection, state, out):
        record = connection.client.get({'path': urlsplit(target).path})
        return {'results': [record], 'stop_reason': 'exhausted'}
    return reading.run(ALPHA_PLATFORM, invocation, command='post', target=target, identity={}, reader=reader,
                       bound=False)


LIST = ['limit', 'chars', 'after', 'out', 'json']
ALPHA = SimpleNamespace(
    PLATFORM=ALPHA_PLATFORM, CHOICES={},
    COMMANDS={
        'feed': {'help': 'Read the alpha feed, newest first.', 'run': alpha_feed,
                 'arguments': ['since', 'until', *LIST], 'epilog': ['Without --limit, a window or --out it reads one '
                                                                    'page; more: continues.'],
                 'exits': (0, 2, 3, 4, 5, 6, 7, 8)},
        'ranked': {'help': 'Read the ranked alpha feed.', 'run': alpha_ranked, 'arguments': list(LIST),
                   'epilog': ['It never ends by itself: --out needs --limit.'], 'exits': (0, 2, 3, 4, 5, 6, 7, 8)},
        'post': {'help': 'Read one alpha post.', 'run': alpha_post,
                 'arguments': [(('target',), {'metavar': 'URL', 'help': 'https://alpha.test/p/<id>'}), 'chars', 'json'],
                 'exits': (0, 2, 3, 4, 5, 6, 9)},
    })


# --- beta: a dedicated tab ------------------------------------------------------------------------------------------

class BetaClient:
    def __init__(self, connection):
        self.connection = connection
        self.aside, self.guard, self.session = connection.aside, connection.guard, connection.session
        self.tab, self.token, self.viewer_id = None, None, None

    def start(self):
        with self.session.opening():
            self.session.reload()
            tabs = {t['target_id']: t['url'] for t in self.aside.tabs()}
            if self.session.tab in tabs and tabs[self.session.tab].startswith('https://beta.test/'):
                self.tab = self.session.tab
            else:
                with self.guard.request(setup=True, kind='setup') as slot:
                    self.aside.open(START)
                    new = [t for t in self.aside.tabs() if t['target_id'] not in tabs]
                    if len(new) != 1:
                        slot.cancel()
                        raise SnsError('aside', 'The beta tab could not be told apart.', 'Run doctor.')
                    self.tab = new[0]['target_id']
                    slot.charge(5)
                self.session.set_tab(self.tab)
            self.token = self.session.touch()
        state = self.aside.evaluate(self.tab, STATE, {})
        if not state.get('viewer'):
            raise SnsError('login', 'Beta login is required in the Aside browser.', 'Log in, then retry.')
        self.viewer_id = state['viewer']
        return self.viewer_id

    def viewer(self):
        return self.viewer_id

    def page(self, cursor):
        with self.guard.request(scope='general') as slot:
            answer = self.aside.evaluate(self.tab, QUERY, {'cursor': cursor})
            limit = answer.get('headers')
            if limit:
                slot.fact('general', Fact(limit['limit'], limit['remaining'],
                                          self.guard.clock.time() + limit['reset']))
            if answer.get('status') == 429:
                slot.classify('rate_limited')
                raise slot.hold(scope='general')
            slot.classify('ok')
        return Page(answer.get('items') or [], next=answer.get('next'), end=not answer.get('next'))

    def verify(self, check):
        self.start()

    def release(self):
        if self.token:
            self.session.release(self.token)
        return self.token

    def release_tab(self):
        self.tab = self.session.tab
        emptied = self.connection.empty_tab(self.tab)
        self.session.set_dirty(not emptied)
        return emptied

    def report(self):
        return {}

    def doctor(self):
        return {'tab': self.tab}


def _beta_locate(url):
    parts = urlsplit(url if '://' in url else 'https://' + url)
    return ('feed', url) if parts.hostname == 'beta.test' else None


BETA_PLATFORM = reading.Platform(
    key='beta', title='Beta', site='beta.test', transport='tab',
    policy=LimitPolicy(scope='bucket', slow='used', hold_seconds=600, person=('challenge',), pace=(1.0, 2.0)),
    window=WindowPolicy(), connect=BetaClient, render=render, locate=_beta_locate, unblock_scope='general',
    idle_action='close')


def beta_feed(invocation):
    def reader(connection, state, out):
        return reading.read_list(connection, state, out, order='finite', command='feed', target=None, identity={},
                                 fetch=connection.client.page)
    return reading.run(BETA_PLATFORM, invocation, command='feed', target=None, identity={}, reader=reader)


BETA = SimpleNamespace(
    PLATFORM=BETA_PLATFORM, CHOICES={},
    COMMANDS={'feed': {'help': 'Read the beta feed.', 'run': beta_feed, 'arguments': list(LIST),
                       'exits': (0, 2, 3, 4, 5, 6, 7, 8, 10)}})

STUBS = {'alpha': ALPHA, 'beta': BETA}
