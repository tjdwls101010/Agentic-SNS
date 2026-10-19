"""post and replies: a post with its parent chain and replies, opened a batch or a branch at a time.

post reads the post in full, its parents and the first batch of replies (each conversation thread as X shows it).
Three kinds of handle continue from there: more: reads the next batch of direct replies; a hidden handle reads the
replies X hid as probable spam or low quality; a reply's own handle reads what hangs under that reply, from the reply's
own page (X's threads can skip posts, so that page is the only complete view of a branch).
"""
from twitter import connect, handles
from twitter.errors import TwitterError
from twitter.paging import paginate
from twitter.x_web import parse_post


def post(options):
    targets = [parse_post(value) for value in options['target']]
    sort = options['sort']
    if len(targets) > 1:
        return _batch(options, targets)
    target = targets[0]

    def read(connection, state, out):
        page = connection.client.post_page(target.post_id, sort=sort)
        context = _context(connection)
        records = page.records
        if options.get('limit') is not None:
            records = _limit_replies(records, options['limit'])
        for record in records:
            if record.get('role') == 'reply' and _has_more(record, records):
                record['replies_handle'] = handles.save(context, _branch(record, sort))
        shown_ids = [r['id'] for r in records if r.get('id')]
        reading = {'results': records, 'stop_reason': 'exhausted', 'details': {'replies': page.coverage},
                   'coverage': _coverage(page.coverage)}
        if page.hidden_cursor:
            number = handles.save(context, {'kind': 'hidden', 'post_id': target.post_id, 'sort': sort,
                                            'cursor': page.hidden_cursor, 'seen': shown_ids, 'pending': []})
            reading['coverage'].append(f'X hid some replies as probable spam or low quality; replies {number} reads '
                                       'them')
        if page.cursor:
            number = handles.save(context, {'kind': 'direct', 'post_id': target.post_id, 'sort': sort,
                                            'cursor': page.cursor, 'seen': shown_ids, 'pending': []})
            reading['next'] = connect.words('replies', str(number), [], options)
            reading['stop_reason'] = 'limit_reached'
            reading['continuable'] = True
        return reading

    return connect.run(options, command='post', target=target.url, identity={'sort': sort}, reader=read)


def _batch(options, targets):
    """Several posts in one request: each in full, without replies; ids X did not return are named."""
    ids = list(dict.fromkeys(t.post_id for t in targets))

    def read(connection, state, out):
        records = connection.client.posts(ids)
        found = {r['id'] for r in records}
        missing = [i for i in ids if i not in found]
        reading = {'results': records, 'stop_reason': 'not_paginable'}
        if missing:
            reading['coverage'] = ['unavailable or not returned: ' + ', '.join(missing)]
            reading['details'] = {'unresolved': missing}
        if not records:
            reading['failure'] = TwitterError(7, 'None of these posts is available to this account.',
                                              'Check the ids; deleted or protected posts cannot be read.')
        return reading

    return connect.run(options, command='post', target=' '.join(ids), identity={}, reader=read)


def replies(options):
    number = options['target']

    def read(connection, state, out):
        start = handles.load(number, _context(connection))
        return _replies(connection, options, start, out)

    return connect.run(options, command='replies', target=number, identity={}, reader=read)


def _context(connection):
    return {'command': 'replies', 'target': None, 'account_id': connection.account_id}


def _branch(record, sort):
    """A handle to the replies under one reply: that reply's own page, from its first batch."""
    return {'kind': 'branch', 'post_id': record['id'], 'url': record.get('url'), 'sort': sort, 'cursor': None,
            'seen': [], 'pending': [], 'reported': record.get('reply_count')}


def _has_more(record, records):
    """Whether a reply has replies under it that this page did not show."""
    count = record.get('reply_count')
    if not count:
        return False
    shown = sum(1 for r in records if r.get('reply_to_id') == record.get('id'))
    return count > shown


def _limit_replies(records, limit):
    """Parents and the post, then the first `limit` conversation threads (each reply with what hangs under it)."""
    kept, threads = [], 0
    for record in records:
        if record.get('role') != 'reply':
            kept.append(record)
            continue
        if record.get('depth') == 0:
            threads += 1
        if threads <= limit:
            kept.append(record)
    return kept


def _replies(connection, options, start, out):
    """Batches of the next direct replies, the hidden replies, or the replies under one reply; continued by handle."""
    client, context = connection.client, _context(connection)
    kind = start['kind']

    def fetch(cursor):
        if kind == 'branch':
            page = client.post_page(start['post_id'], sort=start['sort'], cursor=cursor)
            records = [r for r in page.records if r.get('role') == 'reply']
        else:
            page = client.post_page(start['post_id'], sort=start['sort'], cursor=cursor or start['cursor'])
            records = [r for r in page.records if r.get('role') == 'reply']
        for record in records:
            if _has_more(record, records):
                record['replies_handle'] = handles.save(context, _branch(record, start['sort']))
        return (records, {'has_next_page': bool(page.cursor), 'end_cursor': page.cursor},
                bool(records) or bool(page.unreadable))

    def commit(records, page_state, reason, skipped):
        out.commit(records, page_state, reason, skipped)

    first = None if kind == 'branch' else start.get('cursor')
    state = dict(out.state) if out is not None and out.state else {
        'cursor': first, 'pending': start.get('pending') or [], 'seen': start.get('seen') or []}
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
    reading = {'results': [] if out is not None else result['results'], 'stop_reason': result['stop_reason'],
               'failure': result['failure'], 'words': [], 'partial': bool(result['results']),
               'details': {'thread': {'post_id': start['post_id'], 'kind': kind}}}
    if kind == 'hidden':
        reading['coverage'] = ['these are replies X hid as probable spam or low quality']
    reported = start.get('reported')
    shown = len(result['results'])
    if kind == 'branch' and result['state'] is None and isinstance(reported, int) and shown < reported:
        reading['coverage'] = [f'X reports {reported} replies to this reply; {shown} were shown (some can be hidden, '
                               'deleted or not visible to this account)']
    if result['state'] is not None and out is None:
        nxt = handles.save(context, {**start, 'cursor': result['state']['cursor'],
                                     'pending': result['state']['pending'], 'seen': result['state']['seen']})
        reading['next'] = connect.words('replies', str(nxt), [], options)
        reading['continuable'] = True
    elif result['state'] is not None:
        reading['continuable'] = True
    return reading


def _coverage(coverage):
    notes = []
    reported, shown = coverage.get('reported'), coverage.get('direct_shown', 0) + coverage.get('nested_shown', 0)
    if isinstance(reported, int) and reported > shown:
        notes.append(f'X reports {reported} replies; this batch shows {shown} (more: reads the next batch)')
    if coverage.get('branches'):
        notes.append(f'{coverage["branches"]} reply threads are collapsed; a reply\'s replies <handle> reads its branch')
    return notes
