"""The Threads web client: requests made from the skill's own www.threads.com tab, the way the app makes them.

The tab is opened once on a quiet screen (`aside <url>`) and reused; each read is one GraphQL request sent with the
page's own parameters and headers, one request per browser call. Query ids and provider values come from the app's
loaded module when it has one, else from what an earlier read learned, else from the bundled snapshot. When Threads
refuses a query, the client learns its current id once from the screen that uses it (one document read and the
static bundles it names) or, when the tab's own module was refused, reloads the tab once; a command never recovers
more than that. Every response the tab saw is checked for a block before the next request is sent.

The client follows the client protocol of reading.Platform: every request runs in guard.request(), every answer is
classified, a 429 becomes a hold on the account (30 minutes unless Threads said otherwise), a checkpoint a person
block, and the account the page shows goes to connection.seen().
"""
import json
from pathlib import Path
from urllib.parse import quote, urlsplit

from sns.errors import SnsError, diagnostic
from sns.threads.web import classify, learn, records
from sns.threads.web.snippets import SNIPPETS
from sns.threads.web.targets import ROUTE_SOURCE

SNAPSHOT = json.loads(Path(__file__).with_name('queries.json').read_text(encoding='utf-8'))
QUERIES = SNAPSHOT['queries']
START = SNAPSHOT['start_screen']
# What the page itself loads cannot be bounded or attributed exactly, so opening (or reloading) the tab is prepaid:
# measured 34 Threads requests on the search screen, 38 on home. Requests the page finishes later in the same
# command use up what is left of the reservation first.
OPEN_RESERVE = 40
LEARN_LIMIT = 3     # document reads one command may spend learning queries (each is one request)
RELOAD_LIMIT = 1    # tab reloads one command may spend when the app's own module was refused
REOPEN_LIMIT = 1    # tabs one command may replace after Aside lost the one it used
LOAD_WAIT = 20      # seconds to wait for a tab to finish loading
_GONE = 'Run the command again; it opens a new tab.'
# What the request log says an answer was
OUTCOMES = {'checkpoint': 'checkpoint', 'rate_limit': 'rate_limited', 'login': 'login_required'}


def _int(value, default=0):
    return value if type(value) is int and value >= 0 else default


def _explicit_null(body):
    """Whether a response names its data fields and answers each with null, without errors: the target is not there
    (a server error or a missing data object is a failure, not an answer)."""
    try:
        payload = json.loads((body or '').replace('for (;;);', '', 1))
    except ValueError:
        return False
    data = payload.get('data') if isinstance(payload, dict) else None
    return (isinstance(data, dict) and bool(data) and all(value is None for value in data.values())
            and not payload.get('errors') and not payload.get('error'))


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
    if error.reason == 'checkpoint':
        return 'moved'
    if error.reason == 'rate_limited':
        return 'rate_limited'
    if error.reason == 'time_limit':
        return 'time_limit'
    if error.kind == 'aside':
        return 'aside'
    return 'failed'


def _keep_block(why, message, **details):
    return SnsError('blocked', 'The block stays: ' + message, classify.UNBLOCK_FIX, reason='verification',
                    verification_reason=why, **details)


def _first(*errors):
    """The error a command ends with when several spoke at once: a person block, then a hold, then an account change,
    then anything else (each already recorded); None when there is none."""
    def rank(error):
        if error.kind == 'blocked':
            return 0 if error.reason != 'rate_limited' else 1
        return 2 if error.reason == 'account_changed' else 3
    found = [error for error in errors if error is not None]
    return min(found, key=rank) if found else None


