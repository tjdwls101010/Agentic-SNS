"""search and quotes: X's search, in X's order for this account, with its operators passed through as typed.

A query that carries since:/until: (or since_time:/until_time:) is filtered by X itself, so a search read to its end
covers that window whatever the order; anything else in the query is X's to interpret. Quotes are a search too (the
one X's own quotes screen sends), so they share search's limit.
"""
import re

from sns import reading
from sns.x import web
from sns.x.listing import surface

PRODUCTS = {'posts': {'top': 'Top', 'latest': 'Latest'}, 'accounts': {'top': 'People', 'latest': 'People'},
            'media': {'top': 'Media', 'latest': 'Media'}}
_DATES = re.compile(r'(?<![\w-])(since|until|since_time|until_time):(\S+)', re.I)


def _server_window(text):
    """The window X applies itself, from the query's own date operators, or None."""
    found = {m[1].lower(): m[2] for m in _DATES.finditer(text)}
    if not found:
        return None
    # X decides which day boundaries those operators use (measured once: its own days), so the line names them as X's
    return {'order': 'server', 'since': found.get('since') or found.get('since_time'),
            'until': found.get('until') or found.get('until_time'), 'tz': "X's own days"}


def search(platform, invocation):
    options = invocation.options
    text, kind, sort = options['target'], options['type'], options['sort']
    if options.get('within') == 'communities':
        return _in_communities(platform, invocation, text)
    product = PRODUCTS[kind][sort]
    identity = {'type': kind, 'sort': None if kind == 'accounts' else sort}
    window = _server_window(text) if kind != 'accounts' else None
    order = 'server' if window else ('newest_first' if product == 'Latest' else 'ranked')

    def read(connection, state, out):
        return surface(connection, state, out, order=order, command='search', target=text, identity=identity,
                       kinds=('account',) if kind == 'accounts' else ('post',),
                       words=['--type', kind] + (['--sort', sort] if kind != 'accounts' else []),
                       fetch=lambda cursor: connection.client.search(text, product, cursor))

    return reading.run(platform, invocation, command='search', target=text, identity=identity, reader=read,
                       window=window)


def _in_communities(platform, invocation, text):
    """Posts in communities that match `text`, in the order X's community search serves them."""
    identity = {'in': 'communities'}
    window = _server_window(text)

    def read(connection, state, out):
        return surface(connection, state, out, order='server' if window else 'ranked', kinds=('post',),
                       command='search', target=text, identity=identity, words=['--in', 'communities'],
                       fetch=lambda cursor: connection.client.community_search(text, cursor))

    return reading.run(platform, invocation, command='search', target=text, identity=identity, reader=read,
                       window=window)


def quotes(platform, invocation):
    options = invocation.options
    target = web.parse_post(options['target'])
    sort = options['sort']
    identity = {'sort': sort}

    def read(connection, state, out):
        return surface(connection, state, out, order='ranked', command='quotes', target=target.url,
                       identity=identity, kinds=('post',), words=['--sort', sort],
                       fetch=lambda cursor: connection.client.quotes(target.post_id, sort, cursor))

    return reading.run(platform, invocation, command='quotes', target=target.url, identity=identity, reader=read)
