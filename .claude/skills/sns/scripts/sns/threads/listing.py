"""feed, profile, graph, me, quotes and reposts: lists read by cursor in Threads' order, with each surface's date-window
policy (sns.window). `surface` is the one place a Threads page becomes a reading page and the one place a surface's own
end (Threads' sample, its single batch) is remembered across a continuation."""
from sns import reading
from sns.errors import SnsError
from sns.page import Page
from sns.threads import web
from sns.window import Window

FEEDS = {'foryou': ('for_you', 'ranked'), 'following': ('following', 'newest_first')}
TABS = {'threads': 'newest_first', 'replies': 'newest_first', 'reposts': 'finite', 'media': 'finite'}
# A surface's own end, which a continuation that reads only the tail it already holds must still report
NATURAL_STOPS = ('server_capped', 'not_paginable')


def paged(listed):
    """The reading Page of one page of records (web.Page)."""
    return Page(listed.records, next=listed.cursor if listed.has_next else None, end=not listed.has_next,
                stop=listed.stop, reported_total=listed.reported_total)


def surface(connection, state, out, *, fetch, order, command, target, identity, words=(), extra=None, idle_limit=2,
            end_covers_window=False):
    """Read a Threads surface (fetch(cursor) → a web.Page) as reading.read_list does. What the surface itself said (it
    is a sample, it is one batch, the total it reports) travels in the continuation and the --out file's state."""
    saved = (out.state if out is not None else state) or {}
    natural = dict(saved.get('natural') or {})

    def fetch_page(cursor):
        page = fetch(cursor)
        if page.stop:
            natural['stop'] = page.stop
        if page.reported_total is not None:
            natural['reported'] = page.reported_total
        return paged(page)

    result = reading.read_list(connection, state, out, order=order, command=command, target=target, identity=identity,
                               words=words, extra={**(extra or {}), 'natural': natural}, idle_limit=idle_limit,
                               end_covers_window=end_covers_window, fetch=fetch_page)
    if result['stop_reason'] == 'exhausted' and natural.get('stop') in NATURAL_STOPS and not result.get('failure'):
        result['stop_reason'] = natural['stop']
    reported = natural.get('reported')
    if reported is not None:
        result['details'] = {'reported_total': reported}
        note = f'{connection.platform.title} reports {reported} in total'
        if result.get('reported_total') is None and note not in (result.get('coverage') or []):
            result['coverage'] = [*(result.get('coverage') or []), note]
    return result


def flags(identity, keys=('feed', 'tab', 'sort')):
    """The option words that rerun a command with this identity."""
    words = []
    for key in keys:
        if identity.get(key):
            words += ['--' + key, identity[key]]
    return words


def window_of(platform, options, order):
    """The date window a result names even when the read failed before it began (None: no --since/--until)."""
    if not (options.get('since') or options.get('until')):
        return None
    return Window(options.get('since'), options.get('until'), order=order, policy=platform.window).describe()


def feed(platform, invocation):
    options = invocation.options
    name = options.get('feed') or 'foryou'
    variant, order = FEEDS[name]
    identity = {'feed': name}

    def read(connection, state, out):
        return surface(connection, state, out, order=order, command='feed', target=None, identity=identity,
                       words=flags(identity), end_covers_window=name == 'following',
                       fetch=lambda cursor: connection.client.feed(variant, cursor))

    # neither feed ends by itself, so --out needs --limit
    return reading.run(platform, invocation, command='feed', target=None, identity=identity, reader=read, endless=True,
                       window=window_of(platform, options, order))


def profile(platform, invocation):
    options = invocation.options
    target = web.parse_user(options['target'])
    tab = options.get('tab')
    if tab and target.tab and tab != target.tab:
        raise SnsError('argument', f'The URL is the {target.tab} tab but --tab asks for {tab}.', 'Give one of them.')
    tab = tab or target.tab or 'threads'
    order = TABS[tab]
    identity = {'tab': tab}

    def read(connection, state, out):
        client = connection.client
        saved = (state or {}) if out is None else (out.state or {})
        user_id, user = saved.get('user_id'), None
        if not user_id:
            user_id, user = client.profile_id(target.username)
        result = surface(connection, state, out, order=order, command='profile', target=target.url, identity=identity,
                         words=flags(identity), extra={'user_id': user_id}, end_covers_window=True,
                         fetch=lambda cursor: client.profile_tab(tab, user_id, target.username, cursor))
        if user is not None and not result['results'] and not result.get('failure') and \
                not result.get('continuation') and (out is None or not out.count):
            friendship = user.get('friendship_status') if isinstance(user.get('friendship_status'), dict) else {}
            if user.get('text_post_app_is_private') and friendship.get('following') is False:
                result['failure'] = SnsError('unavailable', f'@{target.username} is private and this account does not '
                                                            'follow it.', 'Tell the user; only accepted followers can '
                                                                          'read it.', reason='unavailable')
        return result

    return reading.run(platform, invocation, command='profile', target=target.url, identity=identity, reader=read,
                       window=window_of(platform, options, order))


def graph(platform, invocation):
    options = invocation.options
    target = web.parse_user(options['target'])
    relation = options['relation']
    identity = {'relation': relation}

    def read(connection, state, out):
        client = connection.client
        saved = (state or {}) if out is None else (out.state or {})
        user_id = saved.get('user_id') or client.profile_id(target.username)[0]
        return surface(connection, state, out, order='finite', command='graph', target=target.url, identity=identity,
                       extra={'user_id': user_id}, words=[relation],
                       fetch=lambda cursor: client.relation(relation, user_id, target.username, cursor))

    return reading.run(platform, invocation, command='graph', target=target.url, identity=identity, reader=read)


def activity(platform, invocation):
    """quotes or reposts of one post: the batch Threads sends, with the count it reports."""
    command = invocation.options['command']
    target = web.parse_post(invocation.options['target'])
    tab = {'quotes': 'quote', 'reposts': 'repost'}[command]

    def read(connection, state, out):
        return surface(connection, state, out, order='finite', command=command, target=target.url, identity={},
                       fetch=lambda cursor: connection.client.activity(target, tab))

    return reading.run(platform, invocation, command=command, target=target.url, identity={}, reader=read)


def me(platform, invocation):
    collection = invocation.options['collection']
    identity = {'collection': collection}

    def read(connection, state, out):
        return surface(connection, state, out, order='finite', command='me', target=None, identity=identity,
                       words=[collection], fetch=lambda cursor: connection.client.mine(collection))

    return reading.run(platform, invocation, command='me', target=None, identity=identity, reader=read)
