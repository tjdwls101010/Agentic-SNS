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
from twitter.x_web.records import (account_record, community_record, list_page, list_record, missing_community,
                                   missing_list, missing_space, post_page, post_record, space_record)

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
# 성진: 앱이 처음 답한 뒤에도 로드 꼬리가 이어진다(라이브: 10건) — 새것 없는 look 2번 연속이나 이 초까지 기다려 열기에 넣는다.
# 꼬리가 더 길게 이어지는 게 보이면(첫 읽기의 배경 요청이 계속 크면) 늘린다
QUIET_LOOKS, QUIET_WAIT = 2, 4.0
_GONE = 'Run the command again; it opens a new tab.'


def snippet(name):
    """The page function the browser runs for `name` (state, arm, query, modules, close, blank)."""
    return SNIPPETS[name]


def _int(value, default=0):
    return value if type(value) is int and value >= 0 else default


def _changed(operation):
    return TwitterError(6, f'X\'s answer to {operation} is not where or what this skill expects.', classify.UPDATE_FIX,
                        reason='shape_changed')


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
            entry = self._entry(known)
            try:
                if entry and _host(entry['url']) == 'x.com':
                    self.tab = known
                    self._take_over(between=True)
                else:
                    # An emptied tab is not sent back to X: Aside closes an emptied tab once nothing holds it, even
                    # while it loads, and a query would then open another one.
                    self._open()
                    self.reopened = bool(entry)
            finally:
                if self.tab:  # a tab that failed to open still polls: the idle cleanup must know of it
                    self.token = self.memory.touch()
        return self.account_id

    def _entry(self, target):
        return next((t for t in self._aside(self.browser.tabs, self._seconds()) if target and t['target_id'] == target),
                    None)

    def _take_over(self, between=False):
        """Look at the recorded tab before using it (a block or login it shows is judged). between: what the page
        requested since the last command is this command's to report (logged as unwatched, not charged) — before any
        verdict, so a block does not hide it."""
        with self.guard.observe() as slot:
            state = self._state()
            if between:
                self.unwatched = _int(state.get('resources'))
                self.guard.log_unwatched(self.unwatched)
            self._note(state)
            self._consume(state, slot)
            self._check(state)

    def _reopen(self):
        """The tab vanished mid-command: use the one another command opened meanwhile, else open one (once)."""
        with self.memory.opening():
            self.memory.reload()
            known = self.memory.tab
            entry = self._entry(known) if known != self.tab else None
            if entry and _host(entry['url']) == 'x.com':
                self.tab = known
                self._take_over()  # what it requested was the other command's to count
            else:
                self._open()

    def _aside(self, method, *args):
        """A browser call; one cut short by the command's own deadline is the time limit, not an Aside failure."""
        try:
            return method(*args)
        except TwitterError as error:
            if error.reason == 'timeout' and self.guard.time_left() <= 1:
                raise TwitterError(6, 'The command reached its time limit during a browser call; its request may have '
                                      'been made.', 'Run the command again (or its more: line); nothing is wrong with '
                                                    'the account. If it keeps happening, run doctor to check Aside.',
                                   reason='time_limit') from None
            raise

    def _args(self, args):
        return {**args, '__ack': self.memory.ack}

    def _state(self):
        state = self._aside(self.browser.evaluate, self.tab, SNIPPETS['state'], self._args({}), self._seconds())
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
                armed = self._load(slot, target)
            try:
                listed = self._aside(self.browser.tabs, self._seconds())
            except TwitterError:
                slot.charge(OPEN_RESERVE)  # the tab loaded x.com, unmeasured
                raise
            if not any(t['target_id'] == target for t in listed):
                slot.charge(OPEN_RESERVE)  # it loaded x.com before Aside closed it, unseen
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
            armed = self._load(slot, self.tab)
            self.reopened = True
            self._settle_load(slot, armed)

    def _load(self, slot, target):
        """Send the tab to x.com with the kit armed; a load that fails once the tab was sent is charged the reserve."""
        try:
            return self._aside(self.browser.load, target, START, SNIPPETS['arm'], self._args({}), self._seconds())
        except TwitterError as error:
            if error.reason != 'tab_missing':
                slot.charge(OPEN_RESERVE)
            raise

    def _settle_load(self, slot, armed):
        """Wait for the loaded app, its store and login, checking each look for a block; charge what the load cost:
        what the tab's observer saw plus the document, or, when the kit came too late to see it all, OPEN_RESERVE for
        what came before it plus everything it saw (never set off against each other). Charged however the wait ends."""
        # measured when the kit came before the app ran, or while X's timing buffer still held the whole load
        early = isinstance(armed, dict) and (armed.get('buffer_intact') is True or
                                             (armed.get('ready_at_install') == 'loading' and not armed.get('app_at_install')))
        deadline = time.monotonic() + min(LOAD_WAIT, max(1.0, self._seconds() - 5))
        seen = [1]   # the document itself is a request too; counted up as the looks come in, charged however they end
        try:
            state = self._wait_for_app(slot, deadline, seen)
        finally:
            self.measured_open = early
            slot.charge(seen[0] if early else OPEN_RESERVE + seen[0] - 1)
        self._check(state)

    def _wait_for_app(self, slot, deadline, seen):
        """Look at the loading tab until its app, store and login are there (or it is logged out, or time is up), then
        until the load has settled (QUIET_LOOKS looks in a row see nothing new, at most QUIET_WAIT seconds), so the
        load's tail is part of the opening rather than of the first read."""
        sessionless, ready, quiet, settle_by = 0, None, 0, None
        while True:
            try:
                look = self._state()
            except TwitterError as error:
                if error.reason == 'tab_missing' or time.monotonic() > deadline:
                    raise
                time.sleep(0.5)
                continue
            seen[0] += _int(look.get('resources'))
            self._note(look)
            self._consume(look, slot)
            if ready is not None:
                quiet = quiet + 1 if not _int(look.get('resources')) else 0
                if quiet >= QUIET_LOOKS or time.monotonic() > settle_by or time.monotonic() > deadline:
                    return look
                time.sleep(0.5)
                continue
            if look.get('app') and look.get('store') and look.get('user_id'):
                ready, settle_by = look, time.monotonic() + QUIET_WAIT
                time.sleep(0.5)
                continue
            if look.get('app') and look.get('store') and not look.get('user_id'):
                sessionless += 1
                if sessionless >= 2:
                    return look  # the app has loaded its store without a session: logged out
            if time.monotonic() > deadline:
                return look
            time.sleep(0.5)

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
        verdicts, unrecorded = [], None
        for kept in signals:
            verdict = classify.signal(kept)
            if verdict.kind == 'rate_limited':
                rate = kept.get('rate') if isinstance(kept.get('rate'), dict) else None
                try:
                    slot.record_bucket(verdict.bucket, 429 if kept.get('status') == 429 else 200, rate)
                except TwitterError as error:
                    unrecorded = unrecorded or error  # a block among the signals is still recorded first
            verdicts.append(verdict)
        if isinstance(report.get('moved'), str):
            verdicts.append(classify.signal({'moved': report['moved']}))
        strongest = classify.strongest(verdicts)
        moments = [s['at'] for s in signals if type(s.get('at')) in (int, float)]
        if strongest is not None and strongest.block:
            self._stop(slot, strongest, moments, report.get('user_id'))
        if unrecorded is not None:
            raise unrecorded  # not acknowledged: protection does not hold what the signals said
        if moments:
            self.memory.acknowledge(max(moments))
        if strongest is not None:
            raise strongest.error

    def _stop(self, slot, verdict, moments=(), account_id=None):
        """Record a block for the account the tab showed (else this command's), empty the tab so the app stops polling
        (even if the block could not be saved), acknowledge the signals it came from, then raise."""
        account_id = account_id if isinstance(account_id, str) and account_id else self.account_id
        try:
            slot.block(verdict.block, account_id)
        finally:
            if not self._empty():
                self.memory.set_dirty(True)  # the idle cleanup keeps trying; the tab must not keep polling
        if moments:
            self.memory.acknowledge(max(moments))
        raise TwitterError(verdict.error.code, verdict.error.message, verdict.error.fix, reason=verdict.error.reason,
                           account_id=account_id)

    def _gone(self):
        tab = next((t for t in self._aside(self.browser.tabs, max(5.0, self.guard.time_left()))
                    if t['target_id'] == self.tab), None)
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
                        result = self._aside(self.browser.evaluate, self.tab, SNIPPETS[name], self._args(args),
                                             self._seconds())
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
                    unrecorded = None
                    if sent:  # its own limit is recorded before any signal can stop the command
                        try:
                            slot.observe(result.get('status'), result.get('headers'))
                        except TwitterError as error:
                            unrecorded = error  # raised once the signals are judged: a lock must still empty the tab
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
                    verdict = judge(result) if judge else None
                    if verdict is not None and verdict.block:
                        self._stop(slot, verdict)
                    if unrecorded is not None:
                        raise unrecorded
                    return result, verdict
            except TwitterError as error:
                if error.reason != 'tab_missing' or attempt or self.guard.checking:
                    raise
                self._reopen()
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
            if self.guard.checking:
                raise verdict.error  # the unblock check is one request: its answer decides, nothing is retried
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
            result = self._aside(self.browser.evaluate, self.tab, SNIPPETS['modules'],
                                 self._args({'names': READ_OPERATIONS, 'hints': hints}), self._seconds())
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
        """Several posts by id in one request, without replies: (records, how many returned could not be read); ids X
        did not return are unresolved."""
        root, warnings = self.query('TweetResultsByRestIds', {'tweetIds': list(ids)})
        records, unreadable = [], 0
        for node in root if isinstance(root, list) else []:
            record = post_record(node) if isinstance(node, dict) else None
            if record is None:
                unreadable += 1
            elif not record.get('unavailable'):
                records.append(record)
        if unreadable and not records:
            raise _changed('TweetResultsByRestIds')
        self.confirm()
        return records, unreadable

    def user(self, handle):
        """The account behind a handle as a record (one request); a handle X does not know, or a suspended account, is
        unavailable."""
        gone = TwitterError(9, f'X has no account @{handle} visible to this account (suspended, deactivated or never '
                               'existed).', 'Check the handle; tell the user rather than retrying.', reason='unavailable')
        root, warnings = self.query('UserByScreenName', {'screen_name': handle}, missing=gone)
        record = account_record(root)
        if record.get('unavailable') or not record.get('id'):
            raise gone
        self.confirm()
        return record

    def users(self, handles):
        """Several accounts by handle in one request; handles X did not return are unresolved."""
        root, warnings = self.query('UsersByScreenNames', {'screen_names': list(handles)})
        records = [account_record(node) for node in (root if isinstance(root, list) else []) if isinstance(node, dict)]
        self.confirm()
        return [r for r in records if not r.get('unavailable') and r.get('id')]

    def x_list(self, list_id):
        """One list's card (one request); a list X does not return to this account is unavailable."""
        gone = TwitterError(9, 'This list is unavailable: deleted, private or never existed.',
                            'Check the list id; tell the user rather than retrying.', reason='unavailable')
        root, warnings = self.query('ListByRestId', {'listId': list_id}, missing=gone)
        record = list_record(root)
        if record is None:
            raise gone if missing_list(root) else _changed('ListByRestId')
        self.confirm()
        return record

    def community(self, community_id):
        """One community's card (one request); a community X does not return to this account is unavailable."""
        gone = TwitterError(9, 'This community is unavailable: deleted, suspended or never existed.',
                            'Check the community id; tell the user rather than retrying.', reason='unavailable')
        root, warnings = self.query('CommunityByRestId', {'communityId': community_id}, missing=gone)
        record = community_record(root)
        if record is None:
            raise gone if missing_community(root) else _changed('CommunityByRestId')
        self.confirm()
        return record

    def space(self, space_id):
        """One space's card (one request); a space X does not return is unavailable."""
        gone = TwitterError(9, 'This space is unavailable: it never existed or X no longer keeps it.',
                            'Check the link; tell the user rather than retrying.', reason='unavailable')
        root, warnings = self.query('AudioSpaceById', {'id': space_id}, missing=gone)
        record = space_record(root)
        if record is None:
            raise gone if missing_space(root) else _changed('AudioSpaceById')
        self.confirm()
        return record

    def community_search(self, text, cursor):
        """One page of X's search across communities' posts for `text` (operators as typed)."""
        return self.timeline('GlobalCommunitiesLatestPostSearchTimeline', {'rawQuery': text}, cursor)

    def explore(self):
        """X's Explore tabs (one request): {tab id: timeline id}, the default tab's id and its first page."""
        root, warnings = self.query('ExplorePage', {})
        initial = root.get('initialTimeline') if isinstance(root, dict) else None
        tabs = {t.get('id'): (t.get('timeline') or {}).get('id') for t in (root.get('timelines') or [])
                if isinstance(t, dict)} if isinstance(root, dict) else {}
        if not isinstance(initial, dict) or not tabs:
            raise TwitterError(6, 'X\'s Explore answer is not what this skill expects.', 'Tell the user the X reader '
                                                                                         'needs an update.',
                               reason='shape_changed')
        instructions = ((initial.get('timeline') or {}).get('timeline') or {}).get('instructions')
        if not isinstance(instructions, list):
            raise _changed('ExplorePage')
        page = list_page(instructions)
        self.confirm()
        return tabs, initial.get('id'), page

    def search(self, text, product, cursor):
        """One page of X's search for `text` (posts Top or Latest, People, Media), operators as typed."""
        return self.timeline('SearchTimeline', {'rawQuery': text, 'product': product,
                                                'withGrokTranslatedBio': product in ('Top', 'People')}, cursor)

    def quotes(self, post_id, sort, cursor):
        """One page of the posts quoting a post, asked the way X's own quotes screen asks (a search)."""
        query = f'quoted_tweet_id:{post_id} OR url:"status/{post_id}/video" OR url:"status/{post_id}/photo"'
        product = 'Latest' if sort == 'recent' else 'Top'
        return self.timeline('SearchTimeline', {'rawQuery': query, 'product': product, 'querySource': 'tdqt',
                                                'withGrokTranslatedBio': product == 'Top'}, cursor)
