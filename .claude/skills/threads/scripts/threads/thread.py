"""post and replies: a post with its parent chain and reply tree, opened a batch or a branch at a time.

post reads the post in full, its parents and the first batch of direct replies (each followed by what hangs under
it); more: continues the direct replies as a replies command, and each direct reply with more under it carries a
replies handle that opens that branch.
"""
from threads import connect, handles
from threads.paging import paginate
from threads.threads_web import parse_post


def post(options):
    target = parse_post(options['target'])
    sort = options['sort']

    def read(connection, state, out):
        page = connection.client.post_page(target, sort=sort, limit=options.get('limit'))
        context = _reply_context(connection)
        records = page.records
        for record in records:
            branch = page.branches.get(record.get('id'))
            if branch and record.get('role') == 'reply':
                # the app opens a branch from its start (after: null); the reply's own cursor only says there is more
                record['replies_handle'] = handles.save(context, {
                    'kind': 'branch', 'post_id': target.post_id, 'path': target.path, 'sort': sort,
                    'parent_id': record['id'], 'cursor': None, 'seen': [], 'pending': []})
        reading = {'results': records, 'stop_reason': 'exhausted', 'details': {'replies': page.coverage},
                   'coverage': _coverage(page.coverage)}
        if page.replies_cursor:
            number = handles.save(context, {'kind': 'direct', 'post_id': target.post_id, 'path': target.path,
                                            'sort': sort, 'cursor': page.replies_cursor,
                                            'seen': [r['id'] for r in records if r.get('id')], 'pending': [],
                                            'reported': page.coverage['reported_direct'],
                                            'shown': page.coverage['received_direct']})
            reading['next'] = connect.words('replies', str(number), [], options)
            reading['stop_reason'] = 'limit_reached'
            reading['continuable'] = True
        return reading

    return connect.run(options, command='post', target=target.url, identity={'sort': sort}, reader=read)


def replies(options):
    number = options['target']

    def read(connection, state, out):
        start = handles.load(number, _reply_context(connection))
        return _replies(connection, options, start, out)

    return connect.run(options, command='replies', target=number, identity={}, reader=read)


def _reply_context(connection):
    return {'command': 'replies', 'target': None, 'account_id': connection.account_id}


def _replies(connection, options, start, out):
    """Batches of one post's direct replies, or of the replies under one reply; continued by a new handle."""
    client, context = connection.client, _reply_context(connection)
    branch = start['kind'] == 'branch'

    def fetch(cursor):
        if branch:
            batch = client.branch(start['post_id'], start['parent_id'], cursor, path=start['path'])
        else:
            batch = client.reply_batch(start['post_id'], cursor, sort=start['sort'], path=start['path'],
                                       seen=set(start.get('seen') or []))
        for record in batch.records:
            more = batch.branches.get(record.get('id'))
            if more:
                record['replies_handle'] = handles.save(context, {
                    'kind': 'branch', 'post_id': start['post_id'], 'path': start['path'], 'sort': start['sort'],
                    'parent_id': record['id'], 'cursor': None, 'seen': [], 'pending': []})
        return batch.records, {'has_next_page': bool(batch.cursor), 'end_cursor': batch.cursor}, bool(batch.records)

    def commit(records, page_state, reason, skipped):
        out.commit(records, page_state, reason, skipped)

    state = dict(out.state) if out is not None and out.state else {
        'cursor': start.get('cursor'), 'pending': start.get('pending') or [], 'seen': start.get('seen') or []}
    limit = options.get('limit')
    if out is not None:
        state.update(seen=sorted(out.ids, key=str), pending=[])
        if limit is not None:
            if out.count >= limit:
                return {'results': [], 'stop_reason': 'limit_reached', 'words': []}
            limit -= out.count
    one_batch = limit is None and out is None
    result = paginate(fetch, limit=limit, state=state, max_pages=1 if one_batch else None,
                      commit=commit if out is not None else None, whole_pages=out is not None)
    shown = (start.get('shown') or 0) + (out.count if out is not None else len(result['results']))
    reading = {'results': [] if out is not None else result['results'], 'stop_reason': result['stop_reason'],
               'failure': result['failure'], 'words': [], 'partial': bool(result['results']),
               'details': {'thread': {'post_id': start['post_id'], 'url': 'https://www.threads.com' + start['path'],
                                      'under': start.get('parent_id') if branch else None}}}
    reported = start.get('reported')
    if not branch and result['state'] is None and isinstance(reported, int) and shown < reported:
        reading['coverage'] = [f'Threads reports {reported} direct replies to this post; {shown} were sent (some can be '
                               'hidden, deleted or not visible to this account)']
    if result['state'] is not None and out is None:
        nxt = handles.save(context, {**start, 'cursor': result['state']['cursor'], 'shown': shown,
                                     'pending': result['state']['pending'], 'seen': result['state']['seen']})
        reading['next'] = connect.words('replies', str(nxt), [], options)
        reading['continuable'] = True
    elif result['state'] is not None:
        reading['continuable'] = True
    return reading


def _coverage(coverage):
    notes = []
    if coverage.get('unfetched'):
        notes.append(f'about {coverage["unfetched"]} direct replies Threads reports were not in this batch (an '
                     'estimate); more: reads the next batch')
    if coverage.get('unshown_received'):
        notes.append(f'{coverage["unshown_received"]} direct replies were received but not shown (--limit)')
    return notes

