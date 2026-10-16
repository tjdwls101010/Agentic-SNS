"""search: posts, tags and accounts, in Threads' order for this account."""
from threads import connect
from threads.paging import paginate


def search(options):
    text, kind = options['target'], options['type']
    sort = None if kind == 'accounts' else options['sort']
    identity = {'type': kind, 'sort': sort}

    def read(connection, state, out):
        client = connection.client
        if kind == 'accounts':
            fetch = lambda cursor: client.search_accounts(text)  # noqa: E731 — one batch
        else:
            fetch = lambda cursor: client.search_posts(text, recent=sort == 'recent', tag=kind == 'tags', cursor=cursor)  # noqa: E731
        return _read(options, identity, state, out, fetch=fetch, text=text)

    return connect.run(options, command='search', target=text, identity=identity, reader=read)


def _read(options, identity, state, out, *, fetch, text):
    natural = {}

    def fetch_page(cursor):
        page = fetch(cursor)
        natural['stop'] = page.stop
        return page.records, {'has_next_page': page.has_next, 'end_cursor': page.cursor}, bool(page.records)

    def commit(records, page_state, reason, skipped):
        out.commit(records, page_state, reason, skipped)

    start = dict(out.state or {}) if out is not None else dict(state or {})
    limit = options.get('limit')
    if out is not None:
        start.update(seen=sorted(out.ids, key=str), pending=[])
        if limit is not None:
            if out.count >= limit:
                return {'results': [], 'stop_reason': 'limit_reached', 'words': _words(identity)}
            limit -= out.count
    one_page = limit is None and out is None
    result = paginate(fetch_page, limit=limit, state=start, commit=commit if out is not None else None,
                      whole_pages=out is not None, max_pages=1 if one_page else None)
    stop = result['stop_reason']
    if stop == 'exhausted' and natural.get('stop') == 'not_paginable':
        stop = 'not_paginable'
    reading = {'results': [] if out is not None else result['results'], 'stop_reason': stop,
               'failure': result['failure'], 'words': _words(identity), 'partial': bool(result['results'])}
    if result['state'] is not None:
        reading['continuation'] = {'command': 'search', 'target': text, 'identity': identity,
                                   'words': _words(identity), 'state': result['state']}
    return reading


def _words(identity):
    words = ['--type', identity['type']]
    if identity.get('sort'):
        words += ['--sort', identity['sort']]
    return words
