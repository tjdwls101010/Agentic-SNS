"""Listing commands: network pages, cached batches and durable page commits."""
from ._cmds_common import continuation, empty_listing, identity, transport
from ._errors import RedditError
from ._listing import select_page
from ._output import CursorStore, OutFile
from ._transport import build_request


def query_context(args):
    defaults = {'home': 'best', 'sub': 'hot', 'user': 'new', 'search': 'relevance'}
    if args.command in defaults:
        args.sort = args.sort or defaults[args.command]
    return {name: getattr(args, name, None) for name in
            ('command', 'target', 'surface', 'query', 'sort', 'time', 'type', 'within', 'nsfw', 'since', 'until')}


def request(args, after=None):
    options = {name: getattr(args, name, None) for name in ('sort', 'time', 'type')}
    options.update(limit=100, after=after)
    target = getattr(args, 'parsed_target', None)
    if args.command == 'me':
        options['type'] = args.surface
    if args.command == 'search':
        target = args.within
        options.update(text=args.query, nsfw=args.nsfw)
    return build_request(args.command, target, **options)


def fetch_page(client, args, after):
    spec = request(args, after)
    for attempt in range(2 if args.command == 'search' else 1):
        try:
            body = client.get(**spec)
            return body[1] if args.command == 'related' else body
        except RedditError as error:
            if error.code != 7:
                raise
            if args.command != 'search' or attempt:
                return empty_listing()
            budget = client.budget
            if client.requests >= client.max_requests or budget['remaining'] <= 0 or budget.get('block'):
                raise RedditError(8, 'Search returned zero items but there is no budget to verify that result.',
                                  'Zero results are unconfirmed; try the query after the budget resets.') from None
    return empty_listing()


def run(args):
    context = query_context(args)
    client = transport(args)
    cursors, state, output = CursorStore(), None, None
    personal = args.command in ('home', 'me')
    account = identity() if personal else None
    if args.after:
        state = cursors.load(args.after, context)['cursor']
        account = state['account']
    if personal and account is None:
        account = identity(client)
        verified = True
    else:
        verified = False
    if args.out:
        output = OutFile(args.out, {**context, 'account': account})
    try:
        if output:
            if output.complete:
                return {'out': args.out, 'count': output.count, 'already_complete': True,
                        'requests': client.requests, 'budget': client.budget}
            if output.state is not None:
                state = output.state
        results, reason, error = [], None, None
        goal = args.limit if args.limit is not None else (None if args.out or getattr(args, 'since', None) else 5)
        initial_count = output.count if output else 0
        pages_seen = set()
        while True:
            try:
                payload = None
                if state is None or (not state['pending'] and state['after'] and not state['window_reached']):
                    if personal and not verified:
                        current = identity(client)
                        if current != account:
                            raise RedditError(4, 'The Reddit account changed since this collection was captured.',
                                              'Start a new query/file for the current account.')
                        verified = True
                    after = state['after'] if state else None
                    if after in pages_seen:
                        reason = 'stalled'
                        break
                    pages_seen.add(after)
                    payload = fetch_page(client, args, after)
                left = (goal - (output.count - initial_count if output else len(results))) if goal is not None else 100
                selected = select_page(payload, state=state, limit=max(1, left), sort=getattr(args, 'sort', None) or 'new',
                                       since=getattr(args, 'since', None), until=getattr(args, 'until', None), account=account)
                state, reason = selected['state'], selected['stop_reason']
                if output:
                    output.commit(selected['results'], state, reason, state=state)
                else:
                    results.extend(selected['results'])
                count = output.count - initial_count if output else len(results)
                if reason in ('exhausted', 'window_reached'):
                    break
                if goal is not None and count >= goal:
                    reason = 'limit_reached'
                    break
            except RedditError as failure:
                if failure.code in (2, 4, 9) or (state is None and failure.code not in (5, 8)):
                    raise
                error = failure
                reason = {5: 'blocked', 8: 'budget'}.get(failure.code, 'query_failure')
                break
        result = {'results': results, 'stop_reason': reason, 'requests': client.requests, 'budget': client.budget,
                  'account': account, 'captured_at': state.get('captured_at') if state else None}
        if state and reason not in ('exhausted', 'window_reached'):
            result['next'] = continuation(args, cursors.save(context, state))
        if output:
            result.update(out=args.out, count=output.count)
        if error:
            result.update(error.as_dict(), code=8 if results or (output and output.count) or error.code == 8 else error.code)
        elif reason == 'stalled':
            result.update(RedditError(8, 'Listing pagination stalled.').as_dict(), code=8)
        elif reason == 'exhausted' and getattr(args, 'since', None):
            result.update(code=8, ok=False, message='The server listing ended before the start of the date window; coverage is incomplete.',
                          fix='Use a narrower recent window; Reddit listings can end before older items.')
        elif not results and not (output and output.count) and args.command != 'related':
            result.update(RedditError(7, 'This selected listing is empty.').as_dict(), code=7)
        if args.command == 'search':
            result['note'] = 'Even two empty searches do not prove absence on Reddit.'
        return result
    finally:
        if output:
            output.close()