class Client:
    """One invocation's connection to Threads, built from the pipeline's connection (aside, guard, session)."""

    def __init__(self, connection):
        self.connection = connection
        self.aside, self.guard, self.session = connection.aside, connection.guard, connection.session
        self.verbose = connection.verbose
        self.clock = self.guard.clock
        self.tab = None
        self.account_id = None
        self.opened_now = False
        self.reopened = False
        self.session_reset = False
        self.unwatched = 0
        self.token = None
        self.prepaid = 0                                  # what the tab opening reserved and the page has not used yet
        self.recovery = {'learn': 0, 'reload': 0}
        self.reopens = 0
        self.provisional = {}  # key → (name, doc_id, flags) found this command; saved only once a read validates it

    # --- the tab ---------------------------------------------------------------------------------------------

    def start(self):
        """Find, re-check and if needed open the dedicated tab under the session lock; returns the account id."""
        with self.session.opening():
            self.session.reload()
            self.session_reset = self.session.reset
            known = self.session.tab
            entry = self._entry(known)
            try:
                if entry and _host(entry['url']) == 'www.threads.com':
                    self.tab = known
                    with self.guard.observe() as slot:
                        state = self._state()
                        self.unwatched = _int(state.get('resources'))
                        self.guard.log_unwatched(self.unwatched)  # made between commands: logged, not charged
                        self._consume(state, slot)
                        self._check(state)
                else:
                    # A tab this skill emptied earlier is not sent back to Threads: Aside drops an emptied tab once
                    # nothing holds it, even mid-load, and a query would then open another one.
                    self._open()
                    self.reopened = bool(entry)
            finally:
                if self.tab:  # a tab that failed to open still polls: the idle cleanup must know of it
                    self.token = self.session.touch()
        return self.account_id

    def viewer(self):
        """The Threads account the tab is logged in to (known from the page; asking Threads is verify's one request)."""
        return self.account_id

    def _entry(self, target):
        return next((t for t in self.aside.tabs() if target and t['target_id'] == target), None)

    def _reopen(self):
        """The tab vanished mid-command: use the one another command opened meanwhile, else open one (once)."""
        with self.session.opening():
            self.session.reload()
            known = self.session.tab
            entry = self._entry(known) if known != self.tab else None
            if entry and _host(entry['url']) == 'www.threads.com':
                self.tab = known  # what it requested was the other command's to count
            else:
                self._open()

    def _args(self, args):
        return {**args, '__ack': self.session.ack, '__markers': classify.SIGNAL_MARKERS}

    def _state(self, document=False):
        state = self.aside.evaluate(self.tab, SNIPPETS['state'], self._args({'document': document}))
        if not isinstance(state, dict) or not isinstance(state.get('location'), str):
            raise SnsError('aside', 'The Threads tab answered invalidly.', 'Run threads doctor.')
        return state

    def _open(self):
        """Open a new dedicated tab: its document and what the page loads are counted apart, as setup."""
        before = {t['target_id'] for t in self.aside.tabs()}
        with self.guard.request(reserve=OPEN_RESERVE, setup=True, kind='tab_open') as slot:
            try:
                self.aside.open(START)
                new = [t for t in self.aside.tabs() if t['target_id'] not in before and
                       _host(t['url']).endswith('threads.com')]
            except SnsError:
                slot.classify('open_failed')
                raise
            if not new:
                slot.classify('open_failed')
                raise SnsError('aside', 'Aside did not open the Threads tab.', 'Check Aside, then run threads doctor.')
            self.tab = new[-1]['target_id']
            self.session.set_tab(self.tab)
            self.opened_now = True
            self._settle_load(slot)

    def _load(self, navigate):
        """Load Threads in the known tab again (it was emptied, or its app was refused): counted like opening."""
        with self.guard.request(reserve=OPEN_RESERVE, setup=True, kind='tab_open') as slot:
            if navigate:
                try:
                    self.aside.evaluate(self.tab, SNIPPETS['navigate'], self._args({'url': START}))
                except SnsError:
                    slot.classify('open_failed')
                    raise
            self.opened_now = self.reopened = True
            self._settle_load(slot)

    def _settle_load(self, slot):
        """Wait for the loaded app and then for the page to go quiet, so what loading it costs is charged here (prepaid)
        and not to the next read; then check the new page before any query: where it is, what loading it answered (a
        429), and the document's own checkpoint and login markers."""
        deadline = self.clock.monotonic() + min(LOAD_WAIT, max(1.0, self.guard.time_left() - 5))
        seen, state = 1, None
        slot.classify('opened')
        try:
            while True:
                try:
                    look = self._state(document=state is None)
                except SnsError as error:
                    # the page is replacing its document; a vanished tab or the time limit ends the wait
                    if error.reason == 'tab_missing' or self.clock.monotonic() > deadline:
                        raise
                    self.clock.sleep(1)
                    continue
                new = _int(look.get('resources'))
                seen += new  # every look's requests count, and every look is checked
                slot.charge(seen)
                self._consume(look, slot)
                if state is not None:
                    self._check(look)  # still a working page of the same logged-in account
                    if not new:
                        break  # quiet: what the page sends from now on is its own polling
                if state is None and (look.get('runtime') and look.get('user_id') or self.clock.monotonic() > deadline):
                    state = look
                    self._check_document(state, slot)  # a checkpoint or login page stops at once, not once quiet
                if self.clock.monotonic() > deadline:
                    break
                self.clock.sleep(1)
        finally:
            self.prepaid = max(0, slot.reserved - seen)
        self._check(state)

    def _check_document(self, state, slot):
        if state.get('document'):
            verdict = classify.document(state['document'])
            if verdict.block:
                self._stop(slot, verdict)
            if verdict.kind == 'login':
                slot.classify('login_required')
                raise verdict.error

    def _check(self, state):
        """Raise for a page that is not a working, logged-in Threads page of this command's account (blocks and
        login pages were already handled by _consume)."""
        if not state.get('runtime') or _host(state['location']) != 'www.threads.com':
            raise SnsError('aside', 'The Threads tab is not a working Threads page.',
                           'Run threads doctor; close the tab if it keeps failing.')
        if not state.get('user_id') or state['user_id'] == '0':
            raise SnsError('login', 'Threads login is required in the Aside browser.', classify.LOGIN_FIX,
                           reason='login')
        self.connection.seen(state['user_id'])  # a different account than this command started with is exit 4
        self.account_id = state['user_id']

    def _seen(self, report):
        """The account a page report shows is passed on: a different one than the command started with is exit 4."""
        user = report.get('user_id') if isinstance(report, dict) else None
        if isinstance(user, str) and user and user != '0':
            self.connection.seen(user)

    def _changed(self, report):
        """The account-changed error a page report shows, returned rather than raised so the answer is judged first."""
        try:
            self._seen(report)
        except SnsError as error:
            if error.reason != 'account_changed':
                raise
            return error
        return None

    def _consume(self, report, slot, defer_login=False, defer=False):
        """Judge everything one browser call reported, strongest first: a checkpoint, then a rate limit, then a login
        page. A block or hold is recorded and the tab emptied before the signals are acknowledged, so the tab drops
        them only once protection holds them; then the block, hold or login is raised (defer_login: a login is returned
        instead, for a caller that has an answer of its own to judge first, which may be a hold to record; defer: any
        of them is returned instead, with the block or hold already recorded)."""
        if not isinstance(report, dict):
            return None
        verdicts = []
        if 429 in (report.get('statuses') or []):
            verdicts.append(classify.response({'status': 429, 'url': '', 'body': ''}, mode='graphql'))
        signals = [s for s in report.get('signals') or [] if isinstance(s, dict)]
        verdicts += [classify.signal(s) for s in signals]
        if isinstance(report.get('location'), str) and report['location'].startswith('http'):
            verdicts.append(classify.response({'status': 200, 'url': report['location'], 'body': ''}, mode='page'))
        if report.get('markers'):
            body = '\n'.join(map(str, report['markers']))
            verdicts.append(classify.response({'status': 200, 'url': START, 'body': body}, mode='page'))
        strongest = classify.strongest(verdicts)
        moments = [s['at'] for s in signals if type(s.get('at')) in (int, float)]
        if strongest is not None and strongest.block:
            # a hold beside a checkpoint is recorded too (the strongest decides only which error is raised)
            for other in {v.block: v for v in verdicts if v.block and v.block != strongest.block}.values():
                self._stop(slot, other, moments, report.get('user_id'), raise_=False)
            error = self._stop(slot, strongest, moments, report.get('user_id'), raise_=not defer)
            return error
        if moments:
            self.session.acknowledge(max(moments))
        if strongest is not None:
            slot.classify(OUTCOMES[strongest.kind])
            if defer_login or defer:
                return strongest.error
            raise strongest.error
        return None

    def _stop(self, slot, verdict, moments=(), account_id=None, raise_=True):
        """Record a block (a checkpoint) or a hold (a 429), empty the tab so the app stops polling (even if it could not
        be saved), acknowledge the signals it came from, then raise (raise_ False: return the error)."""
        account_id = account_id if isinstance(account_id, str) and account_id and account_id != '0' else self.account_id
        slot.classify(OUTCOMES[verdict.block])
        try:
            error = slot.block('checkpoint', account_id) if verdict.block == 'checkpoint' else slot.hold()
        finally:
            self._empty()
        if moments:
            self.session.acknowledge(max(moments))
        if not raise_:
            return error
        raise error

    def _empty(self):
        """Close or empty the tab so the app stops polling; makes no request. A tab that still polls is left marked for
        the idle cleanup to try again."""
        emptied = self.connection.empty_tab(self.tab) if self.tab else True
        if not emptied:
            self.session.set_dirty(True)
        return emptied

    def release_tab(self):
        """The idle cleanup: take in what the tab saw, then empty it; allowed while a block stands."""
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
        if not self.tab:
            return None
        if self.token:
            self.session.release(self.token)
            return self.token
        # the command never used the tab: something is left to empty only when an earlier cleanup failed
        return '-' if self.session.reload().dirty else None

    def report(self):
        return {'unwatched': self.unwatched, 'session_reset': self.session_reset}

    # --- requests --------------------------------------------------------------------------------------------

    def _request(self, name, args, verdict_of, label, setup=False, kind=None):
        """One guarded request: block check and pacing; the response and every signal the tab kept are classified, and
        a block or hold recorded, before the lock is released. A vanished tab is reopened once."""
        for attempt in range(2):
            try:
                with self.guard.request(setup=setup, kind=kind or 'query') as slot:
                    try:
                        result = self.aside.evaluate(self.tab, SNIPPETS[name], self._args(args))
                    except SnsError as error:
                        if error.reason == 'tab_missing':
                            slot.cancel()  # the program never reached a page, so nothing went to Threads
                        raise
                    if not isinstance(result, dict):
                        slot.classify('invalid')
                        raise SnsError('aside', 'The Threads tab answered invalidly.', 'Run threads doctor.')
                    slot.classify('answered')
                    if result.get('stopped') or result.get('refused') or result.get('missing'):
                        slot.cancel()  # our request was not sent; what the tab finished meanwhile still counts
                        self._charge(slot, {**result, 'explicit': 0})
                    else:
                        self._charge(slot, result)
                    if self.verbose:
                        diagnostic('request', label=label, count=self.guard.count, status=result.get('status'),
                                   source=(result.get('used') or {}).get('source'))
                    # Everything is judged and recorded before anything is raised: an account change, the tab's own
                    # signals and the answer itself may all speak at once, and a block or hold in any of them must be
                    # in protection whichever error the command ends with.
                    changed = self._changed(result)
                    pending = self._consume(result, slot, defer=True)
                    if not isinstance(result.get('status'), int) and (pending or changed):
                        raise _first(pending, changed)  # nothing came back to judge: the signals are the answer
                    if result.get('stopped') and not attempt and not (pending or changed):
                        continue  # what stopped it was benign and is acknowledged now: send it once more
                    if result.get('refused'):
                        raise SnsError('argument', 'The browser refused a request this skill must not make: '
                                       + str(result['refused']) + '.', 'Report this as a skill bug.')
                    if result.get('network_error'):
                        slot.classify('network_error')
                        raise _first(pending, changed) or SnsError('failed', 'The request to Threads did not complete.',
                                                                   classify.RETRY_FIX, reason='network')
                    verdict = verdict_of(result)
                    own = self._stop(slot, verdict, account_id=result.get('user_id'), raise_=False) \
                        if verdict.block else None  # recorded for the account the answer came back under
                    first = _first(own, pending, changed)
                    if first is not None:
                        raise first
                    if verdict.kind != 'ok':
                        slot.classify(OUTCOMES.get(verdict.kind) or verdict.reason or verdict.kind)
                    return result, verdict
            except SnsError as error:
                if error.reason != 'tab_missing' or attempt or self.guard.checking or self.reopens >= REOPEN_LIMIT:
                    raise
                self.reopens += 1
                self._reopen()
        raise SnsError('failed', 'The tab kept holding signals this skill could not clear, so nothing was sent.',
                       'Run threads doctor; close the tab if it keeps happening.', reason='stuck')

    def _charge(self, slot, result):
        """Charge what the call sent and what the tab finished meanwhile; late requests use up a reservation first."""
        explicit, seen = _int(result.get('explicit'), 1), _int(result.get('resources'))
        seen = max(seen, explicit)
        extra = max(0, seen - explicit)
        used = min(extra, self.prepaid)
        self.prepaid -= used
        slot.charge(explicit + extra - used)

    def _allowed(self):
        names = {spec['name'] for spec in QUERIES.values() if spec['name']}
        names |= {self.session.renamed(key) for key in QUERIES if self.session.renamed(key)}
        return sorted(names | {name for name, _, _ in self.provisional.values()})

    def _spec(self, key):
        spec = dict(QUERIES[key])
        if key in self.provisional:
            spec['name'], spec['doc_id'], spec['flags'] = self.provisional[key]
            return spec
        renamed = self.session.renamed(key)
        if renamed:
            spec['name'], spec['doc_id'] = renamed, None
        return spec

    def _confirm(self, key):
        """A read under a name found this command came back and was read into records: remember the name."""
        if key in self.provisional:
            name, doc_id, flags = self.provisional.pop(key)
            self.session.rename(key, name)
            self.session.learn(name, doc_id, flags)

    def query(self, key, variables, *, route=None, missing=None):
        """The decoded payload of one read query; a refused one is learned again once (see the module docstring)."""
        spec = self._spec(key)
        for attempt in range(2):
            if not spec['name']:
                self._learn(key, spec, route)
                spec = self._spec(key)
                continue
            learned = self.session.query(spec['name']) or {}
            if key in self.provisional:
                learned = {'doc_id': spec['doc_id'], 'flags': spec.get('flags')}
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
                if self.guard.checking:
                    raise SnsError('failed', 'Threads no longer runs this query as sent.', classify.REJECTED_FIX,
                                   reason='stale')
                if used.get('source') in ('live', 'live_id'):
                    self._reload()
                else:
                    self._learn(key, spec, route)
                spec = self._spec(key)
                continue
            if missing is not None and verdict.reason == 'shape_changed' and _explicit_null(result.get('body')):
                raise missing  # this read's empty answer means its target is not there
            if verdict.error:
                raise verdict.error
            if verdict.kind != 'ok':
                raise SnsError('failed', f'Threads did not run {spec["name"]}.', classify.REJECTED_FIX, reason='stale')
            if used.get('source') in ('live', 'live_id') and isinstance(used.get('doc_id'), str):
                flags = learn.provider_values(used.get('flags') or {}) if used.get('flags') else None
                self.session.learn(spec['name'], used['doc_id'], flags)
            return verdict.payload
        raise SnsError('failed', f'Threads still refuses {spec["name"]} after learning its current id.',
                       'Tell the user the Threads reader needs an update.', reason='stale')

    def _recover(self, kind):
        if self.recovery[kind] >= (LEARN_LIMIT if kind == 'learn' else RELOAD_LIMIT):
            raise SnsError('failed', 'This command already spent its recovery allowance on queries Threads refused.',
                           'Run the command again: what was learned is kept and it continues from there.',
                           reason='recovery_budget')
        self.recovery[kind] += 1

    def _reload(self):
        """The tab's own module was refused (the app in the tab is older than Threads): load it again, once; a tab
        emptied or lost meanwhile is replaced by a new one, never sent back to Threads."""
        self._recover('reload')
        with self.session.opening():
            entry = self._entry(self.tab)
            if entry and _host(entry['url']) == 'www.threads.com':
                self._load(navigate=True)
            else:
                self._open()
                self.reopened = True

    def _learn(self, key, spec, route):
        """Learn `key`'s current id from the screen that uses it: its preloaders, then its bundles, then a renamed
        successor found by argument names and root field. Raises when none is certain."""
        self._recover('learn')
        path = (spec.get('route') or '/').format(**(route or {}))
        html = self.page(path, setup=True, kind='recovery')
        found = learn.preloaders(html)
        flags = {}
        for entry in found.values():
            flags.update(learn.provider_values(entry['variables']))
        pattern = spec.get('learn_pattern')
        if not spec['name'] and pattern:
            names = [name for name in found if pattern in name and 'Mutation' not in name and name.endswith('Query')]
            if len(names) != 1:
                raise SnsError('failed', f'The {path} screen does not name one query for this read.',
                               'Tell the user the Threads reader needs an update.', reason='stale')
            self.provisional[key] = (names[0], found[names[0]]['doc_id'],
                                     learn.provider_values(found[names[0]]['variables']))
            return
        if spec['name'] in found:
            self.session.learn(spec['name'], found[spec['name']]['doc_id'],
                               learn.provider_values(found[spec['name']]['variables']))
            return
        catalog = learn.search(html, [spec['name']])
        entry = catalog.get(spec['name'])
        if entry and entry.get('doc_id') and entry.get('kind') == 'query':
            wanted = {learn.provider_variable(m) for m in entry.get('providers') or []}
            self.session.learn(spec['name'], entry['doc_id'], {k: v for k, v in flags.items() if k in wanted} or None)
            return
        if entry is None and spec.get('args') is not None:
            new = learn.successor({'args': spec['args'], 'root': spec.get('root')}, catalog, set(self._allowed()))
            if new:
                wanted = {learn.provider_variable(m) for m in catalog[new].get('providers') or []}
                self.provisional[key] = (new, catalog[new]['doc_id'],
                                         {k: v for k, v in flags.items() if k in wanted} or None)
                return
        raise SnsError('failed', f'Threads no longer serves {spec["name"]} and no single successor was found.',
                       'Tell the user the Threads reader needs an update.', reason='stale')

    def page(self, path, *, setup=False, kind=None):
        """The HTML of one Threads document on the read surface, redirects followed by the rules (at most three)."""
        original, hop = path, 0
        while True:
            result, verdict = self._request('page', {'path': path, 'route': ROUTE_SOURCE}, lambda r: classify.response(
                {'status': r.get('status'), 'url': r.get('url'), 'body': r.get('body'),
                 'location': r.get('location_header')}, mode='page'), 'page', setup=setup, kind=kind)
            if verdict.error and verdict.kind != 'ok':
                raise verdict.error
            if 300 <= _int(result.get('status')) < 400 or result.get('status') == 0:
                if self.guard.checking:
                    raise SnsError('failed', 'Threads answered the check with a redirect.', classify.RETRY_FIX,
                                   reason='redirect')
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
            result = self.aside.evaluate(self.tab, SNIPPETS['modules'], self._args({'names': self._allowed()}))
            self._consume(result, slot)
        return (result or {}).get('live') or {}

    def verify(self, check):
        """The one check that may lift a person block: the tab's own account, read through one document (/search)
        inside the check (pacing and the deadline still hold); when no tab could be reused, opening one is the check. Clean only when Threads answers for this tab's account
        and the block was recorded for it (or for no known account); anything else keeps the block and says why."""
        try:
            viewer = self.start()
            blocked_for = (check.person or {}).get('viewer')
            if blocked_for and blocked_for != viewer:
                raise _keep_block('account_mismatch', f'it was recorded for Threads account {blocked_for}, and the '
                                                      f'browser is logged in to {viewer}. A person should check which '
                                                      'account was blocked.')
            if self.opened_now:
                # no tab could be reused: opening one loaded the site as a person does and its first look was judged
                # (checkpoint, login, account), which is the check; nothing more is sent while the block stands
                check.cancel()  # the reserved check request was not sent: give it back, leave no probe
                return
            answer = classify.document(self.page('/search', kind='unblock_check'))
            if answer.kind != 'ok':
                raise answer.error or SnsError('failed', 'The check did not show this account logged in.',
                                               classify.RETRY_FIX)
        except SnsError as error:
            if error.reason == 'verification':
                raise
            raise _keep_block(_verification(error), error.message.rstrip('.') + '.', **{
                k: v for k, v in error.details.items() if k in ('reset', 'until', 'next_allowed_at')}) from None
        if answer.account_id != viewer:
            raise _keep_block('account_mismatch', 'Threads answered for another account than the tab is logged in to.')

    def doctor(self):
        """The Threads-specific part of doctor: the tab and which read queries the app defines now."""
        live = self.live_queries()
        return {'tab': {'target_id': self.tab, 'opened_now': self.opened_now, 'reopened': self.reopened},
                'queries': {name: ('live in the tab' if found else 'stored') for name, found in sorted(live.items())}}

    # --- reads, in the skill's terms ---------------------------------------------------------------------------

    def feed(self, variant, cursor):
        source = 'text_post_feed_following' if variant == 'following' else 'text_post_feed_threads'
        key = 'feed_first' if cursor is None else 'feed_next'
        if cursor is None:
            payload = self.query(key, {'variant': variant, 'data': {'pagination_source': source,
                                                                    'reason': 'cold_start_fetch'}})
        else:
            payload = self.query(key, {'after': cursor, 'variant': variant, 'data': {
                'feed_view_info': '[]', 'pagination_source': source, 'reason': 'pagination', 'session_id': None}})
        return self._read(key, lambda: records.connection_page(payload['data'], 'feed'))

    def _read(self, key, parse):
        """Parse a response into records; only then is a query name found this command remembered."""
        result = parse()
        self._confirm(key)
        return result

    def post_page(self, target, *, sort, limit):
        """The post, its parents and its first reply batch: three requests, no screen move."""
        route = {'post_path': target.path}
        post_id = target.post_id
        gone = SnsError('unavailable', 'This post is unavailable: deleted, or not visible to this account.',
                        'Tell the user; retrying will not change it.', reason='unavailable')
        responses = [self.query('post_target', {'postID': post_id}, route=route, missing=gone)['data'],
                     self.query('post_parents', {'postID': post_id}, route=route)['data'],
                     self.query('post_replies', {'postID': post_id, 'sortOrder': sort.upper()}, route=route)['data']]
        page = records.post_page(responses, code=target.code, post_id=post_id, limit=limit)
        for key in ('post_target', 'post_parents', 'post_replies'):
            self._confirm(key)
        return page

    def reply_batch(self, post_id, cursor, *, sort, path, seen):
        """One further batch of a post's direct replies."""
        payload = self.query('replies_next', {'postID': post_id, 'after': cursor, 'sortOrder': sort.upper()},
                             route={'post_path': path})
        return self._read('replies_next', lambda: records.next_batch(payload['data'], post_id, seen))

    def branch(self, parent, cursor, *, sort, path, seen):
        """One batch of the replies under one reply, read as that reply's own post page lists them (the thread view's
        inline expansion shows only a few): its first batch, then the next ones by cursor."""
        if cursor is None:
            key, variables = 'post_replies', {'postID': parent['id'], 'sortOrder': sort.upper()}
        else:
            key, variables = 'replies_next', {'postID': parent['id'], 'after': cursor, 'sortOrder': sort.upper()}
        payload = self.query(key, variables, route={'post_path': path})
        return self._read(key, lambda: records.branch_batch(payload['data'], parent, seen))

    def activity(self, target, tab):
        """The quotes ('quote') or reposts ('repost') of one post: the one batch Threads sends (one request)."""
        payload = self.query('post_activity', {'post_id': target.post_id, 'tab_type': tab},
                             route={'post_path': target.path})
        return self._read('post_activity', lambda: records.activity_page(payload['data'], tab, target.post_id))

    def profile_id(self, username):
        """The numeric id of a handle, and its user object (one request)."""
        gone = SnsError('unavailable', f'Threads has no profile @{username} visible to this account.',
                        'Check the handle; tell the user rather than retrying.', reason='unavailable')
        payload = self.query('profile_by_name', {'username': username}, route={'username': username}, missing=gone)
        data = payload.get('data') or {}
        user = data.get('xdt_text_app_user_by_username') or data.get('user')
        found = records.user_record(user) if isinstance(user, dict) else None
        if found is None:
            raise gone
        self._confirm('profile_by_name')
        return found['id'], user

    def profile_tab(self, tab, user_id, username, cursor):
        if tab == 'threads':
            key = 'profile_threads' if cursor is None else 'profile_threads_next'
        else:
            key = 'profile_' + tab
        variables = {'userID': user_id, **({'after': cursor} if cursor else {})}
        payload = self.query(key, variables, route={'username': username})

        def parse():
            page = records.connection_page(payload['data'], 'profile_tab')
            # A query learned this command must show what this tab is: this profile's own posts, or its reposts.
            if key in self.provisional:
                def fits(group):
                    mine = any((r.get('author') or {}).get('id') == user_id for r in group)
                    return mine and (tab != 'reposts' or any(r.get('reposted_post') for r in group))
                if not all(fits(group) for group in page.groups):
                    self.provisional.pop(key)
                    raise SnsError('failed', f'The query found for the {tab} tab did not return this profile\'s {tab}.',
                                   'Tell the user the Threads reader needs an update.', reason='stale')
                if not page.groups:
                    self.provisional.pop(key)  # an empty answer proves nothing: used now, not remembered
            return page
        return self._read(key, parse)

    def profile_card(self, user_id, username, *, fallback=None):
        """The profile's card (one request); the user object from the id lookup stands in if the card has none."""
        payload = self.query('profile_card', {'userID': user_id}, route={'username': username})
        data = payload.get('data') or {}
        user = data.get('user') or data.get('xdt_text_app_user') or fallback

        def parse():
            card = records.profile_card(user, username)
            if card['id'] != user_id:  # the card must be the account the id lookup found, whatever query answered
                raise SnsError('failed', 'The profile card is about another account than the one asked for.',
                               classify.CHANGED_FIX, reason='shape_changed')
            return card
        return self._read('profile_card', parse)

    def relation(self, relation, user_id, username, cursor):
        """One page of a profile's followers or following."""
        variables = {'userID': user_id, **({'after': cursor} if cursor is not None else {})}
        payload = self.query(relation, variables, route={'username': username})
        return self._read(relation, lambda: records.connection_page(payload['data'], relation))

    def mine(self, collection):
        """The viewer's liked or saved posts (one batch)."""
        payload = self.query(collection, {}, route={})
        return self._read(collection, lambda: records.connection_page(payload['data'], collection))

    def search_posts(self, text, *, recent, tag, cursor, filters=None):
        variables = {'query': text, 'recent': 1 if recent else 0, 'search_surface': 'tags' if tag else 'default',
                     **({'power_search_info': filters} if filters else {})}
        route = {'query': quote(text)}
        key = 'search_posts' if cursor is None else 'search_posts_next'
        payload = self.query(key, variables if cursor is None else {**variables, 'after': cursor}, route=route)
        return self._read(key, lambda: records.connection_page(payload['data'], 'search_posts'))

    def search_accounts(self, text):
        payload = self.query('search_accounts', {'query': text}, route={'query': quote(text)})
        return self._read('search_accounts', lambda: records.connection_page(payload['data'], 'search_accounts'))
