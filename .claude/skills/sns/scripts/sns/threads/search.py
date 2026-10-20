"""search: posts, tags and accounts, in Threads' order for this account.

Dates and an author narrow posts and tags on Threads' side (power_search_info, as the app's search filters send them): a
day is a local day in the zone the window was made in, the start of --since and the end of --until as midnights, so a
read to the end covers the window whatever the order. The bounds sent are the window's saved bounds, so a continuation
asks for the same span even if the computer's zone changed; the local-day check stays as a guard.
"""
from sns import reading
from sns.threads import web
from sns.threads.listing import surface
from sns.window import bounds


def search(platform, invocation):
    options = invocation.options
    text, kind = options['target'], options['type']
    accounts = kind == 'accounts'
    author = web.parse_user(options['from']).username if options.get('from') else None
    identity = {'type': kind, 'sort': None if accounts else options['sort'], 'from': author}
    dated = bool(options.get('since') or options.get('until'))
    words = ['--type', kind]
    for key in ('sort', 'from'):
        if identity.get(key):
            words += ['--' + key, identity[key]]

    def read(connection, state, out):
        client = connection.client
        if accounts:
            def fetch(cursor):
                page = client.search_accounts(text)
                page.stop = 'not_paginable'  # one batch of profiles, whatever the page says
                return page
        else:
            saved = ((out.state if out is not None else state) or {}).get('window') or {}
            span = saved.get('bounds') or bounds(options.get('since'), options.get('until'))
            filters = _filters(author, span)

            def fetch(cursor):
                return client.search_posts(text, recent=identity['sort'] == 'recent', tag=kind == 'tags', cursor=cursor,
                                           filters=filters)
        return surface(connection, state, out, order='finite' if accounts else ('server' if dated else 'ranked'),
                       command='search', target=text, identity=identity, words=words, fetch=fetch)

    window = {'order': 'server', 'since': options.get('since'), 'until': options.get('until')} if dated else None
    return reading.run(platform, invocation, command='search', target=text, identity=identity, reader=read,
                       window=window)


def _filters(author, span):
    """power_search_info for the author and dates asked for, or None: a window's bounds are epochs, the end the
    midnight after --until."""
    found = {}
    if author:
        found['author_username'] = author
    if span.get('start') is not None:
        found['lookback_min_unixtime'] = int(span['start'])
    if span.get('end') is not None:
        found['lookback_max_unixtime'] = int(span['end'])
    return found or None
