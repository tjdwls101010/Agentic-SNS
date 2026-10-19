"""feed, profile, graph, me, list and community posts: lists read by cursor in the server's order, with each
surface's date-window policy (twitter.window).
"""
from twitter import connect
from twitter.errors import TwitterError
from twitter.paging import paginate
from twitter.window import Window
from twitter.x_web import parse_account

# Both home feeds are X's choice of order: the following feed is not newest first (P2 R8), so neither closes a window.
FEEDS = {'foryou': ('foryou', 'unordered'), 'following': ('following', 'unordered')}


def feed(options):
    name = options.get('feed') or 'foryou'
    variant, order = FEEDS[name]
    identity = {'feed': name, 'since': options.get('since'), 'until': options.get('until')}

    def read(connection, state, out):
        return _read(options, identity, state, out, order=order, command='feed', target=None,
                     fetch=lambda cursor: connection.client.feed(variant, cursor))

    return connect.run(options, command='feed', target=None, identity=identity, reader=read,
                       window=_window(options, order))


# tab → (operation, date order). posts is UserTweets: posts and reposts, newest first (X's own Posts tab now hides
# reposts, X14); media is UserMedia: photos, videos and GIFs (X's own Media tab now shows videos only).
TABS = {'posts': ('UserTweets', 'newest_first'), 'replies': ('UserRepliesTimeline', 'newest_first'),
        'media': ('UserMedia', 'finite'), 'highlights': ('UserHighlightsTweets', 'finite'),
        'articles': ('UserArticlesTweets', 'finite')}


def profile(options):
    target = parse_account(options['target'])
    tab = options.get('tab')
    if tab and target.tab and tab != target.tab:
        raise TwitterError(2, f'The URL is the {target.tab} tab but --tab asks for {tab}.', 'Give one of them.')
    tab = tab or target.tab or 'posts'
    if tab not in TABS:
        raise TwitterError(2, f'The {tab} tab is not a list of posts.', 'Use --tab posts, replies, media, highlights or '
                                                                        'articles.')
    operation, order = TABS[tab]
    identity = {'tab': tab, 'since': options.get('since'), 'until': options.get('until')}

    def read(connection, state, out):
        client = connection.client
        saved = (state or {}) if out is None else (out.state or {})
        user_id, card = saved.get('user_id'), None
        if not user_id:
            card = client.user(target.handle)
            user_id = card['id']
        reading = _read(options, identity, state, out, order=order, command='profile', target=target.url,
                        extra={'user_id': user_id},
                        fetch=lambda cursor: client.timeline(operation, {'userId': user_id}, cursor))
        if card is not None and not reading['results'] and not reading.get('failure') and \
                not reading.get('continuation') and (out is None or not out.count):
            if card.get('private') and (card.get('relationship') or {}).get('following') is not True:
                reading['failure'] = TwitterError(9, f'@{target.handle} is protected and this account does not follow '
                                                     'it.', 'Tell the user; only approved followers can read it.',
                                                  reason='unavailable')
        return reading

    return connect.run(options, command='profile', target=target.url, identity=identity, reader=read,
                       window=_window(options, order))


def _read(options, identity, state, out, *, order, fetch, command, target, extra=None, words=None, stops=False,
          idle_limit=2):
    start = dict(out.state or {}) if out is not None else dict(state or {})
    window = Window(options.get('since'), options.get('until'), order, start.pop('window', None))
    for key in (extra or {}):
        start.pop(key, None)
    natural = start.pop('natural', None) or {}
    skipped = {'promoted': 0, 'other': 0}

    def fetch_page(cursor):
        page = fetch(cursor)
        skipped['promoted'] += page.promoted
        skipped['other'] += page.other
        if getattr(page, 'stop', None):
            natural['stop'] = page.stop
        return page.records, {'has_next_page': page.has_next, 'end_cursor': page.cursor}, bool(page.records)

    def commit(records, page_state, reason, page_skipped):
        out.commit(records, {**page_state, 'window': window.state(), 'natural': dict(natural), **(extra or {})}
                   if page_state else None, reason, page_skipped, window.report())

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
                      max_pages=1 if one_page else None, idle_limit=idle_limit)
    stop = result['stop_reason']
    if stops and stop == 'exhausted' and natural.get('stop') == 'not_paginable':
        stop = 'not_paginable'
    coverage = window.report()
    if skipped['promoted']:
        coverage.append(f'{skipped["promoted"]} promoted posts (ads) left out')
    reading = {'results': [] if out is not None else result['results'], 'stop_reason': stop,
               'failure': result['failure'], 'coverage': coverage, 'words': _words(identity, words),
               'partial': bool(result['results'])}
    if result['state'] is not None:
        reading['continuation'] = {'command': command, 'target': target, 'identity': identity,
                                   'words': _words(identity, words),
                                   'state': {**result['state'], 'window': window.state(), 'natural': dict(natural),
                                             **(extra or {})}}
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
