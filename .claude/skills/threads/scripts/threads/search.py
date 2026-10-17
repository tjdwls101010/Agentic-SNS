"""search: posts, tags and accounts, in Threads' order for this account.

Dates and an author narrow posts and tags on Threads' side (power_search_info, as the app's search filters send them):
a day is the account's local day, the start of --since and the end of --until as local midnights, so a read to the end
covers the window whatever the order; the local-day check stays as a guard.
"""
from datetime import date, datetime, time, timedelta

from threads import connect
from threads.paging import paginate
from threads.threads_web import parse_user
from threads.window import Window


def search(options):
    text, kind = options['target'], options['type']
    accounts = kind == 'accounts'
    author = parse_user(options['from']).username if options.get('from') else None
    identity = {'type': kind, 'sort': None if accounts else options['sort'], 'since': options.get('since'),
                'until': options.get('until'), 'from': author}
    filters = _filters(identity)

    def read(connection, state, out):
        client = connection.client
        if accounts:
            fetch = lambda cursor: client.search_accounts(text)  # noqa: E731 — one batch
        else:
            fetch = lambda cursor: client.search_posts(text, recent=identity['sort'] == 'recent',  # noqa: E731
                                                       tag=kind == 'tags', cursor=cursor, filters=filters)
        return _read(options, identity, state, out, fetch=fetch, text=text)

    window = None
    if identity['since'] or identity['until']:
        window = {'order': 'server', 'since': identity['since'], 'until': identity['until']}
    return connect.run(options, command='search', target=text, identity=identity, reader=read, window=window)


def _filters(identity):
    """power_search_info for the dates and author asked for, or None."""
    found = {}
    if identity['from']:
        found['author_username'] = identity['from']
    if identity['since']:
        found['lookback_min_unixtime'] = _midnight(date.fromisoformat(identity['since']))
    if identity['until']:
        found['lookback_max_unixtime'] = _midnight(date.fromisoformat(identity['until']) + timedelta(days=1))
    return found or None


def _midnight(day):
    return int(datetime.combine(day, time()).astimezone().timestamp())


def _read(options, identity, state, out, *, fetch, text):
    start = dict(out.state or {}) if out is not None else dict(state or {})
    window = Window(identity['since'], identity['until'], 'server', start.pop('window', None))
    natural = start.pop('natural', None) or {}  # what the list said, kept for a continuation that reads only its tail

    def fetch_page(cursor):
        page = fetch(cursor)
        natural['stop'] = page.stop
        return page.records, {'has_next_page': page.has_next, 'end_cursor': page.cursor}, bool(page.records)

    def commit(records, page_state, reason, skipped):
        out.commit(records, {**page_state, 'window': window.state(), 'natural': dict(natural)} if page_state else None,
                   reason, skipped, window.report())

    limit = options.get('limit')
    if out is not None:
        start.update(seen=sorted(out.ids, key=str), pending=[])
        if limit is not None:
            if out.count >= limit:
                return {'results': [], 'stop_reason': 'limit_reached', 'words': _words(identity)}
            limit -= out.count
    one_page = limit is None and out is None and not window.active  # a dated search reads to the end, as lists do
    result = paginate(fetch_page, limit=limit, state=start, keep=window.keep,
                      commit=commit if out is not None else None, whole_pages=out is not None,
                      max_pages=1 if one_page else None)
    stop = result['stop_reason']
    if stop == 'exhausted' and natural.get('stop') == 'not_paginable':
        stop = 'not_paginable'
    reading = {'results': [] if out is not None else result['results'], 'stop_reason': stop,
               'failure': result['failure'], 'coverage': window.report(), 'words': _words(identity),
               'partial': bool(result['results'])}
    if result['state'] is not None:
        reading['continuation'] = {'command': 'search', 'target': text, 'identity': identity,
                                   'words': _words(identity), 'state': {**result['state'], 'window': window.state(),
                                                                       'natural': dict(natural)}}
    return reading


def _words(identity):
    words = ['--type', identity['type']]
    for key in ('sort', 'since', 'until', 'from'):
        if identity.get(key):
            words += ['--' + key, identity[key]]
    return words
