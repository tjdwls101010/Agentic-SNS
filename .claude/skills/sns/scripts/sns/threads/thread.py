"""post and replies: a post with its parent chain and reply tree, opened a batch or a branch at a time.

post reads the post in full, its parents and the first batch of direct replies (each followed by what hangs under it).
Two kinds of handle continue from there, both handles of the command replies, saved through the connection while the
post is read: more: reads the next batch of direct replies, and each direct reply with more under it carries a
replies handle that opens that branch from the reply's own page.
"""
from urllib.parse import urlsplit

from sns import reading
from sns.cmdline import command_line, words
from sns.errors import SnsError
from sns.page import Page
from sns.paging import paginate
from sns.threads import web


def _handle(connection, holder, state):
    """A handle of the command replies for `state`; when it cannot be saved, None, and the failure stays on `holder`
    beside what was read (a partial result, not a lost one)."""
    if isinstance(holder.get('failure'), SnsError) and holder['failure'].reason == 'handle':
        return None
    try:
        return connection.handle('replies', state)
    except SnsError as error:
        holder.setdefault('failure', SnsError(error.kind, error.message, error.fix, reason='handle'))
        return None


def post(platform, invocation):
    options = invocation.options
    target = web.parse_post(options['target'])
    sort = options['sort']

    def read(connection, state, out):
        page = connection.client.post_page(target, sort=sort, limit=options.get('limit'))
        result = {'results': page.records, 'stop_reason': 'exhausted', 'details': {'replies': page.coverage},
                  'coverage': _coverage(page.coverage)}
        for record in page.records:
            branch = page.branches.get(record.get('id'))
            if branch and record.get('role') == 'reply':
                number = _handle(connection, result, _branch(target.post_id, target.path, sort, record))
                if number is not None:
                    record['replies_handle'] = number
        if page.replies_cursor:
            number = _handle(connection, result, {
                'kind': 'direct', 'post_id': target.post_id, 'path': target.path, 'sort': sort,
                'cursor': page.replies_cursor, 'seen': [r['id'] for r in page.records if r.get('id')], 'pending': [],
                'reported': page.coverage['reported_direct'], 'shown': page.coverage['received_direct']})
            if number is not None:
                result['next'] = command_line(invocation.cli_path,
                                              words(platform.key, 'replies', str(number), [], options))
                result['stop_reason'] = 'limit_reached'
                result['continuable'] = True
        return result

    return reading.run(platform, invocation, command='post', target=target.url, identity={'sort': sort}, reader=read)


def replies(platform, invocation):
    number = invocation.options['target']

    def read(connection, state, out):
        start = connection.resume(int(number), 'replies')
        return _replies(platform, connection, invocation, start, out)

    return reading.run(platform, invocation, command='replies', target=number, identity={}, reader=read)


def _branch(post_id, path, sort, record):
    """A handle to the replies under one reply: read from that reply's own page (its path when it has one), from its
    start; the reply's own cursor in the thread view only says there is more."""
    own = urlsplit(record.get('url') or '').path
    return {'kind': 'branch', 'post_id': post_id, 'path': path, 'branch_path': own if '/post/' in own else path,
            'sort': sort, 'parent_id': record['id'], 'cursor': None, 'seen': [], 'pending': [],
            'parent': {'id': record['id'], 'author_id': (record.get('author') or {}).get('id'),
                       'reply_level': record.get('reply_level')},
            'reported': record.get('reply_count'), 'shown': 0}


def _replies(platform, connection, invocation, start, out):
    """Batches of one post's direct replies, or of the replies under one reply; continued by a new handle."""
    options = invocation.options
    client = connection.client
    branch = start['kind'] == 'branch'
    unsaved = {}   # the first handle that could not be saved while reading: kept beside the records

    def fetch(cursor):
        if branch:
            batch = client.branch(start['parent'], cursor, sort=start['sort'], path=start['branch_path'],
                                  seen=set(start.get('seen') or []))
        else:
            batch = client.reply_batch(start['post_id'], cursor, sort=start['sort'], path=start['path'],
                                       seen=set(start.get('seen') or []))
        for record in batch.records:
            if batch.branches.get(record.get('id')):
                number = _handle(connection, unsaved, _branch(start['post_id'], start['path'], start['sort'], record))
                if number is not None:
                    record['replies_handle'] = number
        return Page(batch.records, next=batch.cursor, end=not batch.cursor)

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
                      commit=out.commit if out is not None else None, whole_pages=out is not None)
    shown = (start.get('shown') or 0) + (out.count if out is not None else len(result['results']))
    reading_ = {'results': [] if out is not None else result['results'], 'stop_reason': result['stop_reason'],
                'failure': result['failure'], 'words': [], 'partial': bool(result['results']),
                'details': {'thread': {'post_id': start['post_id'], 'url': web.ORIGIN + start['path'],
                                       'under': start.get('parent_id') if branch else None}}}
    reported = start.get('reported')
    if result['state'] is None and isinstance(reported, int) and shown < reported:
        reading_['coverage'] = [f'Threads reports {reported} direct replies to this {"reply" if branch else "post"}; '
                                f'{shown} were sent (some can be hidden, deleted or not visible to this account)']
    if result['state'] is not None and out is None and not reading.stops_continuing(result['failure']):
        following = _handle(connection, unsaved, {**start, 'cursor': result['state']['cursor'], 'shown': shown,
                                                  'pending': result['state']['pending'],
                                                  'seen': result['state']['seen']})
        if following is not None:
            reading_['next'] = command_line(invocation.cli_path,
                                            words(platform.key, 'replies', str(following), [], options))
            reading_['continuable'] = True
    elif result['state'] is not None and out is not None:
        reading_['continuable'] = True
    if unsaved.get('failure') and reading_['failure'] is None:
        reading_['failure'] = unsaved['failure']
    return reading_


def _coverage(coverage):
    notes = []
    if coverage.get('unfetched'):
        notes.append(f'about {coverage["unfetched"]} direct replies Threads reports were not in this batch (an '
                     'estimate); more: reads the next batch')
    if coverage.get('unshown_received'):
        notes.append(f'{coverage["unshown_received"]} direct replies were received but not shown (--limit)')
    return notes
