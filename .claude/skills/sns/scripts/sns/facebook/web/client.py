"""The Facebook web client: requests made from the skill's own facebook.com tab, the way the page makes them.

The tab is opened once (`aside <url>`) and reused; each read is one GraphQL request sent with the page's own request
parameters. Query ids and provider flags come from the page's loaded modules when it has them, else from what an
earlier read learned, else from the bundled snapshot. When Facebook no longer accepts a query, the tab is moved to the
screen that loads that query (as a person would open it) and the read is retried with the id that screen gave: once
per query and a few screens per command, so a failing page never loops.

Request accounting: the skill's own requests are exact. What the page itself requests is prepaid, because it can be
neither bounded nor attributed exactly: opening the tab was measured at about 30 facebook.com requests, moving it to
another screen at 6-9. Requests the page finishes after the call that caused them use up a reservation first, and what
the tab did between commands is logged as unwatched, never charged. Every answer, and every status the tab saw on its
own, is checked for a checkpoint, a login wall or a 429 before the next request goes.

The client follows the client protocol of reading.Platform: every request runs in guard.request() (the account is the
scope), every answer is classified, a 429 anywhere in the tab becomes the account's hold, a checkpoint a person block,
and the account the page shows goes to connection.seen().
"""
import base64
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from sns.errors import SnsError, diagnostic
from sns.facebook.web import classify, targets
from sns.facebook.web.records import (comments_page, group_about, group_card, notifications_page, permalink_post,
                                      posts_page, replies_page, search_page)
from sns.facebook.web.records.search import VERTICALS
from sns.facebook.web.records.search import filters as search_filters
from sns.facebook.web.snippets import SNIPPETS

HOME = 'https://www.facebook.com/'
HOLD_SECONDS = 30 * 60   # how long a 429 holds the account (the policy's hold_seconds; the tab's memory ends with it)
OPEN_RESERVE = 30     # facebook.com requests the page makes while the dedicated tab loads (measured)
ROUTE_RESERVE = 10    # and while it moves to another screen (measured 6-9)
# 성진: 명령당 화면 3번, 쿼리마다 한 번 — 실패하는 페이지가 고리를 돌지 않게 하는 상한. 정상 명령이 더 필요한 게 보이면 올린다
ROUTE_LIMIT = 3       # screens one command may visit to relearn refused query ids (one per query)
REOPEN_LIMIT = 1      # tabs one command may replace after Aside lost the one it used
SNAPSHOT = json.loads((Path(__file__).with_name('queries.json')).read_text(encoding='utf-8'))
QUERIES = SNAPSHOT['queries']
READ_NAMES = sorted(spec['name'] for spec in QUERIES.values())
ABOUT_SECTION = '2327158227'  # the About app section's id
FEED_SORTS = {'top': {'orderby': ['TOP_STORIES'], 'feedStyle': 'DEFAULT'},
              'recent': {'orderby': ['MOST_RECENT'], 'feedStyle': 'MOST_RECENT_FEED_DEFAULT'}}
GROUP_SORTS = {'top': 'TOP_POSTS', 'recent': 'CHRONOLOGICAL', 'activity': 'RECENT_ACTIVITY'}
# all: ranked, nothing filtered out ("All comments"); relevant: Facebook's "Most relevant", which can leave comments
# out; newest: newest first, nothing filtered out.
COMMENT_SORTS = {'all': 'RANKED_UNFILTERED_INTENT_V1', 'relevant': 'RANKED_FILTERED_INTENT_V1',
                 'newest': 'REVERSE_CHRONOLOGICAL_UNFILTERED_INTENT_V1'}
# What the request log says an answer was (the names the contrast watch stops a run on)
OUTCOMES = {'login': 'login_required'}


def _now():
    return datetime.now().astimezone()


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
    if error.reason == 'time_limit':
        return 'time_limit'
    if error.reason == 'rate_limited':
        return 'rate_limited'
    if error.kind == 'aside':
        return 'aside'
    return 'failed'


def _keep_block(why, message, **details):
    return SnsError('blocked', 'The block stays: ' + message, classify.BLOCK_FIX, reason='verification',
                    verification_reason=why, **details)


