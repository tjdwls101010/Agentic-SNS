"""The Facebook web client: requests made from the skill's own facebook.com tab, the way the page makes them.

The tab is opened once (`aside <url>`) and reused; each read is one GraphQL request sent with the page's own request
parameters. Query ids and provider flags come from the page's loaded modules when it has them, else from what an
earlier read learned, else from the bundled snapshot. When Facebook no longer accepts a stored query, the tab is moved
to the screen that loads that query (as a person would open it) and the read is retried once with the live id.
"""
import base64
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

from facebook.errors import FacebookError, diagnostic
from facebook.graphql import classify, targets
from facebook.graphql.records import (about_collections, about_fields, comments_page, group_card, permalink_post,
                                     posts_page, replies_page, search_page)
from facebook.graphql.records.search import VERTICALS
from facebook.graphql.records.search import filters as search_filters

HOME = 'https://www.facebook.com/'
# What the page itself loads cannot be bounded or attributed exactly, so the actions whose size the page decides are
# prepaid: opening the dedicated tab measured 30 facebook.com requests, moving it to another screen 6-9. Requests the
# page finishes after the call that caused them are counted against what is left of these reservations first.
OPEN_RESERVE = 30
ROUTE_RESERVE = 10
SNIPPETS = {path.stem: path.read_text(encoding='utf-8')
            for path in (Path(__file__).parent / 'snippets').glob('*.js')}
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
        self.prepaid = {'setup': 0, 'budget': 0}  # reserved but not yet seen: requests the page may still finish

    # --- the tab ---------------------------------------------------------------------------------------------

    def start(self):
        """Find or open the dedicated tab and check it is a logged-in Facebook page; returns the account id."""
        known = self.memory.tab
        if known and any(t['target_id'] == known and _usable(t['url']) for t in self.browser.tabs()):
            self.tab = known
            with self.guard.observe() as slot:  # what the tab shows and the block it implies, in one critical section
                state = self._state()
                self._check_state(state, slot)
        else:
            self._open()
        return self.account_id

    def _state(self, fresh=False):
        state = self.browser.evaluate(self.tab, SNIPPETS['state'], {'fresh': fresh})
        if not isinstance(state, dict) or not isinstance(state.get('location'), str):
            raise FacebookError(3, 'The Facebook tab answered invalidly.', 'Run doctor.')
        return state

    def _open(self):
        """Open a new dedicated tab: counted as requests (its document and what the page loads), outside the budget."""
        before = {t['target_id'] for t in self.browser.tabs()}
        with self.guard.request(reserve=OPEN_RESERVE, budgeted=False) as slot:
            self.browser.open(HOME)
            new = [t for t in self.browser.tabs() if t['target_id'] not in before and _facebook(t['url'])]
            if not new:
                raise FacebookError(3, 'Aside did not open the Facebook tab.', 'Check Aside, then run doctor.')
            self.tab = new[-1]['target_id']
            self.memory.set_tab(self.tab)
            self.opened_now = True
            state = self._state(fresh=True)
            seen = 1 + _int(state.get('resources'))
            slot.charge(seen)
            self.prepaid['setup'] = max(0, OPEN_RESERVE - seen)
            self._check_state(state, slot)
        return state

    def _check_state(self, state, slot):
        """Raise for a checkpoint or a rate limit among the tab's requests (recorded in `slot` first), a logout, a
        broken page, or another account."""
        verdict = _rate_limited(state, classify.location(state['location'], state.get('user_id')))
        if verdict.block:
            slot.block(verdict.block)
        if verdict.error:
            raise verdict.error
        if not state.get('runtime'):
            raise FacebookError(3, 'The Facebook tab is not a working Facebook page.', 'Run doctor; close the tab if '
                                                                                         'it keeps failing.')
        if self.account_id is not None and state['user_id'] != self.account_id:
            raise FacebookError(4, 'The Aside browser is now logged in to a different Facebook account than when '
                                   'this command started.', 'Check which account Aside is logged in to, then rerun '
                                                            'the command.', reason='account_changed')
        self.account_id = state['user_id']

    def _evaluate(self, snippet, args):
        """Run a page function in the tab; a tab that vanished is reopened once."""
        try:
            with self.guard.observe():
                return self.browser.evaluate(self.tab, SNIPPETS[snippet], args)
        except FacebookError as error:
            if error.reason != 'tab_missing':
                raise
        self._open()
        with self.guard.observe():
            return self.browser.evaluate(self.tab, SNIPPETS[snippet], args)

    # --- requests --------------------------------------------------------------------------------------------

    def _request(self, snippet, args, verdict_of, label, reserve=1):
        """One guarded request: block check, budget and pacing; the response classified before the lock is released.

        A 429 among the facebook.com requests the page made meanwhile is a rate limit like one of ours."""
        for attempt in range(2):
            try:
                with self.guard.request(reserve=reserve) as slot:
                    try:
                        result = self.browser.evaluate(self.tab, SNIPPETS[snippet], args)
                    except FacebookError as error:
                        if error.reason == 'tab_missing':
                            slot.cancel()  # the program never reached a page, so nothing went to Facebook
                        raise
                    if not isinstance(result, dict):
                        raise FacebookError(3, 'The Facebook tab answered invalidly.', 'Run doctor.')
                    if result.get('stopped'):
                        slot.cancel()  # the tab already showed a rate limit, so nothing was sent
                    else:
                        self._charge(slot, result, reserve)
                    if self.verbose:
                        diagnostic('request', snippet=snippet, label=label, count=self.guard.count,
                                   status=result.get('status'), source=(result.get('used') or {}).get('source'))
                    if result.get('refused'):
                        raise FacebookError(2, 'The browser refused a request this skill must not make.',
                                            'Report this as a skill bug.')
                    if result.get('network_error'):
                        verdict = _rate_limited(result, classify.Verdict('failed', error=FacebookError(
                            6, 'The request to Facebook did not complete.', 'Retry later; run doctor if it keeps '
                                                                            'failing.')))
                    else:
                        verdict = _rate_limited(result, verdict_of(result))
                    if verdict.block:
                        slot.block(verdict.block)
                    if result.get('network_error'):
                        raise verdict.error
                    return result, verdict
            except FacebookError as error:
                if error.reason != 'tab_missing' or attempt:
                    raise
            self._open()
        raise AssertionError('unreachable')

    def _charge(self, slot, result, reserve):
        """Charge what the call sent and what the tab finished meanwhile; late requests use up a reservation first."""
        explicit, seen = _int(result.get('explicit'), 1), _int(result.get('resources'))
        if reserve > 1:  # a navigation: prepaid, charged in full when the page loaded more
            slot.charge(max(reserve, seen))
            self.prepaid['budget'] += max(0, reserve - seen)
            return
        extra = max(0, seen - explicit)
        for bucket in ('setup', 'budget'):
            used = min(extra, self.prepaid[bucket])
            self.prepaid[bucket] -= used
            extra -= used
        slot.charge(explicit + extra)

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
        return verdict.chunks

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
        if self.guard.remaining < ROUTE_RESERVE:
            raise FacebookError(8, f'Facebook no longer accepts the stored {name}; loading the current one needs '
                                   f'about {ROUTE_RESERVE} more requests than the budget has left.',
                                'Rerun with a larger --max-requests.', reason='budget')
        result, verdict = self._request('route', {'path': relative, 'names': [name]},
                                        lambda r: classify.location(r.get('location'), r.get('user_id')), 'route',
                                        reserve=ROUTE_RESERVE)
        if verdict.error:
            raise verdict.error
        live = (result.get('live') or {}).get(name)
        if not live:
            raise FacebookError(6, f'Facebook no longer accepts the stored {name} and the page did not provide a '
                                   'current one.', classify.STALE_FIX, reason='stale')
        self.memory.learn(name, live['doc_id'], live.get('flags'))

    # --- reads, in the skill's terms ---------------------------------------------------------------------------

    def resolve(self, kind, url):
        """The numeric id of a normalized profile, group or post URL: from the URL itself, else from its page."""
        direct = {'profile': targets.direct_profile_id, 'group': targets.direct_group_id}.get(kind)
        found = direct(url) if direct else None
        if found:
            return found
        found = targets.find_id(kind, self.page(url))
        if not found:
            raise FacebookError(6, f'Could not find the {kind} id on its page.', 'Check the URL in the browser; it may '
                                                                                 'be private, removed or misspelled.')
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
            raise FacebookError(6, 'The post response holds no readable post.', 'Open the post in the browser; it may '
                                                                                'be private or removed.')
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
        return replies_page(chunks, post_id=post_id, parent_id=parent_id, captured_at=_now())

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

    def about(self, profile_id, collection, *, url):
        """The decoded About response of the overview (collection None) or of one About tab."""
        token = base64.b64encode(f'app_section:{profile_id}:{ABOUT_SECTION}'.encode()).decode()
        return self.query('about', {'pageID': profile_id, 'userID': profile_id, 'sectionToken': token,
                                    'collectionToken': collection}, route=url.rstrip('/') + '/about')

    def group(self, group_id, *, url):
        """(the group's card from its header, response issues)."""
        chunks = self.query('group_root', {'groupID': group_id}, route=url)
        record, issues = group_card(chunks, group_id=group_id, captured_at=_now())
        if record is None:
            raise FacebookError(6, 'The group response holds no readable group header.', 'Open the group in the '
                                                                                         'browser; it may be hidden.')
        return record, issues

    def live_queries(self):
        """Which read queries the tab has loaded right now (doctor); makes no request."""
        result = self._evaluate('modules', {'names': READ_NAMES})
        return result if isinstance(result, dict) else {}


def _rate_limited(result, verdict):
    """A 429 on any of the tab's requests is a rate limit, unless the verdict is already a checkpoint (which lasts)."""
    statuses = list(result.get('statuses') or []) + list(result.get('unwatched') or [])
    if verdict.block == 'checkpoint' or (429 not in statuses and result.get('stopped') != 'rate_limit'
                                         and not result.get('limited')):
        return verdict
    return classify.Verdict('blocked', error=FacebookError(
        5, 'Facebook rate-limited this account; requests are blocked for 30 minutes.',
        'Stop requests and retry after the block expires; check Facebook first.', reason='rate_limit'),
        block='rate_limit')


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
