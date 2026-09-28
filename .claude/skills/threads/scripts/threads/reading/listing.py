"""Home and profile activity share one continuation/commit path."""
from ..errors import ThreadsError
from ..graphql.decode import read_page
from ..graphql.operations import OPERATIONS
from ..graphql.ssr import SSR
from ..graphql.transport import Transport
from ..store import CursorStore, OutFile
from .collect import collect, date_bound
from .common import check_access, check_actor, finish


def run(args, ctx):
    """Read a listing for the query `ctx` identifies. A continuation is returned as next_handle; the caller writes the
    command that resumes it into `next`."""
    if (getattr(args, 'since', None) or getattr(args, 'until', None)) and args.command == 'home' and ctx['feed'] != 'following':
        raise ThreadsError(2, 'Date windows apply only to the following feed and profile activity tabs.')
    lower, upper = date_bound(ctx.get('since')), date_bound(ctx.get('until'))
    if lower is not None and upper is not None and lower >= upper:
        raise ThreadsError(2, '--since must be earlier than --until.')
    transport = Transport(40 if args.limit or ctx.get('since') or args.out else 10)
    output = OutFile(args.out, ctx) if args.out else None
    try:
        handle_state = CursorStore().load(args.after, ctx)['cursor'] if args.after else None
        if output and handle_state is not None and output.cursor != handle_state:
            raise ThreadsError(2, 'The file and continuation handle describe different committed progress.',
                               'Resume the same output file without --after; its committed cursor is authoritative.')
        if output and output.complete:
            return finish({'ok': True, 'results': [], 'stop_reason': output.cursor.get('terminal', 'exhausted'),
                           'out': str(output.path), 'count': output.count, 'already_complete': True}, transport)
        state = handle_state if handle_state is not None else (output.cursor if output else None)
        state = state or {}
        initial = None
        if state:
            transport.page('/')
            check_actor(state, transport)
        elif args.command in ('user', 'graph'):
            html = transport.page(args.target.path)
            state['user_id'] = transport.session.identity(transport.registry.name('profile.page'), 'userID')
            ssr = SSR(html)
            profile = transport.rendered(ssr, 'profile.page', state['user_id'])['user'] or {}
            if profile and profile.get('username', '').lower() != args.target.username:
                raise ThreadsError(6, 'Profile identity differs from the requested handle.', 'Run refresh.', error='envelope_drift')
            state['private_unfollowed'] = bool(profile.get('text_post_app_is_private') and
                                               (profile.get('friendship_status') or {}).get('following') is False) if profile else None
            if args.command == 'user' and ctx['tab'] == 'threads':
                initial = read_page(transport.rendered(ssr, 'profile.threads', state['user_id']),
                                    OPERATIONS['profile.threads'])
                state['ssr_cursor'] = initial.cursor
                check_access(initial, transport, state)
        else:
            html = transport.page('/')
            if args.command == 'home' and ctx['feed'] == 'foryou':
                initial = read_page(transport.rendered(SSR(html), 'feed'), OPERATIONS['feed'])
        check_actor(state, transport)
        operation, variables = query_for(ctx, state)
        def fetch(after):
            name, values = operation, dict(variables)
            if after:
                values['after'] = after
                if args.command == 'home':
                    values['data'] = values['data'] | {'reason': 'pagination'}
                if args.command == 'graph' and ctx['relation'] == 'following':
                    name, values = 'graph.following_more', {'id': state['user_id'], 'first': 10, 'after': after}
            restarted = False
            try:
                page = read_page(transport.query(name, values), OPERATIONS[name])
            except ThreadsError as error:
                if not (args.command == 'user' and after and after == state.get('ssr_cursor') and
                        error.error in ('operation_rotated', 'envelope_drift')):
                    raise
                # The SSR cursor and Direct query are different sources; try the Direct first page once, retaining seen IDs.
                state['ssr_cursor'] = None
                page = read_page(transport.query(name, {key: value for key, value in values.items() if key != 'after'}),
                                 OPERATIONS[name])
                restarted = True
            page.restarted = restarted
            page.state_updates = {'ssr_cursor': None}
            if args.command == 'user':
                check_access(page, transport, state)
            return page
        result = collect(fetch, limit=args.limit or 10, state=state, initial=initial,
                         since=ctx.get('since'), until=ctx.get('until'),
                         monotonic=OPERATIONS[operation].chronological,
                         commit=output.commit if output else None)
        state = result.pop('state')
        result['context'] = ctx
        if args.command == 'graph' and ctx['relation'] == 'followers':
            result['reported_total'] = state.get('reported_total')
        if state['pending'] or not state['done']:
            handle = CursorStore().save(ctx, state)
            result.update(next_handle=handle, next=None)
        if output:
            result.update(out=str(output.path), count=output.count, results=[])
            if result['code'] == 7 and output.count:
                result.update(code=0, ok=True)
        return finish(result, transport)
    finally:
        if output:
            output.close()


def query_for(ctx, state):
    command = ctx['command']
    if command == 'home':
        following = ctx['feed'] == 'following'
        return 'feed', {'variant': 'following' if following else 'for_you',
            'data': {'pagination_source': 'text_post_feed_following' if following else 'text_post_feed_threads', 'reason': 'cold_start_fetch'}}
    if command == 'user':
        return 'profile.' + ctx['tab'], {'userID': state['user_id'], 'first': 25}
    if command == 'graph':
        return 'graph.' + ctx['relation'], {'userID': state['user_id'], 'first': 20}
    if command == 'search':
        if ctx['type'] == 'users':
            return 'search.accounts', {'query': ctx['query']}
        return 'search.posts', {'query': ctx['query'], 'search_surface': 'tags' if ctx['tag'] else 'default',
                                               'recent': int(ctx['sort'] == 'recent')}
    return 'me.' + ctx['collection'], {}
