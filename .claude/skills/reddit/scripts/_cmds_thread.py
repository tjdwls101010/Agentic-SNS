"""Thread commands join pure graph state to the budgeted transport and file output."""
from dataclasses import asdict
from ._cmds_common import continuation, identity, transport
from ._errors import RedditError
from ._output import CursorStore, OutFile
from ._target import parse_target
from ._thread import ThreadStateStore, create_state, select_batch, next_expansion, merge_more, metadata
from ._transport import build_request


def expand(client, state, descriptor):
    if descriptor['kind'] == 'subtree':
        target = parse_target(descriptor['target'])
        spec = build_request('comments', target, sort=state['context']['sort'], context=0)
    else:
        target = state['context']['target']
        spec = build_request('morechildren', parse_target('https://www.reddit.com/comments/' + target['post_id']),
                             sort=state['context']['sort'], children=descriptor['ids'])
    try:
        body = client.get(**spec)
    except RedditError as error:
        if error.code != 7:
            raise
        body = []
    return merge_more(state, body, descriptor['ids'], descriptor['pointer'])


def run(args):
    client = transport(args)
    target = args.parsed_target
    if target.kind == 'share':
        target = client.resolve(target)
        args.target = 'https://www.reddit.com/comments/' + target.post_id + (f'/_/{target.comment_id}/' if target.comment_id else '/')
    args.sort = args.sort or 'best'
    context = {'command': 'thread', 'target': asdict(target), 'sort': args.sort}
    store, cursors = ThreadStateStore(), CursorStore()
    key = store.key(target, args.sort)
    if args.after:
        cursor = cursors.load(args.after, context)['cursor']
        if cursor.get('thread_key') != key:
            raise RedditError(2, 'The continuation does not match this thread.')
    cached = store.load(key)
    account = cached['account'] if cached else identity()
    output = OutFile(args.out, {**context, 'account': account}) if args.out else None
    try:
        if output and output.complete:
            return {'out': args.out, 'count': output.count, 'already_complete': True,
                    'requests': 0, 'budget': client.budget}
        saved = output.state if output and output.state else cached
        if args.after and saved is None:
            raise RedditError(2, 'The thread cache for this continuation is missing or expired.', 'Open the original post again to start a new snapshot.')
        if saved is None or (args.command == 'post' and not args.after and not output):
            body = client.get(**build_request('comments' if target.comment_id else 'post', target,
                                             sort=args.sort, context=args.context))
            saved = create_state(body, target, args.sort, identity())
            store.save(saved)
        elif output and output.state:
            store.save(saved)
        error = None
        with store.transaction(key, initial=saved) as state:
            if output and output.state is None:
                for node in state['nodes'].values():
                    node['shown'] = False
            results = [state['post']] if args.command == 'post' and not output else []
            goal = args.limit if args.limit is not None else (None if output else 25)
            displayed = 0
            while True:
                selected = select_batch(state, limit=max(1, goal - displayed) if goal is not None else 100,
                                        depth=1000000 if output else args.depth)
                displayed += selected['metadata']['shown']
                records = selected['records']
                if output:
                    page = [state['post']] + [r for r in records if not r.get('context')]
                    output.commit(page, {'thread_key': key}, selected['metadata']['stop_reason'], state=state)
                else:
                    results.extend(records)
                if selected['metadata']['complete'] or (records and not output) or (goal is not None and displayed >= goal):
                    break
                descriptor = next_expansion(state)
                if descriptor is None:
                    break
                try:
                    expand(client, state, descriptor)
                except RedditError as failure:
                    error = failure
                    break
                if state['stalled']:
                    break
            info = metadata(state, displayed)
            reason = info['stop_reason']
            if error:
                reason = {5: 'blocked', 8: 'budget'}.get(error.code, 'query_failure')
            if output:
                output.commit([], {'thread_key': key}, reason, state=state)
            result = {'results': results, 'thread': info, 'stop_reason': reason,
                      'account': state['account'], 'captured_at': state['fetched_at']}
        if not info['complete']:
            number = cursors.save(context, {'thread_key': key, 'account': result['account']})
            result['next'] = continuation(args, number, command='comments')
        if output:
            result.update(out=args.out, count=output.count)
        result.update(requests=client.requests, budget=client.budget)
        if error:
            result.update(error.as_dict(), code=8 if displayed or (output and output.count) else error.code)
        elif reason == 'stalled':
            result.update(RedditError(8, 'Thread expansion stalled; missing or unresolved replies remain.').as_dict(), code=8)
        result['note'] = 'Ordering is per batch; cached and expanded replies have different capture times. Reddit comment totals include deleted items.'
        return result
    finally:
        if output:
            output.close()
