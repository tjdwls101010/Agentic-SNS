"""search: posts, people, pages and groups in the server's order for this account."""
from facebook import connect, graphql
from facebook.paging import paginate


def search(options):
    text, vertical = options['target'], options['type']
    recent, since, until = bool(options.get('recent')), options.get('since'), options.get('until')
    group = graphql.normalize_group(options['in_group']) if options.get('in_group') else None
    identity = {'type': vertical, 'recent': recent, 'since': since, 'until': until, 'in_group': group}
    words = ['--type', vertical] + (['--recent'] if recent else []) + (['--since', since] if since else []) \
        + (['--until', until] if until else []) + (['--in-group', group] if group else [])

    def read(connection, state, out):
        issues, notes = [], []
        group_id = ((state or {}).get('group_id') or ((out.state or {}).get('group_id') if out is not None else None)
                    or (connection.client.resolve('group', group) if group else None))

        def fetch(cursor):
            page = connection.client.search(text, vertical, cursor, recent=recent, since=since, until=until,
                                            group_id=group_id, group_url=group)
            issues.extend(page.issues)
            notes.extend(page.issues)
            return page.records, page.page_info, page.has_items

        def commit(records, page_state, reason, skipped):
            out.commit(records, {**page_state, 'group_id': group_id} if page_state else None, reason, skipped,
                       list(dict.fromkeys(notes)))
            notes.clear()

        start = dict((out.state if out is not None else state) or {})
        limit = options.get('limit')
        if out is not None:
            start.update(seen=sorted(out.ids, key=str), pending=[])
            if limit is not None:
                if out.count >= limit:
                    return {'results': [], 'stop_reason': 'limit_reached', 'words': words}
                limit -= out.count
        result = paginate(fetch, limit=limit, state=start, commit=commit if out is not None else None,
                          whole_pages=out is not None)
        reading = {'results': [] if out is not None else result['results'], 'stop_reason': result['stop_reason'],
                   'failure': result['failure'], 'issues': issues, 'words': words, 'partial': bool(result['results'])}
        if result['state'] is not None:
            reading['continuation'] = {'command': 'search', 'target': text, 'identity': identity, 'words': words,
                                       'state': {**result['state'], 'group_id': group_id}}
        return reading

    window = {'order': 'server', 'since': since, 'until': until} if since or until else None
    return connect.run(options, command='search', target=text, identity=identity, reader=read, window=window)
