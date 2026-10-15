"""The Facebook web client: requests made from the skill's own facebook.com tab, the way the page makes them.

The tab is opened once (`aside <url>`) and reused; each read is one GraphQL request sent with the page's own request
parameters. Query ids and provider flags come from the page's loaded modules when it has them, else from what an
earlier read learned, else from the bundled snapshot. When Facebook no longer accepts a stored query, the tab is moved
to the screen that loads that query (as a person would open it) and the read is retried once with the live id.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

from facebook.errors import FacebookError, diagnostic
from facebook.graphql import classify

HOME = 'https://www.facebook.com/'
SNIPPETS = {path.stem: path.read_text(encoding='utf-8')
            for path in (Path(__file__).parent / 'snippets').glob('*.js')}
SNAPSHOT = json.loads((Path(__file__).with_name('queries.json')).read_text(encoding='utf-8'))
QUERIES = SNAPSHOT['queries']
READ_NAMES = sorted(spec['name'] for spec in QUERIES.values())


class Client:
    """One invocation's connection to Facebook.

    browser: the Aside system (tabs, open, evaluate). guard: account protection (request slots). memory: the
    session store (the dedicated tab, learned query ids).
    """

    def __init__(self, browser, guard, memory, verbose=False):
        self.browser, self.guard, self.memory, self.verbose = browser, guard, memory, verbose
        self.tab = None
        self.account_id = None
        self.opened_now = False

    # --- the tab ---------------------------------------------------------------------------------------------

    def start(self):
        """Find or open the dedicated tab and check it is a logged-in Facebook page; returns the account id."""
        known = self.memory.tab
        if known and any(t['target_id'] == known and _usable(t['url']) for t in self.browser.tabs()):
            self.tab = known
            self._check_state(self._state())
        else:
            self._check_state(self._open(), recorded=True)
        return self.account_id

    def _state(self):
        state = self.browser.evaluate(self.tab, SNIPPETS['state'], {})
        if not isinstance(state, dict) or not isinstance(state.get('location'), str):
            raise FacebookError(3, 'The Facebook tab answered invalidly.', 'Run doctor.')
        return state

    def _open(self):
        """Open a new dedicated tab: counted as requests (its document and what the page loads), outside the budget."""
        before = {t['target_id'] for t in self.browser.tabs()}
        with self.guard.request(budgeted=False) as slot:
            self.browser.open(HOME)
            new = [t for t in self.browser.tabs() if t['target_id'] not in before and _facebook(t['url'])]
            if not new:
                raise FacebookError(3, 'Aside did not open the Facebook tab.', 'Check Aside, then run doctor.')
            self.tab = new[-1]['target_id']
            self.memory.set_tab(self.tab)
            self.opened_now = True
            state = self._state()
            slot.charge(1 + _int(state.get('resources')))
            verdict = classify.location(state['location'], state.get('user_id'))
            if verdict.block:
                slot.block(verdict.block)
        return state

    def _check_state(self, state, recorded=False):
        verdict = classify.location(state['location'], state.get('user_id'))
        if verdict.block and not recorded:
            self.guard.block(verdict.block)
        if verdict.error:
            raise verdict.error
        if not state.get('runtime'):
            raise FacebookError(3, 'The Facebook tab is not a working Facebook page.', 'Run doctor; close the tab if '
                                                                                         'it keeps failing.')
        self.account_id = state['user_id']

    def _evaluate(self, snippet, args):
        """Run a page function in the tab; a tab that vanished is reopened once."""
        try:
            return self.browser.evaluate(self.tab, SNIPPETS[snippet], args)
        except FacebookError as error:
            if error.reason != 'tab_missing':
                raise
        self._check_state(self._open(), recorded=True)
        return self.browser.evaluate(self.tab, SNIPPETS[snippet], args)

    # --- requests --------------------------------------------------------------------------------------------

    def _request(self, snippet, args, verdict_of, label):
        """One guarded request: block check, budget and pacing; the response classified before the lock is released."""
        for attempt in range(2):
            try:
                with self.guard.request() as slot:
                    result = self.browser.evaluate(self.tab, SNIPPETS[snippet], args)
                    if not isinstance(result, dict):
                        raise FacebookError(3, 'The Facebook tab answered invalidly.', 'Run doctor.')
                    slot.charge(max(_int(result.get('explicit'), 1), _int(result.get('resources'))))
                    if self.verbose:
                        diagnostic('request', snippet=snippet, label=label, count=self.guard.count,
                                   status=result.get('status'), source=(result.get('used') or {}).get('source'))
                    if result.get('refused'):
                        raise FacebookError(2, 'The browser refused a request this skill must not make.',
                                            'Report this as a skill bug.')
                    if result.get('network_error'):
                        raise FacebookError(6, 'The request to Facebook did not complete.', 'Retry later; run doctor '
                                                                                            'if it keeps failing.')
                    verdict = verdict_of(result)
                    if verdict.block:
                        slot.block(verdict.block)
                    return result, verdict
            except FacebookError as error:
                if error.reason != 'tab_missing' or attempt:
                    raise
            self._check_state(self._open(), recorded=True)
        raise AssertionError('unreachable')

    def query(self, key, variables, *, route, retried=False):
        """The decoded chunks of one read query; stale stored ids are healed by visiting `route` once."""
        spec = QUERIES[key]
        learned = self.memory.query(spec['name'])
        fallback = {'doc_id': (learned or {}).get('doc_id') or spec['doc_id'],
                    'flags': (learned or {}).get('flags') or SNAPSHOT['relay_provider_flags']}
        args = {'name': spec['name'], 'variables': {**spec['variables'], **variables}, 'fallback': fallback}
        result, verdict = self._request('query', args, lambda r: classify.Verdict('stale', error=FacebookError(
            6, f'No id for {spec["name"]} is known.', classify.STALE_FIX, reason='stale')) if r.get('missing')
            else classify.response(r, mode='graphql', expected=(spec['expected_key'], spec['kind']), retried=retried), key)
        used = result.get('used') or {}
        if verdict.kind == 'retry':
            return self.query(key, variables, route=route, retried=True)
        if verdict.kind == 'stale' and used.get('source') in ('stored', 'none') and route:
            self._route(route, spec['name'])
            return self.query(key, variables, route=None, retried=retried)
        if verdict.error:
            raise verdict.error
        if used.get('source') in ('live', 'live_id') and isinstance(used.get('doc_id'), str):
            self.memory.learn(spec['name'], used['doc_id'], used.get('flags'))
        return verdict.chunks if verdict.kind == 'ok' else []

    def page(self, url):
        """The HTML of one facebook.com page (to find an id the queries need)."""
        result, verdict = self._request('page', {'url': url},
                                        lambda r: classify.response(r, mode='html'), 'page')
        if verdict.error:
            raise verdict.error
        return result['body']

    def _route(self, url, name):
        """Move the tab to the screen that loads `name` (as a person would open it), so its live id is used next."""
        path = urlsplit(url)
        relative = (path.path or '/') + (('?' + path.query) if path.query else '')
        result, verdict = self._request('route', {'path': relative, 'names': [name]},
                                        lambda r: classify.location(r.get('location'), r.get('user_id')), 'route')
        if verdict.error:
            raise verdict.error
        live = (result.get('live') or {}).get(name)
        if not live:
            raise FacebookError(6, f'Facebook no longer accepts the stored {name} and the page did not provide a '
                                   'current one.', classify.STALE_FIX, reason='stale')
        self.memory.learn(name, live['doc_id'], live.get('flags'))

    def live_queries(self):
        """Which read queries the tab has loaded right now (doctor); makes no request."""
        result = self._evaluate('modules', {'names': READ_NAMES})
        return result if isinstance(result, dict) else {}


def _facebook(url):
    try:
        host = urlsplit(url).hostname or ''
    except ValueError:
        return False
    return host == 'facebook.com' or host.endswith('.facebook.com')


def _usable(url):
    """The dedicated tab must still be on www.facebook.com: requests are sent relative to its origin."""
    try:
        return urlsplit(url).hostname == 'www.facebook.com'
    except ValueError:
        return False


def _int(value, default=0):
    return value if type(value) is int and value >= 0 else default
