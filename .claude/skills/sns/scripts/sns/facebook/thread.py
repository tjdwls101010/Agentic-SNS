"""post, comments and replies: a post and its comment tree, opened a branch at a time.

post reads the post in full and the first page of parent comments; comments pages through parents; each comment with
replies carries a handle that `replies` opens (a batch of replies, each reply with its own handle for deeper replies).
Every handle is a handle of the command replies, saved through the connection while the comments are read.
"""
from sns import reading
from sns.cmdline import command_line, words
from sns.errors import SnsError
from sns.facebook import web
from sns.facebook.listing import issue_notes
from sns.page import Page
from sns.paging import paginate


def _page(batch):
    """The reading Page of one answer of a comment connection (see listing.paged)."""
    info = batch.page_info if isinstance(batch.page_info, dict) else {}
    cursor = info.get('end_cursor') if info.get('has_next_page') is True and isinstance(info.get('end_cursor'), str) \
        else None
    return Page(batch.records, next=cursor or None, end=info.get('has_next_page') is False,
                unreadable=1 if batch.has_items and not batch.records else 0)


def ended(out):
    """A collection whose last page was committed but whose final line was lost: the source's end is judged again from
    the file, with no request (as reading.read_list does for a list)."""
    return out is not None and out.state is None and out.count and not out.complete


def _ending(out, words):
    stop = out.last_stop or 'exhausted'
    return {'results': [], 'stop_reason': stop, 'ending': stop, 'words': words}


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
    target = web.normalize_post(options['target'])
    sort = options['sort']

    def read(connection, state, out):
        client = connection.client
        story_id = client.resolve('post', target)
        record, issues = client.permalink(story_id, target)
        result = _parents(platform, connection, invocation, target, sort, record['id'], None, max_pages=1)
        result['results'].insert(0, record)
        result['coverage'] = [*issue_notes(issues), *result.get('coverage', [])]
        return result

    return reading.run(platform, invocation, command='post', target=target, identity={'sort': sort}, reader=read)


def comments(platform, invocation):
    options = invocation.options
    target = web.normalize_post(options['target'])
    sort = options['sort']

    def read(connection, state, out):
        if ended(out):
            return _ending(out, ['--sort', sort])
        if state is not None:
            feedback_id = state['post']
        elif out is not None and out.state is not None:
            feedback_id = out.state['post']
        else:
            client = connection.client
            feedback_id = client.permalink(client.resolve('post', target), target)[0]['id']
        one_page = options.get('limit') is None and out is None
        return _parents(platform, connection, invocation, target, sort, feedback_id, state, out=out,
                        max_pages=1 if one_page else None)

    return reading.run(platform, invocation, command='comments', target=target, identity={'sort': sort}, reader=read)


def replies(platform, invocation):
    number = invocation.options['target']

    def read(connection, state, out):
        start = connection.resume(int(number), 'replies')
        result = _replies(platform, connection, invocation, start, out)
        result['details'] = {'thread': {'post_url': start['post_url'], 'parent_id': start['parent_id'],
                                        'depth': start['depth']}}
        return result

    return reading.run(platform, invocation, command='replies', target=number, identity={}, reader=read)


def _reply_state(handle, record, post_id, post_url, depth):
    """What a later `replies` run needs to open the replies under `record`."""
    return {'feedback_id': handle['feedback_id'], 'expansion_token': handle['expansion_token'],
            'parent_id': record['id'], 'post_id': post_id, 'post_url': post_url, 'depth': depth, 'cursor': None,
            'reported': record['reply_count'], 'shown': 0}


