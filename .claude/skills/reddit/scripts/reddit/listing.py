"""feed, sub, profile, me and related: listings read page by page in Reddit's order.

A page asks for 100 records and shows --limit of them (25 by default); the rest wait in the handle, so the next more:
shows them with no request. A date window is only for sort new (a timeline); it keeps the records of its local days and
closes when a page is wholly older than --since, pinned posts aside.
"""
from reddit import connect
from reddit.errors import RedditError
from reddit.paging import paginate
from reddit.reddit_web import FEED_SORTS, SUB_SORTS, TIMES, parse_target, require, routes
from reddit.window import Window

DISPLAY = 25


def feed(options):
    sort = options.get('sort') or 'best'
    identity = {'sort': sort, 'time': options.get('time'), 'since': options.get('since'), 'until': options.get('until')}

    def read(connection, state, out):
        return _read(connection, options, identity, state, out, command='feed', target=None,
                     request=lambda after: routes.feed(sort, options.get('time'), after))

    return connect.run(options, command='feed', target=None, identity=identity, reader=read)


def sub(options):
    target = require(parse_target(options['target']), ('subreddit', 'subreddits'), 'sub')
    sort = options.get('sort') or 'hot'
    identity = {'sort': sort, 'time': options.get('time'), 'since': options.get('since'), 'until': options.get('until')}

    def read(connection, state, out):
        return _read(connection, options, identity, state, out, command='sub', target=target.name,
                     request=lambda after: routes.listing(target.sub, sort, options.get('time'), after))

    return connect.run(options, command='sub', target=target.name, identity=identity, reader=read)


def _read(connection, options, identity, state, out, *, request, command, target, words=None, extra=None):
    """Read pages until the limit, the window, the end or a failure; returns a reading for connect.run."""
    start = dict(out.state or {}) if out is not None else dict(state or {})
    window = Window(options.get('since'), options.get('until'), start.pop('window', None))
    for key in (extra or {}):
        start.pop(key, None)

    def fetch(cursor):
        records, after = connection.network().listing(request(cursor))
        return records, {'has_next_page': after is not None, 'end_cursor': after}, bool(records)

    def commit(records, page_state, reason, skipped):
        out.commit(records, {**page_state, 'window': window.state(), **(extra or {})} if page_state else None, reason,
                   skipped, window.report())

    if out is not None:
        start.update(seen=sorted(out.ids, key=str), pending=[])
    limit = options.get('limit') or (None if out is not None else DISPLAY)
    if out is not None and options.get('limit') is not None:
        if out.count >= options['limit']:
            return {'results': [], 'stop_reason': 'limit_reached', 'words': _words(identity, words)}
        limit -= out.count
    closes = window.closes if window.active and window.bounds['start'] is not None else None
    result = paginate(fetch, limit=limit, state=start, keep=window.keep, closes=closes,
                      commit=commit if out is not None else None, whole_pages=out is not None)
    stop, failure = result['stop_reason'], result['failure']
    if stop == 'exhausted' and window.bounds['start'] is not None:
        failure = RedditError(8, 'The listing ended before the window\'s start: Reddit had no older posts to show '
                                 'here, so the window is not covered.', 'Use a later --since, or search with --sort '
                                                                        'new instead of reading the listing.',
                              reason='listing_ended')
    reading = {'results': [] if out is not None else result['results'], 'stop_reason': stop, 'failure': failure,
               'coverage': window.report(), 'words': _words(identity, words), 'partial': bool(result['results'])}
    if window.active:
        reading['window'] = window.describe()
    if not result['results'] and failure is None and result['state'] is None and out is None and not window.active:
        reading['failure'] = RedditError(7, 'Reddit returned nothing here.', 'Try another target, order or period.')
    if result['state'] is not None:
        reading['continuation'] = {'command': command, 'target': target, 'identity': identity,
                                   'words': _words(identity, words),
                                   'state': {**result['state'], 'window': window.state(), **(extra or {})}}
    return reading


def _words(identity, positional=None):
    words = list(positional or [])
    for key in ('type', 'sort', 'time', 'since', 'until'):
        if identity.get(key):
            words += ['--' + key, identity[key]]
    return words


__all__ = ['FEED_SORTS', 'SUB_SORTS', 'TIMES', 'feed', 'sub']
