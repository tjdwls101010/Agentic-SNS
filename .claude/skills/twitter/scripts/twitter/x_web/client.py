"""The X web client: requests made from the skill's own x.com tab, the way the app makes them.

The tab is opened once on a quiet logged-in screen (an in-app page that does not exist, which still runs the whole app
and polls least) and reused. Each read is one GraphQL request sent from the tab with the app's own definition, feature
values, signature and headers, one request per browser call. Operations missing from the app's loaded modules are
loaded from their lazy chunk (static files) by hint; when that fails too, the last id this account's tab gave, then
the bundled snapshot, is tried. When X refuses a read, the client recovers once in a way that fits the refusal
(feature names it asked for, a fresh signature generator, a reload of a tab whose app is older than X's servers); a
read whose variables X no longer accepts needs a skill update and is never guessed at.

Request accounting: the skill's own requests are exact (one per query sent, one when a call may have sent one and its
answer was lost). What the page itself requests is what the tab's observer saw while the command ran, the skill's own
entries (told apart by their URL nonce) left out. Opening or reloading the tab is measured the same way when the kit
was installed before the app ran; when it was installed late, the opening is charged OPEN_RESERVE instead. Every
response the tab saw is checked for a block before the next request is sent.
"""
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from twitter.errors import TwitterError, diagnostic
from twitter.x_web import classify
from twitter.x_web.records import list_page, post_page, post_record

_SNIPPETS = Path(__file__).with_name('snippets')
_KIT = (_SNIPPETS / 'kit.js').read_text(encoding='utf-8').strip()


def _compose(path):
    body = path.read_text(encoding='utf-8')
    if path.stem == 'arm':  # it decides first whether there is a document to install the kit on
        return 'async (args) => {\n  const KIT = (' + _KIT + ');\n' + body + '}'
    return 'async (args) => {\n  const kit = (' + _KIT + ')(args);\n' + body + '}'


SNIPPETS = {path.stem: _compose(path) for path in _SNIPPETS.glob('*.js') if path.stem != 'kit'}
OPERATIONS = json.loads(Path(__file__).with_name('operations.json').read_text(encoding='utf-8'))['operations']
READ_OPERATIONS = sorted(OPERATIONS)
START = 'https://x.com/i/xskill'
# 성진: 관찰자가 앱보다 늦게 설치돼 열기를 잴 수 없을 때만 쓰는 예약값 — 실측(이른 설치) 열기는 x.com 13 + 문서 1
OPEN_RESERVE = 20
LOAD_WAIT = 20        # seconds a new tab may take until its app, store and login are there
RELOAD_LIMIT = 1      # tab reloads one command may spend recovering a refused read
_GONE = 'Run the command again; it opens a new tab.'


def snippet(name):
    """The page function the browser runs for `name` (state, arm, query, modules, close, blank)."""
    return SNIPPETS[name]


def _int(value, default=0):
    return value if type(value) is int and value >= 0 else default


def _host(url):
    try:
        return urlsplit(url or '').hostname or ''
    except ValueError:
        return ''


