"""search and quotes: X's search, in X's order for this account, with its operators passed through as typed.

A query that carries since:/until: (or since_time:/until_time:) is filtered by X itself, so a search read to its end
covers that window whatever the order; anything else in the query is X's to interpret. Quotes are a search too (the
one X's own quotes screen sends), so they share search's limit.
"""
import re

from twitter import connect
from twitter.x_web import parse_post

PRODUCTS = {'posts': {'top': 'Top', 'latest': 'Latest'}, 'accounts': {'top': 'People', 'latest': 'People'},
            'media': {'top': 'Media', 'latest': 'Media'}}
_DATES = re.compile(r'(?<![\w-])(since|until|since_time|until_time):(\S+)', re.I)


def _server_window(text):
    """The window X applies itself, from the query's own date operators, or None."""
    found = {m[1].lower(): m[2] for m in _DATES.finditer(text)}
    if not found:
        return None
    return {'order': 'server', 'since': found.get('since') or found.get('since_time'),
            'until': found.get('until') or found.get('until_time')}


def search(options):
    text, kind, sort = options['target'], options['type'], options['sort']
    if options.get('within') == 'communities':
        return _in_communities(options, text)
    product = PRODUCTS[kind][sort]
    identity = {'type': kind, 'sort': None if kind == 'accounts' else sort}
    window = _server_window(text) if kind != 'accounts' else None
    order = 'server' if window else ('newest_first' if product == 'Latest' else 'unordered')

    def read(connection, state, out):
        client = connection.client
        return connect.read_list(options, identity, state, out, order=order, command='search', target=text,
                                 words=['--type', kind] + (['--sort', sort] if kind != 'accounts' else []),
                                 fetch=lambda cursor: client.search(text, product, cursor))

    return connect.run(options, command='search', target=text, identity=identity, reader=read, window=window)


def _in_communities(options, text):
    """Posts in communities that match `text`, in the order X's community search serves them."""
    identity = {'in': 'communities'}
    window = _server_window(text)

    def read(connection, state, out):
        client = connection.client
        return connect.read_list(options, identity, state, out, order='server' if window else 'unordered',
                                 command='search', target=text, words=['--in', 'communities'],
                                 fetch=lambda cursor: client.community_search(text, cursor))

    return connect.run(options, command='search', target=text, identity=identity, reader=read, window=window)


def quotes(options):
    target = parse_post(options['target'])
    sort = options['sort']
    identity = {'sort': sort}

    def read(connection, state, out):
        client = connection.client
        return connect.read_list(options, identity, state, out, order='unordered', command='quotes', target=target.url,
                                 words=['--sort', sort],
                                 fetch=lambda cursor: client.quotes(target.post_id, sort, cursor))

    return connect.run(options, command='quotes', target=target.url, identity=identity, reader=read)