class Client:
    """One invocation's connection to Facebook, built from the pipeline's connection (aside, guard, session)."""

    def __init__(self, connection):
        self.connection = connection
        self.aside, self.guard, self.session = connection.aside, connection.guard, connection.session
        self.verbose = connection.verbose
        self.tab = None
        self.account_id = None
        self.opened_now = False
        self.session_reset = False
        self.unwatched = 0
        self.token = None
        self.prepaid = {'open': 0, 'route': 0}   # reserved but not yet seen: requests the page may still finish
        self.routes = set()                      # the queries this command already relearned
        self.reopens = 0

    # --- the tab ---------------------------------------------------------------------------------------------

    def start(self):
        """Find, re-check and if needed open the dedicated tab under the session lock; returns the account id."""
        with self.session.opening():
            self.session.reload()
            self.session_reset = self.session.reset
            known = self.session.tab
            entry = next((t for t in self.aside.tabs() if t['target_id'] == known), None) if known else None
            try:
                if entry and _usable(entry['url']):
                    self.tab = known
                    self._take_over(between=True)
                else:
                    # an emptied tab (about:blank) is left alone and a new one opened: Aside closes it once nothing
                    # holds it, and a request in it would open another one
                    self._open()
            finally:
                if self.tab:  # a tab that failed to open still polls: the idle cleanup must know of it
                    self.token = self.session.touch()
        return self.account_id

    def viewer(self):
        """The Facebook account the tab is logged in to (known from the page; asking Facebook is verify's request)."""
        return self.account_id

    def _state(self, fresh=False):
        state = self.aside.evaluate(self.tab, SNIPPETS['state'], {'fresh': fresh})
        if not isinstance(state, dict) or not isinstance(state.get('location'), str):
            raise SnsError('aside', 'The Facebook tab answered invalidly.', 'Run facebook doctor.')
        return state

    def _take_over(self, between=False):
        """Look at the recorded tab before using it: a checkpoint, a login wall or a rate limit it shows is judged.
        between: the requests the page made since the last command are this command's to report (logged as unwatched,
        not charged) — before any verdict, so a block does not hide them."""
        with self.guard.observe() as slot:
            state = self._state()
            if between:
                self.unwatched = _int(state.get('resources'))
                self.guard.log_unwatched(self.unwatched)
            self._check_state(state, slot)

    def _reopen(self):
        """The tab vanished mid-command: use the one another command opened meanwhile, else open one (once)."""
        with self.session.opening():
            self.session.reload()
            known = self.session.tab
            entry = next((t for t in self.aside.tabs() if known != self.tab and t['target_id'] == known), None)
            if entry and _usable(entry['url']):
                self.tab = known
                self._take_over()  # what it requested was the other command's to count
            else:
                self._open()

    def _open(self):
        """Open a new dedicated tab: counted as setup (its document and what the page loads while it does)."""
        before = {t['target_id'] for t in self.aside.tabs()}
        with self.guard.request(reserve=OPEN_RESERVE, setup=True, kind='tab_open') as slot:
            self.aside.open(HOME)
            slot.classify('opened')
            new = [t for t in self.aside.tabs() if t['target_id'] not in before and _facebook(t['url'])]
            if not new:
                raise SnsError('aside', 'Aside did not open the Facebook tab.', 'Check Aside, then run facebook doctor.')
            self.tab = new[-1]['target_id']
            self.session.set_tab(self.tab)
            self.opened_now = True
            state = self._state(fresh=True)
            seen = 1 + _int(state.get('resources'))
            slot.charge(seen)
            self.prepaid['open'] = max(0, OPEN_RESERVE - seen)
            self._check_state(state, slot)

    def _check_state(self, state, slot):
        """Raise for a checkpoint, a login wall or a rate limit among the tab's requests (recorded first), a broken
        page, or another account than this command started with."""
        self._judge(slot, state, classify.location(state['location'], state.get('user_id')))
        if not state.get('runtime'):
            raise SnsError('aside', 'The Facebook tab is not a working Facebook page.',
                           'Run facebook doctor; close the tab if it keeps failing.')
        self.connection.seen(state['user_id'])  # a different account than this command started with is exit 4
        self.account_id = state['user_id']

    def _judge(self, slot, report, verdict):
        """Record what one browser call reported and what its own answer was, then raise the stop that wins: a
        checkpoint (a person block, the tab emptied so the app stops polling), a login wall, then the rate limit — a
        429 on any of the tab's requests (even one finished between commands), a refusal to send because the tab
        already saw one, or the answer's own. The hold is recorded whenever a 429 was seen, whatever else won."""
        statuses = list(report.get('statuses') or []) + list(report.get('unwatched') or [])
        limited = (429 in statuses or report.get('stopped') == 'rate_limit' or bool(report.get('limited'))
                   or verdict.kind == 'rate_limited')
        # the tab's own memory of a 429 ends where that 429 would have: a look five minutes later does not renew it
        remembered = report.get('limited_at')
        fresh = 429 in statuses or verdict.kind == 'rate_limited'
        until = remembered / 1000 + HOLD_SECONDS if not fresh and type(remembered) in (int, float) else None
        hold = slot.hold(until=until) if limited else None
        if verdict.block:
            slot.classify(verdict.block)
            viewer = report.get('user_id')
            try:
                error = slot.block(verdict.block, viewer if isinstance(viewer, str) and viewer else self.account_id)
            finally:
                self._empty()
            raise error
        if verdict.kind == 'login':
            slot.classify('login_required')
            raise verdict.error
        if limited:
            slot.classify('rate_limited')
            raise hold
        slot.classify(OUTCOMES.get(verdict.kind) or verdict.kind)

    def _empty(self):
        """Empty the tab to about:blank (window.close() does not take on Facebook's tab); makes no request. A tab that
        still polls is left marked for the idle cleanup to try again."""
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
                report = self.aside.evaluate(tab, SNIPPETS['state'], {'fresh': False}, 30)
            except SnsError as error:
                if error.reason == 'tab_missing':
                    return True
                report = None
            if isinstance(report, dict):
                self.guard.log_unwatched(_int(report.get('resources')))
                try:
                    self._judge(slot, report, classify.location(report.get('location'), report.get('user_id')))
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
        return '-' if self.session.reload().dirty else None  # the command never used the tab; something is left to empty

    def report(self):
        return {'unwatched': self.unwatched, 'session_reset': self.session_reset}

    # --- requests --------------------------------------------------------------------------------------------

    def _request(self, snippet, args, verdict_of, label, reserve=1, setup=False, kind='query'):
        """One guarded request: block check and pacing; the answer classified before the lock is released. A tab that
        vanished is reopened once (outside this request's charge)."""
        for attempt in range(2):
            try:
                with self.guard.request(reserve=reserve, setup=setup, kind=kind) as slot:
                    try:
                        result = self.aside.evaluate(self.tab, SNIPPETS[snippet], {'fresh': False, **args})
                    except SnsError as error:
                        if error.reason == 'tab_missing':
                            slot.cancel()  # the program never reached a page, so nothing went to Facebook
                        raise  # any other loss may have sent the request: the slot stays charged
                    if not isinstance(result, dict):
                        slot.classify('invalid')
                        raise SnsError('aside', 'The Facebook tab answered invalidly.', 'Run facebook doctor.')
                    if result.get('stopped') or result.get('refused') or result.get('missing'):
                        slot.cancel()  # the tab already showed a rate limit, or the page function sent nothing
                        slot.charge(_int(result.get('resources')))  # what the page itself finished meanwhile is still seen
                    else:
                        self._charge(slot, result, reserve)
                    if self.verbose:
                        diagnostic('request', snippet=snippet, label=label, count=self.guard.count,
                                   status=result.get('status'), source=(result.get('used') or {}).get('source'))
                    if result.get('refused'):
                        slot.classify('refused')
                        raise SnsError('argument', 'The browser refused a request this skill must not make: '
                                       + str(result['refused']) + '.', 'Report this as a skill bug.')
                    if result.get('network_error'):
                        verdict = classify.Verdict('failed', error=SnsError(
                            'failed', 'The request to Facebook did not complete.', classify.RETRY_FIX, reason='network'))
                    elif result.get('stopped') == 'rate_limit':
                        verdict = classify.Verdict('rate_limited')  # the answer is the tab's own memory of a 429
                    else:
                        verdict = verdict_of(result)
                    moved = classify.location(result['location'], result.get('user_id') or self.account_id) \
                        if isinstance(result.get('location'), str) and not result.get('stopped') else None
                    if moved is not None and moved.kind in ('blocked', 'login') and verdict.kind != 'blocked':
                        verdict = moved  # the page went to a checkpoint or login screen by itself while it answered
                    self._judge(slot, result, verdict)
                    self.connection.seen(result.get('user_id'))
                    return result, verdict
            except SnsError as error:
                if error.reason != 'tab_missing' or attempt or self.guard.checking or self.reopens >= REOPEN_LIMIT:
                    raise
                self.reopens += 1
                self._reopen()
        raise SnsError('failed', 'The Facebook tab could not be used.', 'Run the command again; it opens a new tab.')

    def _charge(self, slot, result, reserve):
        """Charge what the call sent and what the tab finished meanwhile; late requests use up a reservation first."""
        explicit, seen = _int(result.get('explicit'), 1), _int(result.get('resources'))
        if reserve > 1:  # a navigation: prepaid, charged in full when the page loaded more
            slot.charge(max(reserve, seen))
            self.prepaid['route'] += max(0, reserve - seen)
            return
        extra = max(0, seen - explicit)
        for bucket in ('open', 'route'):
            used = min(extra, self.prepaid[bucket])
            self.prepaid[bucket] -= used
            extra -= used
        slot.charge(explicit + extra)

    def query(self, key, variables, *, route):
        """The decoded chunks of one read query. A temporary rejection is retried once; a query Facebook no longer
        accepts is relearned once by visiting `route` (the screen that loads it), when this command still may."""
        spec = QUERIES[key]
        retried = False

        def verdict_of(result):
            if result.get('missing'):
                return classify.Verdict('stale', error=SnsError('failed', f'No id for {spec["name"]} is known.',
                                                                classify.STALE_FIX, reason='stale'))
            return classify.response(result, mode='graphql', expected=(spec['expected_key'], spec['kind']),
                                     retried=retried)

        while True:
            learned = self.session.query(spec['name'])
            fallback = {'doc_id': (learned or {}).get('doc_id') or spec['doc_id'],
                        'flags': (learned or {}).get('flags') or SNAPSHOT['relay_provider_flags']}
            args = {'name': spec['name'], 'allowed': READ_NAMES, 'variables': {**spec['variables'], **variables},
                    'fallback': fallback}
            result, verdict = self._request('query', args, verdict_of, key)
            used = result.get('used') or {}
            if verdict.kind == 'retry':
                if retried or self.guard.checking:  # the unblock check is one request: its answer decides
                    raise SnsError('failed', 'Facebook temporarily rejected the request.', classify.RETRY_FIX,
                                   reason='temporary')
                retried = True
                continue
            if verdict.kind == 'stale' and route and self._relearn(spec['name'], route, used.get('doc_id')):
                continue
            if verdict.error:
                raise verdict.error
            if used.get('source') in ('live', 'live_id') and isinstance(used.get('doc_id'), str):
                self.session.learn(spec['name'], used['doc_id'], used.get('flags'))
            return verdict.chunks

    def _relearn(self, name, url, refused):
        """Move the tab to the screen that loads `name` (as a person would open it), so its current id is used next.
        True when a different id was learned; False when this command already relearned `name`, visited its limit of
        screens, or the screen gave the very id that was just refused."""
        if self.guard.checking or name in self.routes or len(self.routes) >= ROUTE_LIMIT:
            return False
        self.routes.add(name)
        parts = urlsplit(url)
        relative = (parts.path or '/') + (('?' + parts.query) if parts.query else '')
        result, verdict = self._request('route', {'path': relative, 'names': [name]},
                                        lambda r: classify.location(r.get('location'), r.get('user_id')), 'route',
                                        reserve=ROUTE_RESERVE, setup=True, kind='route')
        if verdict.error:
            raise verdict.error
        live = (result.get('live') or {}).get(name)
        if not live:
            raise SnsError('failed', f'Facebook no longer accepts the stored {name} and the page did not provide a '
                                     'current one.', classify.STALE_FIX, reason='stale')
        self.session.learn(name, live['doc_id'], live.get('flags'))
        return live['doc_id'] != refused

    def page(self, url):
        """The HTML of one facebook.com page (to find an id the queries need)."""
        result, verdict = self._request('page', {'url': url}, lambda r: classify.response(r, mode='html'), 'page')
        if verdict.error:
            raise verdict.error
        return result['body']

    # --- reads, in the skill's terms ---------------------------------------------------------------------------

    def resolve(self, kind, url):
        """The numeric id of a normalized profile, group or post URL: from the URL itself, else from its page."""
        direct = {'profile': targets.direct_profile_id, 'group': targets.direct_group_id}.get(kind)
        found = direct(url) if direct else None
        if found:
            return found
        found = targets.find_id(kind, self.page(url))
        if not found:
            raise SnsError('failed', f'Could not find the {kind} id on its page.',
                           'Check the URL in the browser; it may be private, removed or misspelled.', reason='no_id')
        return found

    def feed(self, sort, cursor):
        chunks = self.query('newsfeed', {**FEED_SORTS[sort], 'cursor': cursor}, route=HOME)
        return posts_page(chunks, source='newsfeed', connection_key='news_feed', captured_at=_now())

    def timeline(self, profile_id, cursor, *, after_time, before_time, url):
        chunks = self.query('timeline', {'id': profile_id, 'cursor': cursor, 'afterTime': after_time,
                                         'beforeTime': before_time}, route=url)
        return posts_page(chunks, source='timeline', connection_key='timeline_list_feed_units', captured_at=_now())

    def group_feed(self, group_id, sort, cursor, *, url):
        chunks = self.query('group', {'id': group_id, 'sortingSetting': GROUP_SORTS[sort], 'cursor': cursor}, route=url)
        return posts_page(chunks, source='group', connection_key='group_feed', captured_at=_now())

    def permalink(self, story_id, url):
        """(the post record, response issues); the record's id is the feedback id its comments hang on."""
        chunks = self.query('post', {'storyID': story_id}, route=url)
        record, issues = permalink_post(chunks, captured_at=_now())
        if record is None:
            raise SnsError('failed', 'The post response holds no readable post.',
                           'Open the post in the browser; it may be private or removed.', reason='no_post')
        return record, issues

    def comments(self, feedback_id, sort, cursor, *, url):
        """One page of a post's parent comments, with reply handles."""
        variables = {'id': feedback_id, 'commentsIntentToken': COMMENT_SORTS[sort]}
        if cursor is None:
            chunks = self.query('comments', variables, route=url)
        else:
            chunks = self.query('comments_page', {**variables, 'commentsAfterCursor': cursor}, route=url)
        return comments_page(chunks, post_id=feedback_id, captured_at=_now())

    def replies(self, feedback_id, token, cursor, *, depth, parent_id, post_id, url):
        """One batch of replies to one comment (depth 1) or to one reply (depth 2)."""
        variables = {'id': feedback_id, 'expansionToken': token, 'repliesAfterCursor': cursor}
        chunks = self.query('replies' if depth <= 1 else 'replies_deep', variables, route=url)
        return replies_page(chunks, post_id=post_id, parent_id=parent_id, captured_at=_now(), depth=depth)

    def search(self, text, vertical, cursor, *, recent=False, since=None, until=None, group_id=None, group_url=None):
        """One page of search results; recent, since and until are Facebook's post filters; group_id searches inside
        one group the way the group's own search box does (observed: scoped callsite and experience)."""
        base = QUERIES['search']['variables']['args']
        experience = {**base['experience'], 'type': VERTICALS[vertical]}
        variables = {'cursor': cursor}
        if group_id:
            experience.update(type='GROUPS_SCOPED', fbid=group_id)
            variables['renderLocation'] = 'group_serp'
        args = {**base, 'text': text, 'experience': experience,
                'filters': search_filters(recent=recent, since=since, until=until, today=_now().date().isoformat())}
        if group_id:
            args['callsite'] = 'comet:scoped:group'
        route = (group_url.rstrip('/') + '/search/?q=' + quote(text)) if group_id else \
            HOME + 'search/' + vertical + '/?q=' + quote(text)
        chunks = self.query('search', {'args': args, **variables}, route=route)
        return search_page(chunks, vertical=vertical, captured_at=_now())

    def notifications(self, cursor):
        """One page of the viewer's notification list. route=None: a refused id is never relearned, because the screen
        that loads these queries is the notifications screen, and rendering it makes the app send the seen-state
        mutations; the command ends instead."""
        try:
            if cursor is None:
                chunks = self.query('notifications', {}, route=None)
            else:
                chunks = self.query('notifications_page', {'cursor': cursor}, route=None)
        except SnsError as error:
            if error.reason != 'stale':
                raise
            raise SnsError('failed', 'Facebook no longer accepts the stored notifications query ('
                           + error.message.rstrip('.') + '). The skill does not open the notifications screen to '
                             'relearn it, because opening that screen makes Facebook mark notifications seen.',
                           classify.STALE_FIX, reason='stale') from None
        return notifications_page(chunks, captured_at=_now())

    def about(self, profile_id, collection, *, url):
        """The decoded About response of the overview (collection None) or of one About tab."""
        token = base64.b64encode(f'app_section:{profile_id}:{ABOUT_SECTION}'.encode()).decode()
        return self.query('about', {'pageID': profile_id, 'userID': profile_id, 'sectionToken': token,
                                    'collectionToken': collection},
                          route=targets.BASE + targets.about_path(url))

    def group(self, group_id, *, url):
        """(the group's card: its header, then its About screen; response issues). Two requests."""
        chunks = self.query('group_root', {'groupID': group_id}, route=url)
        record, issues = group_card(chunks, group_id=group_id, captured_at=_now())
        if record is None:
            raise SnsError('failed', 'The group response holds no readable group header.',
                           'Open the group in the browser; it may be hidden.', reason='no_group')
        details, more = group_about(self.query('group_about', {'groupID': group_id}, route=url.rstrip('/') + '/about'))
        record.update({key: None for key in ('description', 'privacy_description', 'posts_last_day',
                                             'posts_last_month', 'created_at')}, rules=[])
        record.update(details or {})
        return record, issues + more

    # --- maintenance -----------------------------------------------------------------------------------------

    def verify(self, check):
        """The one request that may lift a person block: the tab's own account, read with one feed query inside the
        check (pacing and the deadline still hold, and nothing is retried or relearned: the answer decides). Clean
        only when Facebook answers for the account the tab is logged in to and the block was recorded for it (or for
        no known account); anything else keeps the block and says why."""
        try:
            viewer = self.start()
            self.connection.seen(viewer)
            blocked_for = (check.person or {}).get('viewer')
            if blocked_for and blocked_for != viewer:
                raise _keep_block('account_mismatch', f'it was recorded for Facebook account {blocked_for}, and the '
                                                      f'browser is logged in to {viewer}. A person should check which '
                                                      'account was blocked.')
            self.query('newsfeed', {**FEED_SORTS['top'], 'cursor': None, 'count': 1}, route=HOME)
        except SnsError as error:
            if error.reason == 'verification':
                raise
            raise _keep_block(_verification(error), error.message.rstrip('.') + '.', **{
                k: v for k, v in error.details.items() if k in ('until', 'reset', 'next_allowed_at')}) from None

    def doctor(self):
        """The Facebook-specific part of doctor: the tab and which read queries the page has loaded now."""
        live = self._modules()
        return {'tab': {'target_id': self.tab, 'opened_now': self.opened_now},
                'queries': {name: ('live in the tab' if doc else 'stored') for name, doc in sorted(live.items())}}

    def _modules(self):
        """Which read queries the tab has loaded right now; makes no request. A tab that vanished is reopened once."""
        for attempt in range(2):
            try:
                with self.guard.observe():
                    result = self.aside.evaluate(self.tab, SNIPPETS['modules'], {'names': READ_NAMES, 'fresh': False})
                return result if isinstance(result, dict) else {}
            except SnsError as error:
                if error.reason != 'tab_missing' or attempt or self.reopens >= REOPEN_LIMIT:
                    raise
                self.reopens += 1
                self._reopen()
        return {}
