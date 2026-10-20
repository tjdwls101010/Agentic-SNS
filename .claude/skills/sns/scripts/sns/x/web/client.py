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

The client follows the client protocol of reading.Platform: every request runs in guard.request() (the operation is its
scope), every answer is classified, X's limit headers become a limits.Fact, a 429 or an exhausted window becomes a hold
on that operation, a lock or challenge a person block, and the account the page shows goes to connection.seen().
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

from sns.errors import SnsError, diagnostic
from sns.x.web import classify
from sns.x.web.records import (account_record, community_record, list_page, list_record, missing_community,
                               missing_list, missing_space, post_page, post_record, space_record)
from sns.x.web.snippets import SNIPPETS

OPERATIONS = json.loads(Path(__file__).with_name('operations.json').read_text(encoding='utf-8'))['operations']
READ_OPERATIONS = sorted(OPERATIONS)
START = 'https://x.com/i/xskill'
# 성진: 관찰자가 앱보다 늦게 설치돼 열기를 잴 수 없을 때만 쓰는 예약값 — 실측(이른 설치) 열기는 x.com 13 + 문서 1
OPEN_RESERVE = 20
LOAD_WAIT = 20        # seconds a new tab may take until its app, store and login are there
RELOAD_LIMIT = 1      # tab reloads one command may spend recovering a refused read
REOPEN_LIMIT = 1      # tabs one command may replace after Aside lost the one it used
# 성진: 앱이 처음 답한 뒤에도 로드 꼬리가 이어진다(라이브: 10건) — 새것 없는 look 2번 연속이나 이 초까지 기다려 열기에 넣는다.
# 꼬리가 더 길게 이어지는 게 보이면(첫 읽기의 배경 요청이 계속 크면) 늘린다
QUIET_LOOKS, QUIET_WAIT = 2, 4.0
_GONE = 'Run the command again; it opens a new tab.'
# What the request log says an answer was (the names the contrast watch stops a run on); a lock or challenge is named by
# its reason
OUTCOMES = {'login': 'login_required', 'csrf': 'login_required'}


def _int(value, default=0):
    return value if type(value) is int and value >= 0 else default


def _changed(operation):
    return SnsError('failed', f'X\'s answer to {operation} is not where or what this skill expects.', classify.UPDATE_FIX,
                    reason='shape_changed')


def _host(url):
    try:
        return urlsplit(url or '').hostname or ''
    except ValueError:
        return ''


def _verification(error):
    """Why the check that could lift a block failed, from what stopped it."""
    if error.reason == 'verification':
        return error.details.get('verification_reason') or 'aside'
    if error.reason == 'login':
        return 'logged_out'
    if error.reason == 'account_changed':
        return 'account_mismatch'
    if error.reason in ('account_locked', 'challenge'):
        return 'moved'
    if error.reason == 'time_limit':
        return 'time_limit'
    if error.kind == 'scope_limit':
        return 'rate_limited'
    if error.kind == 'aside':
        return 'aside'
    return 'failed'


def _keep_block(why, message, **details):
    return SnsError('blocked', 'The block stays: ' + message, classify.UNBLOCK_FIX, reason='verification',
                    verification_reason=why, **details)