def _replies(platform, connection, invocation, start, out):
    """Batches of replies to one comment; each reply with deeper replies gets a handle; continued by a new handle."""
    options = invocation.options
    if ended(out):
        return _ending(out, [])
    issues = []
    unsaved = {}   # the first handle that could not be saved while reading: kept beside the records

    def fetch(cursor):
        batch = connection.client.replies(start['feedback_id'], start['expansion_token'], cursor,
                                          depth=start['depth'], parent_id=start['parent_id'],
                                          post_id=start['post_id'], url=start['post_url'])
        issues.extend(batch.issues)
        for record in batch.records:
            handle = batch.handles.get(record['id']) or {}
            # Facebook nests replies two levels deep; a deeper reply's own replies are not opened.
            if handle.get('expandable') and record['depth'] == 1:
                number = _handle(connection, unsaved, _reply_state(handle, record, start['post_id'],
                                                                   start['post_url'], 2))
                if number is not None:
                    record['replies_handle'] = number
        page = _page(batch)
        if start['depth'] >= 2 and page.next is not None:
            # Asked for the next batch of a reply's replies (after or before cursor, with or without a count), Facebook
            # sends the first one again (D6, observed 2026-10-21): the first batch is all there is to read.
            # 성진: 둘째 단계 다음 묶음을 받는 길(화면의 '답글 더 보기'가 보내는 요청)을 찾으면 이 정지를 걷을 것
            page.next, page.stop = None, 'server_capped'
        return page

    def commit(records, page_state, reason, skipped):
        out.commit(records, page_state, reason, skipped)

    state = dict(out.state) if out is not None and out.state else {
        'cursor': start.get('cursor'), 'pending': start.get('pending') or [], 'seen': start.get('seen') or [],
        'ended': start.get('ended')}
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
    reading_ = {'results': [] if out is not None else result['results'], 'stop_reason': result['stop_reason'],
                'failure': result['failure'], 'words': [], 'partial': bool(result['results']),
                'coverage': issue_notes(issues)}
    reported = start.get('reported')
    if (result['state'] is None or result['failure'] is not None) and isinstance(reported, int) and shown < reported:
        reading_['coverage'].append(f'Facebook reports {reported} replies under this comment (deeper ones included); '
                                    f'{shown} were sent')
    if result['state'] is not None and out is None and not reading.stops_continuing(result['failure']):
        following = _handle(connection, unsaved, {**start, 'cursor': result['state']['cursor'], 'shown': shown,
                                                  'pending': result['state']['pending'],
                                                  'seen': result['state']['seen'],
                                                  'ended': result['state'].get('ended')})
        if following is not None:
            reading_['next'] = command_line(invocation.cli_path, words(platform.key, 'replies', str(following), [],
                                                                       options))
            reading_['continuable'] = True
    elif result['state'] is not None and out is not None:
        reading_['continuable'] = True
    if unsaved.get('failure') and reading_['failure'] is None:
        reading_['failure'] = unsaved['failure']
    return reading_


def _parents(platform, connection, invocation, target, sort, feedback_id, state, *, out=None, max_pages=None):
    """Pages of parent comments, each given its reply handle; continued as a comments command."""
    options = invocation.options
    issues = []
    unsaved = {}

    def fetch(cursor):
        batch = connection.client.comments(feedback_id, sort, cursor, url=target)
        issues.extend(batch.issues)
        for record in batch.records:
            handle = batch.handles.get(record['id']) or {}
            if handle.get('expandable'):
                number = _handle(connection, unsaved, _reply_state(handle, record, feedback_id, target, 1))
                if number is not None:
                    record['replies_handle'] = number
        return _page(batch)

    def commit(records, page_state, reason, skipped):
        out.commit(records, {**page_state, 'post': feedback_id} if page_state else None, reason, skipped)

    start = dict((out.state if out is not None else state) or {})
    limit = options.get('limit')
    if out is not None:
        start.update(seen=sorted(out.ids, key=str), pending=[])
        if limit is not None:
            if out.count >= limit:
                return {'results': [], 'stop_reason': 'limit_reached', 'words': ['--sort', sort]}
            limit -= out.count
    result = paginate(fetch, limit=limit, state=start, max_pages=max_pages, commit=commit if out is not None else None,
                      whole_pages=out is not None)
    reading_ = {'results': [] if out is not None else result['results'], 'stop_reason': result['stop_reason'],
                'failure': result['failure'], 'words': ['--sort', sort], 'partial': bool(result['results']),
                'coverage': issue_notes(issues)}
    if result['state'] is not None:
        reading_['continuation'] = {'command': 'comments', 'target': target, 'identity': {'sort': sort},
                                    'words': ['--sort', sort], 'state': {**result['state'], 'post': feedback_id},
                                    'limit': options.get('limit') if invocation.options['command'] == 'comments'
                                    else None}
    if unsaved.get('failure') and reading_['failure'] is None:
        reading_['failure'] = unsaved['failure']
    return reading_
