"""post, comments and replies: a post and its comment tree, opened a branch at a time.

post reads the post in full and the first page of parent comments; comments pages through parents; each comment with
replies carries a handle that `replies` opens (a batch of replies, each reply with its own handle for deeper replies).
"""
from facebook import connect, graphql, handles
from facebook.paging import paginate


def post(options):
    target = graphql.normalize_post(options['target'])
    sort = options['sort']

    def read(connection, state, out):
        client = connection.client
        story_id = client.resolve('post', target)
        record, issues = client.permalink(story_id, target)
        reading = _parents(connection, options, target, sort, record['id'], None, max_pages=1)
        reading['results'].insert(0, record)
        reading['issues'] = issues + reading['issues']
        return reading

    return connect.run(options, command='post', target=target, identity={'sort': sort}, reader=read)


def comments(options):
    target = graphql.normalize_post(options['target'])
    sort = options['sort']

    def read(connection, state, out):
        if state is not None:
            feedback_id = state['post']
        elif out is not None and out.state is not None:
            feedback_id = out.state['post']
        else:
            client = connection.client
            feedback_id = client.permalink(client.resolve('post', target), target)[0]['id']
        one_page = options.get('limit') is None and out is None
        return _parents(connection, options, target, sort, feedback_id, state, out=out, max_pages=1 if one_page else None)

    return connect.run(options, command='comments', target=target, identity={'sort': sort}, reader=read)


def _parents(connection, options, target, sort, feedback_id, state, *, out=None, max_pages=None):
    """Pages of parent comments, each given its reply handle; continued as a comments command."""
    issues, notes = [], []
    reply_context = {'command': 'replies', 'target': None, 'account_id': connection.account_id}

    def fetch(cursor):
        page = connection.client.comments(feedback_id, sort, cursor, url=target)
        issues.extend(page.issues)
        notes.extend(page.issues)
        for record in page.records:
            handle = page.handles.get(record['id']) or {}
            if handle.get('expandable'):
                record['replies_handle'] = handles.save(reply_context, {
                    'feedback_id': handle['feedback_id'], 'expansion_token': handle['expansion_token'],
                    'parent_id': record['id'], 'post_id': feedback_id, 'post_url': target, 'depth': 1, 'cursor': None})
        return page.records, page.page_info, page.has_items

    def commit(records, page_state, reason, skipped):
        out.commit(records, {**page_state, 'post': feedback_id} if page_state else None, reason, skipped,
                   list(dict.fromkeys(notes)))
        notes.clear()

    start = dict((out.state if out is not None else state) or {})
    limit = options.get('limit')
    if out is not None:
        start.update(seen=sorted(out.ids, key=str), pending=[])
        if limit is not None:
            if out.parent_count >= limit:
                return {'results': [], 'stop_reason': 'limit_reached', 'words': ['--sort', sort]}
            limit -= out.parent_count
    result = paginate(fetch, limit=limit, state=start, max_pages=max_pages, commit=commit if out is not None else None,
                      whole_pages=out is not None)
    reading = {'results': [] if out is not None else result['results'], 'stop_reason': result['stop_reason'],
               'failure': result['failure'], 'issues': issues, 'words': ['--sort', sort],
               'partial': bool(result['results']), 'detail': True}
    if result['state'] is not None:
        reading['continuation'] = {'command': 'comments', 'target': target, 'identity': {'sort': sort},
                                   'words': ['--sort', sort], 'state': {**result['state'], 'post': feedback_id},
                                   'limit': options.get('limit') if options['command'] == 'comments' else None}
    return reading
