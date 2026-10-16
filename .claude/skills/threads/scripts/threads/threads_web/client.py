"""The Threads web client: requests made from the skill's own www.threads.com tab, the way the app makes them.

The tab is opened once on a quiet screen (`aside <url>`) and reused; each read is one GraphQL request sent with the
page's own parameters and headers, one request per browser call. Query ids and provider values come from the app's
loaded module when it has one, else from what an earlier read learned, else from the bundled snapshot. When Threads
refuses a query, the client learns its current id once from the screen that uses it (one document read and the
static bundles it names) or, when the tab's own module was refused, reloads the tab once; a command never recovers
more than that. Every response the tab saw is checked for a block before the next request is sent.
"""
import json
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

from threads.errors import ThreadsError, diagnostic
from threads.threads_web import classify, learn, records

_SNIPPETS = Path(__file__).with_name('snippets')
_KIT = (_SNIPPETS / 'kit.js').read_text(encoding='utf-8').strip()
# Every page function is the shared kit (the tab's ledger and signal store) followed by its own body.
SNIPPETS = {path.stem: 'async (args) => {\n  const kit = (' + _KIT + ')(args);\n' + path.read_text(encoding='utf-8') + '}'
            for path in _SNIPPETS.glob('*.js') if path.stem != 'kit'}
SNAPSHOT = json.loads(Path(__file__).with_name('queries.json').read_text(encoding='utf-8'))
QUERIES = SNAPSHOT['queries']
START = SNAPSHOT['start_screen']
# What the page itself loads cannot be bounded or attributed exactly, so opening (or reloading) the tab is prepaid:
# measured 34 Threads requests on the search screen, 38 on home. Requests the page finishes later in the same
# command use up what is left of the reservation first.
OPEN_RESERVE = 40
LEARN_LIMIT = 3     # document reads one command may spend learning queries (each is one request)
RELOAD_LIMIT = 1    # tab reloads one command may spend when the app's own module was refused
LOAD_WAIT = 20      # seconds to wait for a tab to finish loading
_GONE = 'Run the command again; it opens a new tab.'


def snippet(name):
    """The page function the browser runs for `name` (state, query, page, modules, blank, navigate)."""
    return SNIPPETS[name]


def _int(value, default=0):
    return value if type(value) is int and value >= 0 else default


def _host(url):
    try:
        return urlsplit(url or '').hostname or ''
    except ValueError:
        return ''


