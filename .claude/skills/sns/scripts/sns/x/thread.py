"""post and replies: a post with its parent chain and replies, opened a batch or a branch at a time.

post reads the post in full, its parents and the first batch of replies (each conversation thread as X shows it).
Three kinds of handle continue from there: more: reads the next batch of direct replies; a hidden handle reads the
replies X hid as probable spam or low quality; a reply's own handle reads what hangs under that reply, from the reply's
own page (X's threads can skip posts, so that page is the only complete view of a branch). All of them are handles of
the command replies, saved through the connection while the post is read.
"""
from sns import reading
from sns.cmdline import command_line, words
from sns.errors import SnsError
from sns.page import Page
from sns.paging import paginate
from sns.x import web


def _handle(connection, result, state):
    """A handle of the command replies for `state`; when it cannot be saved, None, and the failure stays on `result`
    beside what was read (a partial result, not a lost one)."""
    if isinstance(result.get('failure'), SnsError) and result['failure'].reason == 'handle':
        return None
    try:
        return connection.handle('replies', state)
    except SnsError as error:
        result.setdefault('failure', SnsError(error.kind, error.message, error.fix, reason='handle'))
        return None


def post(platform, invocation):
    options = invocation.options
    targets = [web.parse_post(value) for value in options['target']]
    sort = options['sort']
    if len(targets) > 1:
        return _batch(platform, invocation, targets)
    target = targets[0]

    def read(connection, state, out):
        page = connection.client.post_page(target.post_id, sort=sort)
        records = page.records
        if options.get('limit') is not None:
            records = _limit_replies(records, options['limit'])
        shown_ids = [r['id'] for r in records if r.get('id')]
        result = {'results': records, 'stop_reason': 'exhausted', 'details': {'replies': page.coverage},
                  'coverage': _coverage(page.coverage)}
        for record in records:
            if record.get('role') == 'reply' and _has_more(record, records):
                number = _handle(connection, result, _branch(record, sort))
                if number is not None:
                    record['replies_handle'] = number
        if page.unreadable:
            result['coverage'].append(f'{page.unreadable} replies this skill could not read were left out (X may have '
                                      'changed its answer)')
        number = _handle(connection, result, {'kind': 'hidden', 'post_id': target.post_id, 'sort': sort,
                                              'cursor': page.hidden_cursor, 'seen': shown_ids, 'pending': []}) \
            if page.hidden_cursor else None
        if number is not None:
            result['coverage'].append(f'X hid some replies as probable spam or low quality; replies {number} reads '
                                      'them')
        number = _handle(connection, result, {'kind': 'direct', 'post_id': target.post_id, 'sort': sort,
                                              'cursor': page.cursor, 'seen': shown_ids, 'pending': []}) \
            if page.cursor else None
        if number is not None:
            result['next'] = command_line(invocation.cli_path, words(platform.key, 'replies', str(number), [], options))
            result['stop_reason'] = 'limit_reached'
            result['continuable'] = True
        return result

    return reading.run(platform, invocation, command='post', target=target.url, identity={'sort': sort}, reader=read)


def _batch(platform, invocation, targets):
    """Several posts in one request: each in full, without replies; ids X did not return are named."""
    ids = list(dict.fromkeys(t.post_id for t in targets))

    def read(connection, state, out):
        records, unreadable = connection.client.posts(ids)
        found = {r['id'] for r in records}
        missing = [i for i in ids if i not in found]
        result = {'results': records, 'stop_reason': 'not_paginable', 'coverage': []}
        if missing:
            result['coverage'].append('unavailable or not returned: ' + ', '.join(missing))
            result['details'] = {'unresolved': missing}
        if unreadable:
            result['coverage'].append(f'{unreadable} of the posts X returned this skill could not read (X may have '
                                      'changed its answer), so ids named above may be among them')
        if not records:
            result['failure'] = SnsError('empty', 'None of these posts is available to this account.',
                                         'Check the ids; deleted or protected posts cannot be read.')
        return result

    return reading.run(platform, invocation, command='post', target=' '.join(ids), identity={}, reader=read)


