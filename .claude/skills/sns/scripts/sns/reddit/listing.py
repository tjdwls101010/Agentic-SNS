"""feed, sub, profile, me and related: listings read page by page in Reddit's order (reading.read_list), plus what every
listing command shares — the sort a date window implies and the page a listing asks for."""
from sns import reading
from sns.errors import SnsError
from sns.page import Page

from sns.reddit import web

DISPLAY = 25   # a page asks Reddit for 100 and shows this many; the rest waits in the handle


def window_check(options):
    """A date window reads a timeline: Reddit's other orders are rankings. An explicit --sort other than new is refused
    (a sort left out is read as new, see resolve_sort)."""
    if (options.get('since') or options.get('until')) and options.get('sort') not in (None, 'new'):
        raise SnsError('argument', 'A date window needs --sort new: other orders are rankings, not a timeline.',
                       'Use --sort new (or leave --sort out) with --since/--until, or --time for a ranking\'s server '
                       'period.')


def resolve_sort(options, default):
    """(the sort a result names, the sort sent to Reddit, the words that repeat it in more:). A window with no --sort
    reads newest first and says so: 'new (window)' (its more: carries no --sort, so it repeats the same implication)."""
    if options.get('sort') is None and (options.get('since') or options.get('until')) and default != 'new':
        return 'new (window)', 'new', []
    sort = options.get('sort') or default
    return sort, sort, ['--sort', sort]


def window_of(options, order):
    """The window a result states even when the read failed before it was made."""
    if options.get('since') or options.get('until'):
        return {'since': options.get('since'), 'until': options.get('until'), 'order': order}
    return None


def read_pages(connection, state, out, *, request, command, target, identity, words, order):
    """A listing read page by page, as a reading for reading.run(): a page asks for 100 and shows 25 (--limit); the rest
    waits in the handle, so the next more: shows it with no further listing request. A date window is only for sort
    new (a timeline): it keeps the records of its days and closes at the first record older than --since, pinned posts
    aside; a listing that ends first did not cover the window (partial).

    Returns the reading and the number of records Reddit sent in this invocation's pages (a profile judges an empty
    first page by it)."""
    received = []

    def fetch(after):
        records, following = connection.client.listing(request(after))
        received.append(len(records))
        return Page(records, next=following, end=following is None)

    earlier = bool((state or {}).get('cursor') or (state or {}).get('seen') or (out is not None and out.count))
    result = reading.read_list(connection, state, out, order=order, fetch=fetch, command=command, target=target,
                               identity=identity, words=words, show=DISPLAY)
    failure = result.get('failure')
    if failure is not None and failure.reason == 'listing_ended' and not earlier and not any(received):
        result['failure'] = None  # a listing with nothing in it is empty (7), not one that ended before the window
    return result, received


def feed(platform, invocation):
    """Your home feed, a page at a time."""
    options = invocation.options
    shown, sort, sort_words = resolve_sort(options, 'best')
    identity = {'sort': shown, 'time': options.get('time')}
    words = sort_words + (['--time', options['time']] if options.get('time') else [])
    order = 'newest_first' if sort == 'new' else 'ranked'

    def read(connection, state, out):
        return read_pages(connection, state, out, request=lambda after: web.routes.feed(sort, options.get('time'), after),
                          command='feed', target=None, identity=identity, words=words, order=order)[0]

    # 성진: 홈 best·hot은 개인화된 끝없는 표면이다 — --out은 --limit이 있어야 끝을 안다(계획 '자연 종료 규칙')
    return reading.run(platform, invocation, command='feed', target=None, identity=identity, reader=read,
                       window=window_of(options, order), endless=sort in ('best', 'hot'))


