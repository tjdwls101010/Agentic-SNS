"""Home and profile activity share one continuation/commit path."""
from ._cmds_common import check_access, check_actor, context, finish, more_command
from ._errors import ThreadsError
from ._listing import collect, date_bound
from ._output import CursorStore, OutFile
from ._ssr import SSR
from ._transport import Transport
from ._walk import read_page


def run(args):
    ctx = context(args)
    if (getattr(args, 'since', None) or getattr(args, 'until', None)) and args.command == 'home' and ctx['feed'] != 'following':
        raise ThreadsError(2, 'Date windows apply only to the following feed and profile activity tabs.')
    lower, upper = date_bound(ctx.get('since')), date_bound(ctx.get('until'))
    if lower is not None and upper is not None and lower >= upper:
        raise ThreadsError(2, '--since must be earlier than --until.')
    transport = Transport(40 if args.limit or ctx.get('since') or args.out else 10)
    output = OutFile(args.out, ctx) if args.out else None
    try:
        if output and output.complete:
            return finish({'ok': True, 'results': [], 'stop_reason': output.cursor.get('terminal', 'exhausted'),
                           'out': str(output.path), 'count': output.count, 'already_complete': True}, transport)
        state = CursorStore().load(args.after, ctx)['cursor'] if args.after else (output.cursor if output else None)
        state = state or {}
        initial = None
        if state:
            transport.page('/')
            check_actor(state, transport)
        elif args.command in ('user', 'graph'):
            html = transport.page(args.target.path)
            state['user_id'] = transport.session.identity('BarcelonaProfilePageDirectQuery', 'userID')
            ssr = SSR(html)
            profile = ssr.select('BarcelonaProfilePageDirectQuery', state['user_id'])['user'] or {}
            if profile and profile.get('username', '').lower() != args.target.username:
                raise ThreadsError(6, 'Profile identity differs from the requested handle.', 'Run refresh.', error='envelope_drift')
            state['private_unfollowed'] = bool(profile.get('text_post_app_is_private') and
                                               (profile.get('friendship_status') or {}).get('following') is False) if profile else None
            if args.command == 'user' and ctx['tab'] == 'threads':
                initial = read_page(ssr.select('BarcelonaProfileThreadsTabDirectQuery', state['user_id']), 'BarcelonaProfileThreadsTabDirectQuery')
                check_access(initial, transport, state)
        else:
            html = transport.page('/')
            if args.command == 'home' and ctx['feed'] == 'foryou':
                initial = read_page(SSR(html).select('BarcelonaFeedDirectQuery'), 'BarcelonaFeedDirectQuery')
        check_actor(state, transport)
        operation, variables = query_for(ctx, state)
        def fetch(after):
            name, values = operation, dict(variables)
            if after:
                values['after'] = after
                if args.command == 'home':
                    values['data'] = values['data'] | {'reason': 'pagination'}
                if args.command == 'graph' and ctx['relation'] == 'following':
                    name, values = 'BarcelonaFriendshipsFollowingTabRefetchableQuery', {'id': state['user_id'], 'first': 10, 'after': after}
            page = read_page(transport.query(name, values), name)
            if args.command == 'user':
                check_access(page, transport, state)
            return page
        result = collect(fetch, limit=args.limit or 10, state=state, initial=initial,
                         since=ctx.get('since'), until=ctx.get('until'),
                         monotonic=args.command == 'user' and ctx['tab'] in ('threads', 'replies'),
                         commit=output.commit if output else None)
        state = result.pop('state')
        result['context'] = ctx
        if args.command == 'graph' and ctx['relation'] == 'followers':
            result['reported_total'] = state.get('reported_total')
        if state['pending'] or not state['done']:
            handle = CursorStore().save(ctx, state)
            result.update(next_handle=handle, next=more_command(ctx, handle))
        if output:
            result.update(out=str(output.path), count=output.count, results=[])
        return finish(result, transport)
    finally:
        if output:
            output.close()


def query_for(ctx, state):
    command = ctx['command']
    if command == 'home':
        following = ctx['feed'] == 'following'
        return 'BarcelonaFeedDirectQuery', {'variant': 'following' if following else 'for_you',
            'data': {'pagination_source': 'text_post_feed_following' if following else 'text_post_feed_threads', 'reason': 'cold_start_fetch'}}
    if command == 'user':
        return 'BarcelonaProfile' + ctx['tab'].capitalize() + 'TabDirectQuery', {'userID': state['user_id'], 'first': 25}
    if command == 'graph':
        return 'BarcelonaFriendships' + ctx['relation'].capitalize() + 'TabQuery', {'userID': state['user_id'], 'first': 20}
    if command == 'search':
        if ctx['type'] == 'users':
            return 'useBarcelonaAccountSearchGraphQLDataSourceQuery', {'query': ctx['query']}
        return 'BarcelonaSearchResultsQuery', {'query': ctx['query'], 'search_surface': 'tags' if ctx['tag'] else 'default',
                                               'recent': int(ctx['sort'] == 'recent')}
    return 'Barcelona' + ctx['collection'].capitalize() + 'PageViewerQuery', {}