def replies(platform, invocation):
    options = invocation.options
    number = options['target']

    def read(connection, state, out):
        start = connection.resume(int(number), 'replies')
        return _replies(platform, connection, invocation, start, out)

    return reading.run(platform, invocation, command='replies', target=number, identity={}, reader=read)


def _branch(record, sort):
    """A handle to the replies under one reply: that reply's own page, from its first batch."""
    return {'kind': 'branch', 'post_id': record['id'], 'url': record.get('url'), 'sort': sort, 'cursor': None,
            'seen': [], 'pending': [], 'reported': record.get('reply_count')}


def _has_more(record, records):
    """Whether a reply has replies under it that this page did not show."""
    count = record.get('reply_count')
    if not count:
        return False
    shown = sum(1 for r in records if r.get('parent_id') == record.get('id'))
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


def _replies(platform, connection, invocation, start, out):
    """Batches of the next direct replies, the hidden replies, or the replies under one reply; continued by handle."""
    options = invocation.options
    client = connection.client
    kind = start['kind']
    unread = [0]
    unsaved = {}   # the first handle that could not be saved while reading: kept beside the records

    def fetch(cursor):
        page = client.post_page(start['post_id'], sort=start['sort'], cursor=cursor)
        found = [r for r in page.records if r.get('role') == 'reply']
        for record in found:
            if _has_more(record, found):
                number = _handle(connection, unsaved, _branch(record, start['sort']))
                if number is not None:
                    record['replies_handle'] = number
        unread[0] += page.unreadable
        return Page(found, next=page.cursor, end=not page.cursor, unreadable=page.unreadable)

    def commit(records, page_state, reason, skipped):
        out.commit(records, page_state, reason, skipped)

    first = start.get('cursor')  # a branch handle starts at its first page (no cursor), a later one where it stopped
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
    reading_ = {'results': [] if out is not None else result['results'], 'stop_reason': result['stop_reason'],
                'failure': result['failure'], 'words': [], 'partial': bool(result['results']),
                'details': {'thread': {'post_id': start['post_id'], 'kind': kind}}}
    if kind == 'hidden':
        reading_['coverage'] = ['these are replies X hid as probable spam or low quality']
    reported = start.get('reported')
    shown = len(result['results'])
    if kind == 'branch' and result['state'] is None and isinstance(reported, int) and shown < reported:
        reading_['coverage'] = [f'X reports {reported} replies to this reply; {shown} were shown (some can be hidden, '
                                'deleted or not visible to this account)']
    if unread[0]:
        reading_['coverage'] = [*(reading_.get('coverage') or []), f'{unread[0]} replies this skill could not read '
                                'were left out (X may have changed its answer)']
    if result['state'] is not None and out is None and not reading.stops_continuing(result['failure']):
        following = _handle(connection, unsaved, {**start, 'cursor': result['state']['cursor'],
                                                  'pending': result['state']['pending'],
                                                  'seen': result['state']['seen']})
        if following is not None:
            reading_['next'] = command_line(invocation.cli_path, words(platform.key, 'replies', str(following), [], options))
            reading_['continuable'] = True
    elif result['state'] is not None and out is not None:
        reading_['continuable'] = True
    if unsaved.get('failure') and reading_['failure'] is None:
        reading_['failure'] = unsaved['failure']
    return reading_


def _coverage(coverage):
    notes = []
    reported, shown = coverage.get('reported'), coverage.get('direct_shown', 0) + coverage.get('nested_shown', 0)
    if isinstance(reported, int) and reported > shown:
        notes.append(f'X reports {reported} replies; this batch shows {shown} (more: reads the next batch)')
    if coverage.get('branches'):
        notes.append(f'{coverage["branches"]} reply threads are collapsed; a reply\'s replies <handle> reads its branch')
    return notes