def sub(platform, invocation):
    """A community's listing."""
    options = invocation.options
    target = web.require(web.parse_target(options['target']), 'sub')
    shown, sort, sort_words = resolve_sort(options, 'hot')
    identity = {'sort': shown, 'time': options.get('time')}
    words = sort_words + (['--time', options['time']] if options.get('time') else [])
    order = 'newest_first' if sort == 'new' else 'ranked'

    def read(connection, state, out):
        return read_pages(connection, state, out, request=lambda after: web.routes.listing(
            target.sub, sort, options.get('time'), after), command='sub', target=target.name, identity=identity,
            words=words, order=order)[0]

    return reading.run(platform, invocation, command='sub', target=target.name, identity=identity, reader=read,
                       window=window_of(options, order))


def related(platform, invocation):
    """Other posts of the same link (crossposts and duplicates), in other communities or the same one."""
    target = web.require(web.parse_target(invocation.options['target']), 'related')

    def read(connection, state, out):
        return read_pages(connection, state, out, request=lambda after: web.routes.related(target.post_id, after),
                          command='related', target=target.name, identity={}, words=[], order='finite')[0]

    return reading.run(platform, invocation, command='related', target=target.name, identity={}, reader=read)


def me(platform, invocation):
    """The user's own subscriptions, saved or upvoted items, read under the logged-in name."""
    collection = invocation.options['collection']
    identity = {'collection': collection}

    def read(connection, state, out):
        name = connection.viewer()  # the account check names whose lists these are (a bound read has made it already)
        return read_pages(connection, state, out, request=lambda after: web.routes.mine(collection, name, after),
                          command='me', target=None, identity=identity, words=[collection], order='finite')[0]

    return reading.run(platform, invocation, command='me', target=None, identity=identity, reader=read)


_KARMA = {'overview': ('activity', 'karma', ('post_karma', 'comment_karma')),
          'posts': ('posts', 'post karma', ('post_karma',)),
          'comments': ('comments', 'comment karma', ('comment_karma',))}


def profile(platform, invocation):
    """A redditor's public activity. A first unfiltered page that comes back empty is judged against the account's karma
    for that kind (one more request): karma means the history is hidden from other accounts or was deleted (unavailable),
    no karma is only what was observed (empty)."""
    options = invocation.options
    target = web.require(web.parse_target(options['target']), 'profile')
    kind = options.get('type') or 'overview'
    shown, sort, sort_words = resolve_sort(options, 'new')
    identity = {'sort': shown, 'time': options.get('time'), 'type': kind}
    words = ['--type', kind] + sort_words + (['--time', options['time']] if options.get('time') else [])
    order = 'newest_first' if sort == 'new' else 'ranked'
    unfiltered = not (options.get('after') or options.get('since') or options.get('until') or options.get('time'))

    def read(connection, state, out):
        result, received = read_pages(connection, state, out, request=lambda after: web.routes.profile(
            target.user, kind, sort, options.get('time'), after), command='profile', target=target.name,
            identity=identity, words=words, order=order)
        empty = result.get('stop_reason') == 'exhausted' and result.get('failure') is None and not any(received) \
            and not result.get('results') and (out is None or not out.count)
        if unfiltered and empty:
            result['failure'] = _history(connection, target.user, kind)
        return result

    return reading.run(platform, invocation, command='profile', target=target.name, identity=identity, reader=read,
                       window=window_of(options, order))


def _history(connection, name, kind):
    """The failure an empty first page means, from the karma of that kind."""
    noun, karma_name, fields = _KARMA[kind]
    try:
        card = connection.client.user(name)
    except SnsError as error:
        return error
    karma = sum(card.get(field) or 0 for field in fields)
    if karma > 0:
        return SnsError('unavailable', f'no visible {noun} although {karma_name} is {karma:g}: the history is hidden '
                                       'from other accounts or was deleted', f'Tell the user; about u/{name} still '
                                       'reads the account\'s card (karma, age).', reason='history_not_visible')
    return SnsError('empty', f'no visible {noun}; {karma_name} is 0', 'An empty history here is what was observed, not '
                                                                     'proof the account never posted.')