class Client:
    """One invocation's connection to X.

    browser: the Aside system (tabs, opener, load, evaluate). guard: account protection (request slots, the deadline).
    memory: the session store (the dedicated tab, the use token, acknowledged signals, learned operation ids).
    """

    def __init__(self, browser, guard, memory, verbose=False):
        self.browser, self.guard, self.memory, self.verbose = browser, guard, memory, verbose
        self.tab = None
        self.account_id = None
        self.language = None
        self.opened_now = False
        self.reopened = False
        self.session_reset = False
        self.unwatched = 0
        self.token = None
        self.measured_open = None   # True: the opening was measured; False: reserved
        self.reloads = 0
        self.provisional = {}       # operation → (query_id, features) used this command; saved once a read validates it
        self.nonce = {'sent': 0, 'matched': 0}

    # --- the tab ---------------------------------------------------------------------------------------------

    def _seconds(self):
        left = self.guard.time_left()
        if left <= 1:
            raise TwitterError(6, 'The command reached its time limit.', 'Run the command again (or its more: line); '
                                                                          'nothing is wrong with the account.',
                               reason='time_limit')
        return left

    def start(self):
        """Find, re-check and if needed open the dedicated tab under the session lock; returns the account id."""
        with self.memory.opening():
            self.memory.reload()
            self.session_reset = self.memory.reset
            known = self.memory.tab
            entry = next((t for t in self.browser.tabs(self._seconds()) if known and t['target_id'] == known), None)
            if entry and _host(entry['url']) == 'x.com':
                self.tab = known
                with self.guard.observe() as slot:
                    state = self._state()
                    self.unwatched = _int(state.get('resources'))
                    self.guard.log_unwatched(self.unwatched)  # made between commands: logged, not charged
                    self._note(state)
                    self._consume(state, slot)
                    self._check(state)
            else:
                # An emptied tab is not sent back to X: Aside closes an emptied tab once nothing holds it, even while
                # it loads, and a query would then open another one.
                self._open()
                self.reopened = bool(entry)
            self.token = self.memory.touch()
        return self.account_id

    def _args(self, args):
        return {**args, '__ack': self.memory.ack}

    def _state(self):
        state = self.browser.evaluate(self.tab, SNIPPETS['state'], self._args({}), self._seconds())
        if not isinstance(state, dict) or not isinstance(state.get('location'), str):
            raise TwitterError(3, 'The X tab answered invalidly.', 'Run doctor.')
        return state

    def _open(self):
        """Open a new dedicated tab: about:blank first (recorded before it can poll), attached, its opener ended, then
        sent to x.com with the kit installed as the load begins. Counted outside the budget."""
        with self.guard.request(reserve=1, budgeted=False, kind='tab_open') as slot:
            with self.browser.opener(self._seconds()) as target:
                self.tab = target
                self.memory.set_tab(target)
                armed = self.browser.load(target, START, SNIPPETS['arm'], self._args({}), self._seconds())
            if not any(t['target_id'] == target for t in self.browser.tabs(self._seconds())):
                raise TwitterError(3, 'Aside closed the new X tab when the session that opened it ended; Aside\'s '
                                      'behaviour has changed and the skill needs an update.',
                                   'Tell the user the X reader needs an update; retrying opens a tab each time.',
                                   reason='aside_changed')
            self.opened_now = True
            self._settle_load(slot, armed)

    def _reload(self):
        """Load the app in the known tab again (its app is older than X's servers): measured like opening, outside the
        budget, at most RELOAD_LIMIT a command."""
        if self.reloads >= RELOAD_LIMIT:
            raise TwitterError(6, 'This command already reloaded the X tab once to recover a refused read.',
                               'Run the command again; if it keeps failing, the skill needs an update.',
                               reason='recovery_budget')
        self.reloads += 1
        with self.memory.opening(), self.guard.request(reserve=1, budgeted=False, kind='tab_reload') as slot:
            armed = self.browser.load(self.tab, START, SNIPPETS['arm'], self._args({}), self._seconds())
            self.reopened = True
            self._settle_load(slot, armed)

    def _settle_load(self, slot, armed):
        """Wait for the loaded app, its store and login, checking each look for a block; charge what the load cost:
        what the tab's observer saw plus the document, or OPEN_RESERVE when the kit came too late to see it all."""
        # measured when the kit came before the app ran, or while X's timing buffer still held the whole load
        early = isinstance(armed, dict) and (armed.get('buffer_intact') is True or
                                             (armed.get('ready_at_install') == 'loading' and not armed.get('app_at_install')))
        deadline = time.monotonic() + min(LOAD_WAIT, max(1.0, self._seconds() - 5))
        seen, state, sessionless = 1, None, 0   # the document itself is a request too
        while True:
            try:
                look = self._state()
            except TwitterError as error:
                if error.reason == 'tab_missing' or time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
                continue
            seen += _int(look.get('resources'))
            self._note(look)
            self._consume(look, slot)
            if look.get('app') and look.get('store') and look.get('user_id'):
                state = look
                break
            if look.get('app') and look.get('store') and not look.get('user_id'):
                sessionless += 1
                if sessionless >= 2:
                    state = look  # the app has loaded its store without a session: logged out
                    break
            if time.monotonic() > deadline:
                state = look
                break
            time.sleep(0.5)
        self.measured_open = early
        slot.charge(seen if early else max(OPEN_RESERVE, seen))
        self._check(state)

    def _check(self, state):
        """Raise for a page that is not a working, logged-in x.com page of this command's account (blocks and login
        pages were already handled by _consume)."""
        if _host(state.get('location')) != 'x.com' or not state.get('app') or not state.get('store'):
            raise TwitterError(3, 'The X tab is not a working x.com page.', 'Run doctor; close the tab if it keeps '
                                                                             'failing.')
        if not state.get('user_id') or not state.get('ct0'):
            raise TwitterError(4, 'X login is required in the Aside browser.', classify.LOGIN_FIX, reason='login')
        if self.account_id is not None and state['user_id'] != self.account_id:
            raise TwitterError(4, 'The Aside browser is now logged in to a different X account than when this command '
                                  'started.', 'Check which account Aside is logged in to, then rerun.',
                               reason='account_changed')
        self.account_id = state['user_id']
        self.language = state.get('language')

    def _note(self, report):
        """Remember whether the skill's own requests were told apart by their nonce (doctor reports it)."""
        if isinstance(report, dict):
            self.nonce['matched'] += _int(report.get('ours'))

    def _consume(self, report, slot):
        """Judge everything one browser call reported. A lock or challenge is recorded and the tab emptied before the
        signals are acknowledged; a login is raised; another operation's limit is recorded for its bucket and the
        command goes on. The tab drops the signals only once protection holds them."""
        if not isinstance(report, dict):
            return
        signals = [s for s in report.get('signals') or [] if isinstance(s, dict)]
        verdicts = []
        for kept in signals:
            verdict = classify.signal(kept)
            if verdict.kind == 'rate_limited':
                rate = kept.get('rate') if isinstance(kept.get('rate'), dict) else None
                slot.record_bucket(verdict.bucket, 429 if kept.get('status') == 429 else 200, rate)
            verdicts.append(verdict)
        if isinstance(report.get('moved'), str):
            verdicts.append(classify.signal({'moved': report['moved']}))
        strongest = classify.strongest(verdicts)
        moments = [s['at'] for s in signals if type(s.get('at')) in (int, float)]
        if strongest is not None and strongest.block:
            self._stop(slot, strongest, moments)
        if moments:
            self.memory.acknowledge(max(moments))
        if strongest is not None:
            raise strongest.error

    def _stop(self, slot, verdict, moments=()):
        """Record a block, empty the tab so the app stops polling (even if the block could not be saved), acknowledge
        the signals it came from, then raise."""
        try:
            slot.block(verdict.block, self.account_id)
        finally:
            if not self._empty():
                self.memory.set_dirty(True)  # the idle cleanup keeps trying; the tab must not keep polling
        if moments:
            self.memory.acknowledge(max(moments))
        raise TwitterError(verdict.error.code, verdict.error.message, verdict.error.fix, reason=verdict.error.reason,
                           account_id=self.account_id)

    def _gone(self):
        tab = next((t for t in self.browser.tabs(max(5.0, self.guard.time_left())) if t['target_id'] == self.tab), None)
        return tab is None or not _host(tab['url'])

    def _empty(self):
        """Close the tab, or empty it to about:blank when it stays; makes no request. True once nothing polls."""
        for name in ('close', 'blank', 'blank'):
            try:
                self.browser.evaluate(self.tab, SNIPPETS[name], self._args({}), max(5.0, self.guard.time_left()))
            except TwitterError as error:
                if error.reason == 'tab_missing':
                    return True
            for _ in range(6):
                try:
                    if self._gone():
                        return True
                except TwitterError:
                    break
                time.sleep(0.3)
        return False

    def release_tab(self):
        """The idle cleanup: take in what the tab saw, then close or empty it; allowed while a block stands."""
        if not self.tab:
            return False
        with self.guard.observe(allow_blocked=True) as slot:
            try:
                report = self.browser.evaluate(self.tab, SNIPPETS['state'], self._args({}), 30)
            except TwitterError as error:
                if error.reason == 'tab_missing':
                    return True
                report = None
            if isinstance(report, dict):
                self.guard.log_unwatched(_int(report.get('resources')))
                try:
                    self._consume(report, slot)
                except TwitterError:
                    pass  # recorded; the tab is being emptied anyway
            emptied = self._empty()
            self.memory.set_dirty(not emptied)
            return emptied

    # --- requests --------------------------------------------------------------------------------------------

    def _call(self, name, args, operation, judge=None):
        """One guarded browser call that may send `operation`: block, limit, budget and pacing first; the answer and
        every signal the tab kept are judged — and a block or bucket recorded — before the lock is released (judge(result)
        gives the verdict on the answer itself). A vanished tab is reopened once (outside this request's charge)."""
        for attempt in range(2):
            try:
                with self.guard.request(operation=operation) as slot:
                    try:
                        result = self.browser.evaluate(self.tab, SNIPPETS[name], self._args(args), self._seconds())
                    except TwitterError as error:
                        if error.reason == 'tab_missing':
                            slot.cancel()  # the program never reached a page, so nothing went to X
                        raise  # any other loss may have sent the request: the slot stays charged at 1
                    if not isinstance(result, dict):
                        raise TwitterError(3, 'The X tab answered invalidly.', 'Run doctor.')
                    sent = bool(result.get('explicit'))
                    if not sent:
                        slot.cancel()  # refused, missing or stopped in the page: nothing was sent
                    slot.charge(int(sent) + _int(result.get('resources')))
                    if sent:
                        self.nonce['sent'] += 1
                    self._note(result)
                    if self.verbose:
                        diagnostic('request', operation=operation, count=self.guard.count, status=result.get('status'),
                                   source=(result.get('used') or {}).get('source'))
                    self._consume(result, slot)
                    if result.get('stopped') == 'limit':
                        raise self._limit(operation)
                    if result.get('stopped'):
                        raise TwitterError(6, 'The tab held signals this skill could not clear, so nothing was sent.',
                                           'Run doctor; close the tab if it keeps happening.', reason='stuck')
                    if result.get('refused'):
                        raise TwitterError(2, 'The browser refused a request this skill must not make: '
                                              + str(result['refused']) + '.', 'Report this as a skill bug.')
                    if result.get('login'):
                        raise TwitterError(4, 'X login is required in the Aside browser.', classify.LOGIN_FIX,
                                           reason='login')
                    if result.get('missing'):
                        raise TwitterError(6, 'The X tab lacks ' + str(result['missing']) + ', so nothing was sent.',
                                           'Run the command again; if it keeps failing, the skill needs an update.',
                                           reason='missing')
                    if result.get('network_error'):
                        raise TwitterError(6, 'The request to X did not complete.', classify.RETRY_FIX, reason='network')
                    slot.observe(result.get('status'), result.get('headers'))
                    verdict = judge(result) if judge else None
                    if verdict is not None and verdict.block:
                        self._stop(slot, verdict)
                    return result, verdict
            except TwitterError as error:
                if error.reason != 'tab_missing' or attempt:
                    raise
                with self.memory.opening():
                    self._open()
        raise TwitterError(6, 'The X tab could not be used.', _GONE)

    def _limit(self, operation, message=None):
        reset = (self.guard.state()['buckets'].get(operation) or {}).get('reset')
        return TwitterError(10, message or f'X\'s limit for {operation} is used up for now.', 'This is not an account problem and '
                            'other commands still work; retry this one after its reset.', reason='rate_limited',
                            operation=operation, reset=reset, next_allowed_at=reset)

    def _fallback(self, operation):
        learned = self.memory.query(operation) or {}
        spec = OPERATIONS[operation]
        return {'query_id': learned.get('doc_id') or spec.get('query_id'), 'features': learned.get('flags') or []}

    def query(self, operation, variables, *, missing=None):
        """The data at `operation`'s root for `variables` (the snapshot's own variables underneath); a refused read is
        recovered once in the way its refusal allows (see the module docstring)."""
        spec = OPERATIONS[operation]
        args = {'name': operation, 'allowed': READ_OPERATIONS, 'variables': {**spec['variables'], **variables},
                'toggles': spec.get('field_toggles') or {}, 'chunk_hint': spec.get('chunk_hint'),
                'fallback': self._fallback(operation)}
        retried = set()
        while True:
            result, verdict = self._call('query', args, operation,
                                         lambda r: classify.response(r, operation, spec['root']))
            if verdict.kind == 'ok':
                used = result.get('used') or {}
                if used.get('source') in ('live', 'chunk') and isinstance(used.get('query_id'), str):
                    self.provisional[operation] = (used['query_id'], used.get('features') or [])
                return verdict.root, verdict.warnings
            if verdict.kind == 'unavailable' and missing is not None:
                raise missing
            if verdict.kind == 'rate_limited':
                raise self._limit(operation, verdict.error.message)
            if verdict.kind == 'features_missing' and 'features' not in retried:
                retried.add('features')
                args = {**args, 'extra_features': verdict.names}
                continue
            if verdict.kind == 'csrf' and 'csrf' not in retried:
                retried.add('csrf')  # the next call reads ct0 again from the tab
                continue
            if verdict.kind == 'signature_rejected' and 'signature' not in retried:
                retried.add('signature')
                args = {**args, 'fresh_generator': True}
                continue
            if verdict.kind in ('signature_rejected', 'rotated') and 'reload' not in retried and \
                    (result.get('used') or {}).get('source') in ('live', 'chunk'):
                retried.add('reload')
                self._reload()  # the tab's app is older than X's servers
                continue
            if verdict.kind == 'rotated':
                raise TwitterError(6, f'X no longer runs {operation} as this skill sends it.',
                                   'Tell the user the X reader needs an update; other commands may work.', reason='stale')
            raise verdict.error

    def confirm(self):
        """The read was turned into records: remember the operation ids the live tab gave, for when it cannot."""
        for operation, (query_id, features) in self.provisional.items():
            self.memory.learn(operation, query_id, features)
        self.provisional = {}

    def live_operations(self):
        """Which of the skill's operations the tab's app defines now, lazy chunks loaded by hint; makes no x.com
        request."""
        hints = sorted({spec['chunk_hint'] for spec in OPERATIONS.values() if spec.get('chunk_hint')})
        with self.guard.observe() as slot:
            result = self.browser.evaluate(self.tab, SNIPPETS['modules'], self._args({'names': READ_OPERATIONS,
                                                                                       'hints': hints}), self._seconds())
            if isinstance(result, dict):
                slot.charge(_int(result.get('resources')))  # the page's own requests while this command ran
            self._consume(result, slot)
        return result if isinstance(result, dict) else {}

    def viewer(self):
        """The logged-in account as X answers it (one Viewer read)."""
        root, _ = self.query('Viewer', {})
        return root

    # --- reads, in the skill's terms ---------------------------------------------------------------------------

    def timeline(self, operation, variables, cursor=None):
        """One page of a timeline surface as records (see records.list_page)."""
        root, warnings = self.query(operation, {**variables, **({'cursor': cursor} if cursor else {})})
        page = list_page(root)
        page.warnings = warnings
        self.confirm()
        return page

    def feed(self, variant, cursor):
        """One page of the home feed: for you (HomeTimeline) or following (HomeLatestTimeline)."""
        return self.timeline('HomeLatestTimeline' if variant == 'following' else 'HomeTimeline', {}, cursor)

    def post_page(self, post_id, *, sort, cursor=None):
        """A post read: the post, its parents and a batch of its replies (first page), or a further batch by cursor —
        the next direct replies, or the replies X hid (one request)."""
        gone = TwitterError(9, 'This post is unavailable: deleted, withheld, protected or not visible to this account.',
                            'Tell the user; retrying will not change it.', reason='unavailable')
        variables = {'focalTweetId': post_id, 'rankingMode': 'Recency' if sort == 'recent' else 'Relevance'}
        if cursor:
            variables['cursor'] = cursor
        root, warnings = self.query('TweetDetail', variables, missing=gone)
        page = post_page(root, post_id, continuing=bool(cursor))
        self.confirm()
        return page

    def posts(self, ids):
        """Several posts by id in one request, without replies; ids X did not return are unresolved."""
        root, warnings = self.query('TweetResultsByRestIds', {'tweetIds': list(ids)})
        records = []
        for node in root if isinstance(root, list) else []:
            record = post_record(node) if isinstance(node, dict) else None
            if record is not None and not record.get('unavailable'):
                records.append(record)
        self.confirm()
        return records
