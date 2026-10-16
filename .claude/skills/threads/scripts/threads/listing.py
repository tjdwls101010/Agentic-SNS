"""feed, profile, graph and me: lists read by cursor in the server's order, with each surface's date-window policy.

A window keeps the dated posts written on its local days; a post without a date cannot be placed and is left out and
counted (a tombstone is not counted). Only a newest-first surface (the following feed, a profile's threads and replies
tabs) can prove it passed --since: a page closes the window when every unit on it is older than --since, pinned units
aside, provided every unit so far came newest first by its newest post — once the order breaks, nothing closes it. A
finite list in no date order (reposts, media) covers the window only when read to the end; a ranked feed never does.
"""
from datetime import date, datetime

from threads import connect
from threads.errors import ThreadsError
from threads.paging import paginate
from threads.threads_web import parse_user

FEEDS = {'foryou': ('for_you', 'unordered'), 'following': ('following', 'newest_first')}
TABS = {'threads': 'newest_first', 'replies': 'newest_first', 'reposts': 'finite', 'media': 'finite'}


def _local_day(stamp):
    return datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone().date()


class Window:
    """The date-window policy of one read, with the state a continuation carries."""

    def __init__(self, since, until, order, state=None):
        self.since = date.fromisoformat(since) if since else None
        self.until = date.fromisoformat(until) if until else None
        self.order = order
        state = state or {}
        self.last = state.get('last')                  # the newest-post time of the last unit seen, ISO
        self.unordered = bool(state.get('unordered'))
        self.undated = list(state.get('undated') or [])

    @property
    def active(self):
        return self.since is not None or self.until is not None

    def state(self):
        return {'last': self.last, 'unordered': self.unordered, 'undated': self.undated}

    def keep(self, record):
        if not self.active:
            return True
        if record.get('unavailable'):
            return False
        if not record.get('created_at'):
            if record.get('id') not in self.undated:
                self.undated.append(record.get('id'))
            return False
        day = _local_day(record['created_at'])
        return (self.since is None or day >= self.since) and (self.until is None or day <= self.until)

    def closes(self, records):
        """Whether this newest-first page proves the window's start was passed (see the module docstring)."""
        units = {}
        for record in records:
            units.setdefault(record.get('unit') or record.get('id'), []).append(record)
        times = []
        for unit in units.values():
            if any(r.get('is_pinned') for r in unit):
                continue
            stamps = [r.get('created_at') for r in unit if not r.get('unavailable')]
            if not stamps or any(s is None for s in stamps):
                self.unordered = True
                continue
            times.append(max(datetime.fromisoformat(s.replace('Z', '+00:00')) for s in stamps))
        previous = datetime.fromisoformat(self.last) if self.last else None
        if any(a < b for a, b in zip(times, times[1:])) or (previous and times and times[0] > previous):
            self.unordered = True
        if times:
            self.last = times[-1].isoformat()
        return (self.since is not None and bool(times) and not self.unordered
                and max(times).astimezone().date() < self.since)

    def report(self):
        notes = []
        if self.undated:
            notes.append(f'{len(self.undated)} undated post{"s" if len(self.undated) > 1 else ""} left out: no date '
                         'places them in the window')
        if self.order == 'newest_first' and self.unordered and self.since:
            notes.append('this surface did not come newest first here, so reading on cannot prove --since was passed')
        return notes


def feed(options):
    name = options.get('feed') or 'foryou'
    variant, order = FEEDS[name]
    identity = {'feed': name, 'since': options.get('since'), 'until': options.get('until')}

    def read(connection, state, out):
        return _read(options, identity, state, out, order=order, command='feed', target=None,
                     fetch=lambda cursor: connection.client.feed(variant, cursor))

    return connect.run(options, command='feed', target=None, identity=identity, reader=read,
                       window=_window(options, order))


def profile(options):
    target = parse_user(options['target'])
    tab = options.get('tab')
    if tab and target.tab and tab != target.tab:
        raise ThreadsError(2, f'The URL is the {target.tab} tab but --tab asks for {tab}.', 'Give one of them.')
    tab = tab or target.tab or 'threads'
    order = TABS[tab]
    identity = {'tab': tab, 'since': options.get('since'), 'until': options.get('until')}

    def read(connection, state, out):
        client = connection.client
        saved = (state or {}) if out is None else (out.state or {})
        user_id = saved.get('user_id')
        user = None
        if not user_id:
            user_id, user = client.profile_id(target.username)
        extra = {'user_id': user_id}
        reading = _read(options, identity, state, out, order=order, command='profile', target=target.url, extra=extra,
                        fetch=lambda cursor: client.profile_tab(tab, user_id, target.username, cursor))
        if user is not None and not reading['results'] and not reading.get('failure') and not reading.get('continuation') \
                and (out is None or not out.count):
            friendship = user.get('friendship_status') if isinstance(user.get('friendship_status'), dict) else {}
            if user.get('text_post_app_is_private') and friendship.get('following') is False:
                reading['failure'] = ThreadsError(9, f'@{target.username} is private and this account does not follow '
                                                     'it.', 'Tell the user; only accepted followers can read it.',
                                                  reason='unavailable')
        return reading

    return connect.run(options, command='profile', target=target.url, identity=identity, reader=read,
                       window=_window(options, order))


def _read(options, identity, state, out, *, order, fetch, command, target, extra=None):
    start = dict(out.state or {}) if out is not None else dict(state or {})
    window = Window(options.get('since'), options.get('until'), order, start.pop('window', None))
    for key in (extra or {}):
        start.pop(key, None)

    def fetch_page(cursor):
        page = fetch(cursor)
        return page.records, {'has_next_page': page.has_next, 'end_cursor': page.cursor}, bool(page.records)

    def commit(records, page_state, reason, skipped):
        out.commit(records, {**page_state, 'window': window.state(), **(extra or {})} if page_state else None, reason,
                   skipped, window.report())

    if out is not None:
        start.update(seen=sorted(out.ids, key=str), pending=[])
    limit = options.get('limit')
    if out is not None and limit is not None:
        if out.count >= limit:
            return {'results': [], 'stop_reason': 'limit_reached', 'words': _words(identity)}
        limit -= out.count
    closes = window.closes if order == 'newest_first' and window.since else None
    # Without --limit, a window or --out, one page is read: a glance at a list costs one request, not the budget.
    one_page = limit is None and out is None and not window.active
    result = paginate(fetch_page, limit=limit, state=start, keep=window.keep, closes=closes,
                      commit=commit if out is not None else None, whole_pages=out is not None,
                      max_pages=1 if one_page else None)
    reading = {'results': [] if out is not None else result['results'], 'stop_reason': result['stop_reason'],
               'failure': result['failure'], 'coverage': window.report(), 'words': _words(identity),
               'partial': bool(result['results'])}
    if result['state'] is not None:
        reading['continuation'] = {'command': command, 'target': target, 'identity': identity,
                                   'words': _words(identity),
                                   'state': {**result['state'], 'window': window.state(), **(extra or {})}}
    return reading


def _words(identity):
    words = []
    for key in ('feed', 'tab', 'sort'):
        if identity.get(key):
            words += ['--' + key, identity[key]]
    for key in ('since', 'until'):
        if identity.get(key):
            words += ['--' + key, identity[key]]
    return words


def _window(options, order):
    if not (options.get('since') or options.get('until')):
        return None
    return {'order': order, 'since': options.get('since'), 'until': options.get('until')}
