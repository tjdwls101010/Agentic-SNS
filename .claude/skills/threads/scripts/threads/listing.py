"""feed, profile, graph and me: lists read by cursor in the server's order, with each surface's date-window policy
(threads.window).
"""
from threads import connect
from threads.errors import ThreadsError
from threads.paging import paginate
from threads.threads_web import parse_post, parse_user
from threads.window import Window

FEEDS = {'foryou': ('for_you', 'unordered'), 'following': ('following', 'newest_first')}
TABS = {'threads': 'newest_first', 'replies': 'newest_first', 'reposts': 'finite', 'media': 'finite'}


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


def graph(options):
    target = parse_user(options['target'])
    relation = options['relation']
    identity = {'relation': relation}

    def read(connection, state, out):
        client = connection.client
        saved = (state or {}) if out is None else (out.state or {})
        user_id = saved.get('user_id') or client.profile_id(target.username)[0]
        totals = {}

        def fetch(cursor):
            page = client.relation(relation, user_id, target.username, cursor)
            if page.reported_total is not None:
                totals['reported'] = page.reported_total
            return page
        reading = _read(options, identity, state, out, order=None, command='graph', target=target.url,
                        extra={'user_id': user_id}, fetch=fetch, words=[relation], stops=True)
        if 'reported' in totals:
            reading['details'] = {'reported_total': totals['reported']}
        return reading

    return connect.run(options, command='graph', target=target.url, identity=identity, reader=read)


def activity(options):
    """quotes or reposts of one post: the batch Threads sends, with the count it reports."""
    target = parse_post(options['target'])
    tab = {'quotes': 'quote', 'reposts': 'repost'}[options['command']]

    def read(connection, state, out):
        totals = {}

        def fetch(cursor):
            page = connection.client.activity(target, tab)
            totals['reported'] = page.reported_total
            return page
        reading = _read(options, {}, state, out, order=None, command=options['command'], target=target.url,
                        fetch=fetch, stops=True)
        if totals.get('reported') is not None:
            reading['details'] = {'reported_total': totals['reported']}
        return reading

    return connect.run(options, command=options['command'], target=target.url, identity={}, reader=read)


def me(options):
    collection = options['collection']
    identity = {'collection': collection}

    def read(connection, state, out):
        return _read(options, identity, state, out, order=None, command='me', target=None, words=[collection],
                     fetch=lambda cursor: connection.client.mine(collection), stops=True)

    return connect.run(options, command='me', target=None, identity=identity, reader=read)


def _read(options, identity, state, out, *, order, fetch, command, target, extra=None, words=None, stops=False):
    start = dict(out.state or {}) if out is not None else dict(state or {})
    window = Window(options.get('since'), options.get('until'), order, start.pop('window', None))
    for key in (extra or {}):
        start.pop(key, None)

    natural = {}

    def fetch_page(cursor):
        page = fetch(cursor)
        natural['stop'] = page.stop  # server_capped or not_paginable when the list itself says so
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
    stop = result['stop_reason']
    if stops and stop == 'exhausted' and natural.get('stop') in ('server_capped', 'not_paginable'):
        stop = natural['stop']
    reading = {'results': [] if out is not None else result['results'], 'stop_reason': stop,
               'failure': result['failure'], 'coverage': window.report(), 'words': _words(identity, words),
               'partial': bool(result['results'])}
    if result['state'] is not None:
        reading['continuation'] = {'command': command, 'target': target, 'identity': identity,
                                   'words': _words(identity, words),
                                   'state': {**result['state'], 'window': window.state(), **(extra or {})}}
    return reading


def _words(identity, positional=None):
    words = list(positional or [])
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