class Client:
    """One invocation's connection to Threads.

    browser: the Aside system (tabs, open, evaluate). guard: account protection (request slots). memory: the session
    store (the dedicated tab, the use token, acknowledged signals, learned ids and renames).
    """

    def __init__(self, browser, guard, memory, verbose=False):
        self.browser, self.guard, self.memory, self.verbose = browser, guard, memory, verbose
        self.tab = None
        self.account_id = None
        self.opened_now = False
        self.reopened = False
        self.session_reset = False
        self.unwatched = 0
        self.token = None
        self.prepaid = {'setup': 0, 'budget': 0}
        self.recovery = {'learn': 0, 'reload': 0}

    # --- the tab ---------------------------------------------------------------------------------------------

    def start(self):
        """Find, re-check and if needed open the dedicated tab under the session lock; returns the account id."""
        with self.memory.opening():
            self.memory.reload()
            self.session_reset = self.memory.reset
            known = self.memory.tab
            entry = next((t for t in self.browser.tabs() if known and t['target_id'] == known), None)
            if entry and _host(entry['url']) == 'www.threads.com':
                self.tab = known
                with self.guard.observe() as slot:
                    state = self._state()
                    self.unwatched = _int(state.get('resources'))
                    self.guard.log_unwatched(self.unwatched)  # made between commands: logged, not charged
                    self._check(state, slot)
            elif entry and not _host(entry['url']):
                self.tab = known
                self._load(navigate=True)  # the tab this skill emptied earlier: send it back to Threads
            else:
                self._open()
            self.token = self.memory.touch()
        return self.account_id

    def _state(self, document=False):
        state = self.browser.evaluate(self.tab, SNIPPETS['state'], {'document': document, '__ack': self.memory.ack})
        if not isinstance(state, dict) or not isinstance(state.get('location'), str):
            raise ThreadsError(3, 'The Threads tab answered invalidly.', 'Run doctor.')
        return state

    def _open(self):
        """Open a new dedicated tab: its document and what the page loads are counted, outside the budget."""
        before = {t['target_id'] for t in self.browser.tabs()}
        with self.guard.request(reserve=OPEN_RESERVE, budgeted=False, kind='tab_open') as slot:
            self.browser.open(START)
            new = [t for t in self.browser.tabs() if t['target_id'] not in before and _host(t['url']).endswith('threads.com')]
            if not new:
                raise ThreadsError(3, 'Aside did not open the Threads tab.', 'Check Aside, then run doctor.')
            self.tab = new[-1]['target_id']
            self.memory.set_tab(self.tab)
            self.opened_now = True
            self._settle_load(slot)

    def _load(self, navigate):
        """Load Threads in the known tab again (it was emptied, or its app was refused): counted like opening."""
        with self.guard.request(reserve=OPEN_RESERVE, budgeted=False, kind='tab_open') as slot:
            if navigate:
                self.browser.evaluate(self.tab, SNIPPETS['navigate'], {'url': START})
            self.opened_now = self.reopened = True
            self._settle_load(slot)

    def _settle_load(self, slot):
        """Wait for the loaded app, then check the new page before any query: where it is, what loading it answered
        (a 429), and the document's own checkpoint and login markers."""
        deadline = time.monotonic() + LOAD_WAIT
        while True:
            try:
                state = self._state(document=True)
            except ThreadsError as error:
                # the page is replacing its document; a vanished tab or the time limit ends the wait
                if error.reason == 'tab_missing' or time.monotonic() > deadline:
                    raise
                time.sleep(1)
                continue
            if state.get('runtime') and state.get('user_id') or time.monotonic() > deadline:
                break
            if urlsplit(state['location']).path.startswith(('/challenge', '/checkpoint', '/accounts/login', '/login')):
                break
            time.sleep(1)
        seen = 1 + _int(state.get('resources'))
        slot.charge(seen)
        self.prepaid['setup'] = max(0, slot.reserved - seen)
        if state.get('document'):
            verdict = classify.document(state['document'])
            if verdict.block:
                self._stop(slot, verdict)
            if verdict.kind == 'login':
                raise verdict.error
        self._check(state, slot)

    def _check(self, state, slot):
        """Raise for what the tab shows: a block among its signals, its requests or its location (recorded in `slot`
        and the tab emptied first), a logout, a broken page, or another account."""
        self._signals(state, slot)
        if 429 in (state.get('statuses') or []):
            self._stop(slot, classify.response({'status': 429, 'url': state['location'], 'body': ''}, mode='graphql'))
        path = urlsplit(state['location']).path.lower()
        located = classify.response({'status': 200, 'url': state['location'], 'body': ''}, mode='page')
        if located.block:
            self._stop(slot, located)
        if located.kind == 'login' or path.startswith(('/accounts/login', '/login')):
            raise classify.response({'status': 200, 'url': 'https://www.threads.com/accounts/login/', 'body': ''},
                                    mode='page').error
        if not state.get('runtime') or _host(state['location']) != 'www.threads.com':
            raise ThreadsError(3, 'The Threads tab is not a working Threads page.', 'Run doctor; close the tab if it '
                                                                                   'keeps failing.')
        if not state.get('user_id') or state['user_id'] == '0':
            raise ThreadsError(4, 'Threads login is required in the Aside browser.', classify.LOGIN_FIX,
                               reason='login')
        if self.account_id is not None and state['user_id'] != self.account_id:
            raise ThreadsError(4, 'The Aside browser is now logged in to a different Threads account than when this '
                                  'command started.', 'Check which account Aside is logged in to, then rerun.',
                               reason='account_changed')
        self.account_id = state['user_id']

    def _signals(self, result, slot):
        """Classify the app responses the tab kept; a block is recorded and the tab emptied before anything else, and
        the signals are acknowledged only after that, so the tab drops them only once protection holds them."""
        signals = [s for s in result.get('signals') or [] if isinstance(s, dict)]
        worst = None
        for signal in signals:
            mode = 'graphql' if '/graphql' in str(signal.get('url')) or '/api/' in str(signal.get('url')) else 'page'
            verdict = classify.response({'status': signal.get('status'), 'url': signal.get('url') or '',
                                         'body': signal.get('body') or ''}, mode=mode)
            if verdict.block == 'checkpoint' or (verdict.block and worst is None) or (
                    verdict.kind == 'login' and worst is None):
                worst = verdict
        if worst is not None and worst.block:
            self._stop(slot, worst, acknowledge=signals)
        if signals:
            self.memory.acknowledge(max(s.get('at', 0) for s in signals if type(s.get('at')) in (int, float)))
        if worst is not None and worst.kind == 'login':
            raise worst.error

    def _stop(self, slot, verdict, acknowledge=()):
        """Record a block, empty the tab so the app stops polling, then raise."""
        slot.block(verdict.block)
        if acknowledge:
            self.memory.acknowledge(max(s.get('at', 0) for s in acknowledge if type(s.get('at')) in (int, float)))
        try:
            self.browser.evaluate(self.tab, SNIPPETS['blank'], {'__ack': self.memory.ack})
        except ThreadsError:
            pass  # a tab that is already gone polls nothing
        raise verdict.error

    def blank(self):
        """Empty the dedicated tab (about:blank, no request) after taking in what it saw."""
        if not self.tab:
            return False
        with self.guard.observe() as slot:
            report = self.browser.evaluate(self.tab, SNIPPETS['blank'], {'__ack': self.memory.ack})
            if isinstance(report, dict):
                self.guard.log_unwatched(_int(report.get('resources')))
                self._signals(report, slot)
        return True

    # --- requests --------------------------------------------------------------------------------------------

    def _request(self, name, args, verdict_of, label, budgeted=True, kind=None):
        """One guarded request: block check, budget and pacing; the response and every signal the tab kept are
        classified, and a block recorded, before the lock is released. A vanished tab is reopened once."""
        for attempt in range(2):
            try:
                with self.guard.request(budgeted=budgeted, kind=kind) as slot:
                    try:
                        result = self.browser.evaluate(self.tab, SNIPPETS[name], {**args, '__ack': self.memory.ack})
                    except ThreadsError as error:
                        if error.reason == 'tab_missing':
                            slot.cancel()  # the program never reached a page, so nothing went to Threads
                        raise
                    if not isinstance(result, dict):
                        raise ThreadsError(3, 'The Threads tab answered invalidly.', 'Run doctor.')
                    if result.get('stopped') or result.get('refused') or result.get('missing'):
                        slot.cancel()  # nothing was sent
                    else:
                        self._charge(slot, result)
                    if self.verbose:
                        diagnostic('request', label=label, count=self.guard.count, status=result.get('status'),
                                   source=(result.get('used') or {}).get('source'))
                    self._signals(result, slot)
                    if 429 in (result.get('statuses') or []):
                        self._stop(slot, classify.response({'status': 429, 'url': '', 'body': ''}, mode='graphql'))
                    if result.get('refused'):
                        raise ThreadsError(2, 'The browser refused a request this skill must not make: '
                                              + str(result['refused']) + '.', 'Report this as a skill bug.')
                    if result.get('network_error'):
                        raise ThreadsError(6, 'The request to Threads did not complete.', classify.RETRY_FIX,
                                           reason='network')
                    verdict = verdict_of(result)
                    if verdict.block:
                        self._stop(slot, verdict)
                    return result, verdict
            except ThreadsError as error:
                if error.reason != 'tab_missing' or attempt:
                    raise
            with self.memory.opening():
                self._open()
        raise AssertionError('unreachable')

    def _charge(self, slot, result):
        """Charge what the call sent and what the tab finished meanwhile; late requests use up a reservation first."""
        explicit, seen = _int(result.get('explicit'), 1), _int(result.get('resources'))
        extra = max(0, seen - explicit)
        for bucket in ('setup', 'budget'):
            used = min(extra, self.prepaid[bucket])
            self.prepaid[bucket] -= used
            extra -= used
        slot.charge(explicit + extra)

    def _allowed(self):
        names = {spec['name'] for spec in QUERIES.values() if spec['name']}
        return sorted(names | {self.memory.renamed(key) for key in QUERIES if self.memory.renamed(key)})

    def _spec(self, key):
        spec = dict(QUERIES[key])
        renamed = self.memory.renamed(key)
        if renamed:
            spec['name'], spec['doc_id'] = renamed, None
        return spec

    def query(self, key, variables, *, route=None):
        """The decoded payload of one read query; a refused one is learned again once (see the module docstring)."""
        spec = self._spec(key)
        for attempt in range(2):
            if not spec['name']:
                self._learn(key, spec, route)
                spec = self._spec(key)
                continue
            learned = self.memory.query(spec['name']) or {}
            args = {'name': spec['name'], 'allowed': self._allowed(), 'asbd_id': SNAPSHOT['asbd_id'],
                    'variables': {**spec['variables'], **variables}, 'endpoint': spec.get('endpoint'),
                    'root': spec.get('root'),
                    'fallback': {'doc_id': learned.get('doc_id') or spec.get('doc_id'), 'flags': learned.get('flags'),
                                 'providers': [[learn.provider_variable(m), m] for m in spec.get('providers') or []]}}
            result, verdict = self._request('query', args, lambda r: (
                classify.Verdict('failed', reason='rejected_query') if r.get('missing')
                else classify.response(r, mode='graphql')), key)
            used = result.get('used') or {}
            if verdict.kind == 'failed' and verdict.reason == 'rejected_query' and not attempt:
                if used.get('source') in ('live', 'live_id'):
                    self._reload()
                else:
                    self._learn(key, spec, route)
                spec = self._spec(key)
                continue
            if verdict.error:
                raise verdict.error
            if verdict.kind != 'ok':
                raise ThreadsError(6, f'Threads did not run {spec["name"]}.', classify.REJECTED_FIX, reason='stale')
            if used.get('source') in ('live', 'live_id') and isinstance(used.get('doc_id'), str):
                flags = learn.provider_values(used.get('flags') or {}) if used.get('flags') else None
                self.memory.learn(spec['name'], used['doc_id'], flags)
            return verdict.payload
        raise ThreadsError(6, f'Threads still refuses {spec["name"]} after learning its current id.',
                           'Tell the user the Threads reader needs an update.', reason='stale')

    def _recover(self, kind):
        if self.recovery[kind] >= (LEARN_LIMIT if kind == 'learn' else RELOAD_LIMIT):
            raise ThreadsError(6, 'This command already spent its recovery allowance on queries Threads refused.',
                               'Run the command again: what was learned is kept and it continues from there.',
                               reason='recovery_budget')
        self.recovery[kind] += 1

    def _reload(self):
        """The tab's own module was refused (the app in the tab is older than Threads): load it again, once."""
        self._recover('reload')
        with self.memory.opening():
            self._load(navigate=True)

    def _learn(self, key, spec, route):
        """Learn `key`'s current id from the screen that uses it: its preloaders, then its bundles, then a renamed
        successor found by argument names and root field. Raises when none is certain."""
        self._recover('learn')
        path = (spec.get('route') or '/').format(**(route or {}))
        html = self.page(path, budgeted=False, kind='recovery')
        found = learn.preloaders(html)
        flags = {}
        for entry in found.values():
            flags.update(learn.provider_values(entry['variables']))
        pattern = spec.get('learn_pattern')
        if not spec['name'] and pattern:
            names = [name for name in found if pattern in name and 'Mutation' not in name and name.endswith('Query')]
            if len(names) != 1:
                raise ThreadsError(6, f'The {path} screen does not name one query for this read.',
                                   'Tell the user the Threads reader needs an update.', reason='stale')
            self.memory.rename(key, names[0])
            self.memory.learn(names[0], found[names[0]]['doc_id'], learn.provider_values(found[names[0]]['variables']))
            return
        if spec['name'] in found:
            self.memory.learn(spec['name'], found[spec['name']]['doc_id'],
                              learn.provider_values(found[spec['name']]['variables']))
            return
        catalog = learn.search(html, [spec['name']])
        entry = catalog.get(spec['name'])
        if entry and entry.get('doc_id') and entry.get('kind') == 'query':
            wanted = {learn.provider_variable(m) for m in entry.get('providers') or []}
            self.memory.learn(spec['name'], entry['doc_id'], {k: v for k, v in flags.items() if k in wanted} or None)
            return
        if entry is None and spec.get('args') is not None:
            new = learn.successor({'args': spec['args'], 'root': spec.get('root')}, catalog, set(self._allowed()))
            if new:
                self.memory.rename(key, new)
                wanted = {learn.provider_variable(m) for m in catalog[new].get('providers') or []}
                self.memory.learn(new, catalog[new]['doc_id'], {k: v for k, v in flags.items() if k in wanted} or None)
                return
        raise ThreadsError(6, f'Threads no longer serves {spec["name"]} and no single successor was found.',
                           'Tell the user the Threads reader needs an update.', reason='stale')

    def page(self, path, *, budgeted=True, kind=None):
        """The HTML of one Threads document on the read surface, redirects followed by the rules (at most three)."""
        original, hop = path, 0
        while True:
            result, verdict = self._request('page', {'path': path}, lambda r: classify.response(
                {'status': r.get('status'), 'url': r.get('url'), 'body': r.get('body'),
                 'location': r.get('location_header')}, mode='page'), 'page', budgeted=budgeted, kind=kind)
            if verdict.error and verdict.kind != 'ok':
                raise verdict.error
            if 300 <= _int(result.get('status')) < 400 or result.get('status') == 0:
                hop += 1
                step = classify.redirect(original, result.get('location_header'), hop)
                if step.kind != 'follow':
                    raise step.error
                path = step.path
                continue
            return result.get('body') or ''

    def live_queries(self):
        """Which read queries the tab has loaded right now (doctor); makes no request."""
        with self.guard.observe() as slot:
            result = self.browser.evaluate(self.tab, SNIPPETS['modules'], {'names': self._allowed(),
                                                                           '__ack': self.memory.ack})
            if isinstance(result, dict):
                self._signals(result, slot)
        return (result or {}).get('live') or {}

    # --- reads, in the skill's terms ---------------------------------------------------------------------------

    def feed(self, variant, cursor):
        source = 'text_post_feed_following' if variant == 'following' else 'text_post_feed_threads'
        if cursor is None:
            payload = self.query('feed_first', {'variant': variant, 'data': {'pagination_source': source,
                                                                             'reason': 'cold_start_fetch'}})
        else:
            payload = self.query('feed_next', {'after': cursor, 'variant': variant, 'data': {
                'feed_view_info': '[]', 'pagination_source': source, 'reason': 'pagination', 'session_id': None}})
        return records.connection_page(payload['data'], 'feed')

    def post_page(self, target, *, sort, limit):
        """The post, its parents and its first reply batch: three requests, no screen move."""
        route = {'post_path': target.path}
        post_id = target.post_id
        responses = [self.query('post_target', {'postID': post_id}, route=route)['data'],
                     self.query('post_parents', {'postID': post_id}, route=route)['data'],
                     self.query('post_replies', {'postID': post_id, 'sortOrder': sort.upper()}, route=route)['data']]
        return records.post_page(responses, code=target.code, post_id=post_id, limit=limit)

    def replies(self, post_id, cursor, *, sort, path):
        """One further batch of a post's direct replies."""
        payload = self.query('replies_next', {'postID': post_id, 'after': cursor, 'sortOrder': sort.upper()},
                             route={'post_path': path})
        return payload['data']

    def profile_id(self, username):
        """The numeric id of a handle, and its user object (one request)."""
        payload = self.query('profile_by_name', {'username': username}, route={'username': username})
        user = (payload.get('data') or {}).get('xdt_text_app_user_by_username') or (payload.get('data') or {}).get('user')
        found = records.user_record(user) if isinstance(user, dict) else None
        if found is None:
            raise ThreadsError(9, f'Threads has no profile @{username} visible to this account.',
                               'Check the handle; tell the user rather than retrying.', reason='unavailable')
        return found['id'], user

    def profile_tab(self, tab, user_id, username, cursor):
        if tab == 'threads':
            key = 'profile_threads' if cursor is None else 'profile_threads_next'
            variables = {'userID': user_id, **({'after': cursor} if cursor else {})}
        else:
            key, variables = 'profile_' + tab, {'userID': user_id, **({'after': cursor} if cursor else {})}
        payload = self.query(key, variables, route={'username': username})
        return records.connection_page(payload['data'], 'profile_tab')

    def search_posts(self, text, *, recent, tag, cursor):
        variables = {'query': text, 'recent': 1 if recent else 0, 'search_surface': 'tags' if tag else 'default'}
        route = {'query': quote(text)}
        payload = (self.query('search_posts', variables, route=route) if cursor is None else
                   self.query('search_posts_next', {**variables, 'after': cursor}, route=route))
        return records.connection_page(payload['data'], 'search_posts')

    def search_accounts(self, text):
        payload = self.query('search_accounts', {'query': text}, route={'query': quote(text)})
        return records.connection_page(payload['data'], 'search_accounts')