class Client:
    """One invocation's connection to X, built from the pipeline's connection (aside, guard, session)."""

    def __init__(self, connection):
        self.connection = connection
        self.aside, self.guard, self.session = connection.aside, connection.guard, connection.session
        self.verbose = connection.verbose
        self.clock = self.guard.clock
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
        self.reopens = 0
        self.provisional = {}       # operation → (query_id, features) used this command; saved once a read validates it
        self.nonce = {'sent': 0, 'matched': 0}

    # --- the tab ---------------------------------------------------------------------------------------------

    def start(self):
        """Find, re-check and if needed open the dedicated tab under the session lock; returns the account id."""
        with self.session.opening():
            self.session.reload()
            self.session_reset = self.session.reset
            known = self.session.tab
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
                    self.token = self.session.touch()
        return self.account_id

    def viewer(self):
        """The X account the tab is logged in to (known from the page; asking X is verify's one request)."""
        return self.account_id

    def _entry(self, target):
        return next((t for t in self.aside.tabs() if target and t['target_id'] == target), None)

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
        with self.session.opening():
            self.session.reload()
            known = self.session.tab
            entry = self._entry(known) if known != self.tab else None
            if entry and _host(entry['url']) == 'x.com':
                self.tab = known
                self._take_over()  # what it requested was the other command's to count
            else:
                self._open()

    def _args(self, args):
        return {**args, '__ack': self.session.ack}

    def _state(self):
        state = self.aside.evaluate(self.tab, SNIPPETS['state'], self._args({}))
        if not isinstance(state, dict) or not isinstance(state.get('location'), str):
            raise SnsError('aside', 'The X tab answered invalidly.', 'Run x doctor.')
        return state

    def _open(self):
        """Open a new dedicated tab: about:blank first (recorded before it can poll), attached, its opener ended, then
        sent to x.com with the kit installed as the load begins. Counted apart from the command's reads (setup)."""
        with self.guard.request(reserve=1, setup=True, kind='tab_open') as slot:
            with self.aside.opener() as target:
                self.tab = target
                self.session.set_tab(target)
                armed = self._load(slot, target)
            try:
                listed = self.aside.tabs()
            except SnsError:
                slot.charge(OPEN_RESERVE)  # the tab loaded x.com, unmeasured
                slot.classify('opened')
                raise
            if not any(t['target_id'] == target for t in listed):
                slot.charge(OPEN_RESERVE)  # it loaded x.com before Aside closed it, unseen
                slot.classify('tab_closed')
                raise SnsError('aside', 'Aside closed the new X tab when the session that opened it ended; Aside\'s '
                                        'behaviour has changed and the skill needs an update.',
                               'Tell the user the X reader needs an update; retrying opens a tab each time.',
                               reason='aside_changed')
            self.opened_now = True
            self._settle_load(slot, armed)

    def _reload(self):
        """Load the app in the known tab again (its app is older than X's servers): measured like opening, counted as
        setup, at most RELOAD_LIMIT a command."""
        if self.reloads >= RELOAD_LIMIT:
            raise SnsError('failed', 'This command already reloaded the X tab once to recover a refused read.',
                           'Run the command again; if it keeps failing, the skill needs an update.',
                           reason='recovery_budget')
        self.reloads += 1
        with self.session.opening(), self.guard.request(reserve=1, setup=True, kind='tab_reload') as slot:
            armed = self._load(slot, self.tab)
            self.reopened = True
            self._settle_load(slot, armed)

    def _load(self, slot, target):
        """Send the tab to x.com with the kit armed; a load that fails once the tab was sent is charged the reserve."""
        try:
            return self.aside.load(target, START, SNIPPETS['arm'], self._args({}))
        except SnsError as error:
            if error.reason != 'tab_missing':
                slot.charge(OPEN_RESERVE)
            slot.classify('load_failed')
            raise

    def _settle_load(self, slot, armed):
        """Wait for the loaded app, its store and login, checking each look for a block; charge what the load cost:
        what the tab's observer saw plus the document, or, when the kit came too late to see it all, OPEN_RESERVE for
        what came before it plus everything it saw (never set off against each other). Charged however the wait ends."""
        # measured when the kit came before the app ran, or while X's timing buffer still held the whole load
        early = isinstance(armed, dict) and (armed.get('buffer_intact') is True or
                                             (armed.get('ready_at_install') == 'loading' and not armed.get('app_at_install')))
        deadline = self.clock.monotonic() + min(LOAD_WAIT, max(1.0, self.guard.time_left() - 5))
        seen = [1]   # the document itself is a request too; counted up as the looks come in, charged however they end
        slot.classify('opened')
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
            except SnsError as error:
                if error.reason == 'tab_missing' or self.clock.monotonic() > deadline:
                    raise
                self.clock.sleep(0.5)
                continue
            seen[0] += _int(look.get('resources'))
            self._note(look)
            self._consume(look, slot)
            if ready is not None:
                quiet = quiet + 1 if not _int(look.get('resources')) else 0
                if quiet >= QUIET_LOOKS or self.clock.monotonic() > settle_by or self.clock.monotonic() > deadline:
                    return look
                self.clock.sleep(0.5)
                continue
            if look.get('app') and look.get('store') and look.get('user_id'):
                ready, settle_by = look, self.clock.monotonic() + QUIET_WAIT
                self.clock.sleep(0.5)
                continue
            if look.get('app') and look.get('store') and not look.get('user_id'):
                sessionless += 1
                if sessionless >= 2:
                    return look  # the app has loaded its store without a session: logged out
            if self.clock.monotonic() > deadline:
                return look
            self.clock.sleep(0.5)

    def _check(self, state):
        """Raise for a page that is not a working, logged-in x.com page of this command's account (blocks and login
        pages were already handled by _consume)."""
        if _host(state.get('location')) != 'x.com' or not state.get('app') or not state.get('store'):
            raise SnsError('aside', 'The X tab is not a working x.com page.', 'Run x doctor; close the tab if it keeps '
                                                                              'failing.')
        if not state.get('user_id') or not state.get('ct0'):
            raise SnsError('login', 'X login is required in the Aside browser.', classify.LOGIN_FIX, reason='login')
        self.connection.seen(state['user_id'])  # a different account than this command started with is exit 4
        self.account_id = state['user_id']
        self.language = state.get('language')

    def _seen(self, report):
        """The account a page report shows is passed on: a different one than the command started with is exit 4."""
        user = report.get('user_id') if isinstance(report, dict) else None
        if isinstance(user, str) and user:
            self.connection.seen(user)

    def _note(self, report):
        """Remember whether the skill's own requests were told apart by their nonce (doctor reports it)."""
        if isinstance(report, dict):
            self.nonce['matched'] += _int(report.get('ours'))

    def _consume(self, report, slot, defer_login=False):
        """Judge everything one browser call reported. A lock or challenge is recorded and the tab emptied before the
        signals are acknowledged; a login is raised (defer_login: returned, for a caller that has an answer of its own
        to judge first); another operation's limit is recorded as a hold on that operation and the command goes on. The
        tab drops the signals only once protection holds them. Returns (the holds by operation, the deferred login)."""
        holds = {}
        if not isinstance(report, dict):
            return holds, None
        signals = [s for s in report.get('signals') or [] if isinstance(s, dict)]
        verdicts, unrecorded = [], None
        for kept in signals:
            verdict = classify.signal(kept)
            # a window whose reset has already passed (a signal that waited in an idle tab) limits nothing any more
            spent = verdict.reset is not None and verdict.reset <= self.clock.time() and kept.get('status') != 429
            if verdict.kind == 'rate_limited' and not spent:
                try:
                    holds[verdict.bucket] = slot.hold(until=verdict.reset, scope=verdict.bucket)
                except SnsError as error:
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
            self.session.acknowledge(max(moments))
        if strongest is not None and not defer_login:
            raise strongest.error
        return holds, strongest.error if strongest is not None else None

    def _stop(self, slot, verdict, moments=(), account_id=None):
        """Record a block for the account the tab showed (else this command's), empty the tab so the app stops polling
        (even if the block could not be saved), acknowledge the signals it came from, then raise."""
        account_id = account_id if isinstance(account_id, str) and account_id else self.account_id
        try:
            error = slot.block(verdict.block, account_id)
        finally:
            self._empty()
        if moments:
            self.session.acknowledge(max(moments))
        raise error

    def _empty(self):
        """Close the tab, or empty it to about:blank when it stays; makes no request. A tab that still polls is left
        marked for the idle cleanup to try again."""
        emptied = self.connection.empty_tab(self.tab) if self.tab else True
        if not emptied:
            self.session.set_dirty(True)
        return emptied

    def release_tab(self):
        """The idle cleanup: take in what the tab saw, then close or empty it; allowed while a block stands."""
        tab = self.session.tab
        if not tab:
            return False
        self.tab = tab
        with self.guard.observe(allow_blocked=True) as slot:
            try:
                report = self.aside.evaluate(tab, SNIPPETS['state'], self._args({}), 30)
            except SnsError as error:
                if error.reason == 'tab_missing':
                    return True
                report = None
            if isinstance(report, dict):
                self.guard.log_unwatched(_int(report.get('resources')))
                try:
                    self._consume(report, slot)
                except SnsError:
                    pass  # recorded; the tab is being emptied anyway
            emptied = self.connection.empty_tab(tab)
            self.session.set_dirty(not emptied)
            return emptied

    def release(self):
        """Give the tab back; the token the idle cleanup is left behind (None: nothing to clean up)."""
        self.session.note_nonce(self.nonce['sent'], self.nonce['matched'])
        if not self.tab:
            return None
        if self.token:
            self.session.release(self.token)
            return self.token
        return '-' if self.session.reload().dirty else None  # the command never used the tab; something is left to empty

    def report(self):
        return {'unwatched': self.unwatched, 'session_reset': self.session_reset}

    # --- requests --------------------------------------------------------------------------------------------

    def _call(self, name, args, operation, judge=None):
        """One guarded browser call that may send `operation`: block, limit and pacing first; the answer and every
        signal the tab kept are judged — and a block or limit recorded — before the lock is released (judge(result)
        gives the verdict on the answer itself). A vanished tab is reopened once (outside this request's charge)."""
        for attempt in range(2):
            try:
                with self.guard.request(scope=operation) as slot:
                    try:
                        result = self.aside.evaluate(self.tab, SNIPPETS[name], self._args(args))
                    except SnsError as error:
                        if error.reason == 'tab_missing':
                            slot.cancel()  # the program never reached a page, so nothing went to X
                        raise  # any other loss may have sent the request: the slot stays charged at 1
                    if not isinstance(result, dict):
                        slot.classify('invalid')
                        raise SnsError('aside', 'The X tab answered invalidly.', 'Run x doctor.')
                    slot.classify('answered')
                    sent = bool(result.get('explicit'))
                    if not sent:
                        slot.cancel()  # refused, missing or stopped in the page: nothing was sent
                    slot.charge(int(sent) + _int(result.get('resources')))
                    if sent:
                        self.nonce['sent'] += 1
                        limit = classify.fact(result.get('headers'))
                        if limit is not None:
                            slot.fact(operation, limit)  # X's window for this operation, as the headers state it
                    self._note(result)
                    if self.verbose:
                        diagnostic('request', operation=operation, count=self.guard.count, status=result.get('status'),
                                   source=(result.get('used') or {}).get('source'))
                    holds, login = self._consume(result, slot, defer_login=True)
                    self._seen(result)
                    if login is not None and not (sent and isinstance(result.get('status'), int)):
                        raise login  # nothing came back to judge: the signal is the answer
                    if result.get('stopped') == 'limit':
                        raise holds.get(operation) or slot.hold(scope=operation)
                    if result.get('stopped'):
                        raise SnsError('failed', 'The tab held signals this skill could not clear, so nothing was sent.',
                                       'Run x doctor; close the tab if it keeps happening.', reason='stuck')
                    if result.get('refused'):
                        raise SnsError('argument', 'The browser refused a request this skill must not make: '
                                                   + str(result['refused']) + '.', 'Report this as a skill bug.')
                    if result.get('login'):
                        slot.classify('login_required')
                        raise SnsError('login', 'X login is required in the Aside browser.', classify.LOGIN_FIX,
                                       reason='login')
                    if result.get('missing'):
                        raise SnsError('failed', 'The X tab lacks ' + str(result['missing']) + ', so nothing was sent.',
                                       'Run the command again; if it keeps failing, the skill needs an update.',
                                       reason='missing')
                    if result.get('network_error'):
                        slot.classify('network_error')
                        raise SnsError('failed', 'The request to X did not complete.', classify.RETRY_FIX,
                                       reason='network')
                    verdict = judge(result) if judge else None
                    if verdict is not None:
                        slot.classify(OUTCOMES.get(verdict.kind) or verdict.block or verdict.kind)
                        if verdict.kind == 'rate_limited':
                            stop = slot.hold(until=verdict.reset, scope=operation)  # recorded either way
                            raise login or stop  # a logout outranks the limit (the exit priority: block, login, limit)
                        if verdict.block:
                            self._stop(slot, verdict)
                    if login is not None:
                        raise login  # the own answer was judged first: a block it met outranks a logout seen beside it
                    return result, verdict
            except SnsError as error:
                if error.reason != 'tab_missing' or attempt or self.guard.checking or self.reopens >= REOPEN_LIMIT:
                    raise
                self.reopens += 1
                self._reopen()
        raise SnsError('failed', 'The X tab could not be used.', _GONE)

    def _fallback(self, operation):
        learned = self.session.query(operation) or {}
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
                raise SnsError('failed', f'X no longer runs {operation} as this skill sends it.',
                               'Tell the user the X reader needs an update; other commands may work.', reason='stale')
            raise verdict.error

    def confirm(self):
        """The read was turned into records: remember the operation ids the live tab gave, for when it cannot."""
        for operation, (query_id, features) in self.provisional.items():
            self.session.learn(operation, query_id, features)
        self.provisional = {}

    def live_operations(self):
        """Which of the skill's operations the tab's app defines now, lazy chunks loaded by hint; makes no x.com
        request."""
        hints = sorted({spec['chunk_hint'] for spec in OPERATIONS.values() if spec.get('chunk_hint')})
        with self.guard.observe() as slot:
            result = self.aside.evaluate(self.tab, SNIPPETS['modules'],
                                         self._args({'names': READ_OPERATIONS, 'hints': hints}))
            if isinstance(result, dict):
                slot.charge(_int(result.get('resources')))  # the page's own requests while this command ran
            self._consume(result, slot)
        return result if isinstance(result, dict) else {}

    def verify(self, check):
        """The one request that may lift a person block: the tab's own account, read with one Viewer query inside the
        check (X's Viewer limit, pacing and the deadline still hold). Clean only when X answers for this tab's account
        and the block was recorded for it (or for no known account); anything else keeps the block and says why."""
        try:
            viewer = self.start()
            blocked_for = (check.person or {}).get('viewer')
            if blocked_for and blocked_for != viewer:
                raise _keep_block('account_mismatch', f'it was recorded for X account {blocked_for}, and the browser is '
                                                      f'logged in to {viewer}. A person should check which account was '
                                                      'locked.')
            root, _ = self.query('Viewer', {})
        except SnsError as error:
            if error.reason == 'verification':
                raise
            raise _keep_block(_verification(error), error.message.rstrip('.') + '.', **{
                k: v for k, v in error.details.items() if k in ('reset', 'next_allowed_at')}) from None
        answered = str((root or {}).get('rest_id', '')) if isinstance(root, dict) else ''
        if answered != viewer:
            raise _keep_block('account_mismatch', 'X answered for another account than the tab is logged in to.')

    def doctor(self):
        """The X-specific part of doctor: the tab, what the app defines now, and whether own requests are told apart."""
        live = self.live_operations()
        nonce = self.session.nonce
        matched = nonce['matched'] + self.nonce['matched']
        sent = nonce['sent'] + self.nonce['sent']
        return {
            'tab': {'target_id': self.tab, 'opened_now': self.opened_now, 'reopened': self.reopened,
                    'opening_measured': self.measured_open},
            'operations': {name: (value['type'] if value else 'not in the tab (stored id used)')
                           for name, value in sorted((live.get('live') or {}).items())},
            'signature_generator': bool(live.get('generator')), 'bearer': bool(live.get('bearer')),
            'own_request_matching': ('confirmed' if matched else 'not seen yet (an own request may be counted twice)'
                                     if sent else 'not tried yet'),
        }

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
        gone = SnsError('unavailable', 'This post is unavailable: deleted, withheld, protected or not visible to this '
                                       'account.', 'Tell the user; retrying will not change it.', reason='unavailable')
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
            if node is None:
                continue  # X answers null for an id it does not know (observed): not returned, not unreadable
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
        gone = SnsError('unavailable', f'X has no account @{handle} visible to this account (suspended, deactivated or '
                                       'never existed).', 'Check the handle; tell the user rather than retrying.',
                        reason='unavailable')
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
        gone = SnsError('unavailable', 'This list is unavailable: deleted, private or never existed.',
                        'Check the list id; tell the user rather than retrying.', reason='unavailable')
        root, warnings = self.query('ListByRestId', {'listId': list_id}, missing=gone)
        record = list_record(root)
        if record is None:
            raise gone if missing_list(root) else _changed('ListByRestId')
        self.confirm()
        return record

    def community(self, community_id):
        """One community's card (one request); a community X does not return to this account is unavailable."""
        gone = SnsError('unavailable', 'This community is unavailable: deleted, suspended or never existed.',
                        'Check the community id; tell the user rather than retrying.', reason='unavailable')
        root, warnings = self.query('CommunityByRestId', {'communityId': community_id}, missing=gone)
        record = community_record(root)
        if record is None:
            raise gone if missing_community(root) else _changed('CommunityByRestId')
        self.confirm()
        return record

    def space(self, space_id):
        """One space's card (one request); a space X does not return is unavailable."""
        gone = SnsError('unavailable', 'This space is unavailable: it never existed or X no longer keeps it.',
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
            raise SnsError('failed', 'X\'s Explore answer is not what this skill expects.', 'Tell the user the X reader '
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
