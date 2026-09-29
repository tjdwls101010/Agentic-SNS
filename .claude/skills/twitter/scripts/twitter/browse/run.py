"""Connect normalized pages, continuation state and page-committed output; the caller turns a handle into more:."""
from .pagination import collect
from ..continuation import CursorStore, valid as valid_handle
from ..export import OutFile
from ..errors import TwitterError
from ..graphql.protocol.transport import Transport
from ..graphql.responses.pages import normalize_page

__all__ = ['run', 'valid_handle']  # valid_handle: cli.py checks --after before any file or request


def run(args, context, op, variables, *, rows, personal=False, prepare=None, fetch=None, finish=None, continuable=True,
        sparse=False):
    """Fetch and collect one query.

    `context` is the query's identity, to which the viewer is attached here. `rows` is the kind of record the pages hold; `personal` rechecks the viewer cookie; `prepare(transport, args, session, state, variables, card)` makes the requests needed before the first page and returns the card; `fetch(transport, args)` replaces the single request for a first page that takes more; `finish(result, args)` adds to the collected result; a query that is not `continuable` gets no handle and is not paged further; `sparse` account lists stop after three empty pages.
    """
    transport = Transport(10)
    session = transport.session(personal=personal)
    context['viewer_id'] = session['viewer_id']
    store = CursorStore()
    state = store.load(args.after, context) if args.after else {}
    explicit = state.get('explicit_limit', True) if args.after and args.limit == state.get('limit') else args.explicit_limit
    transport.budget.maximum = 40 if explicit or args.since or args.out else 10
    output = OutFile(args.out, context) if args.out else None
    try:
        if output:
            state = output.state
            if state.get('metadata', {}).get('user_id'):
                state['user_id'] = state['metadata']['user_id']
            if output.complete:
                return dict(ok=True, results=[], stop_reason=state.get('terminal', 'exhausted'), stored=output.count,
                            shown=0, out=str(output.path), already_complete=True, operation=op, code=0,
                            budget=transport.budget.summary(), fetched_bytes=transport.fetched_bytes)
        card = state.get('card') or state.get('metadata', {}).get('card')
        if prepare:
            card = prepare(transport, args, session, state, variables, card)
        state['card'] = card
        metadata = state.setdefault('metadata', {})
        metadata.update(card=card, user_id=state.get('user_id'))
        focal = args.targets[0].tweet_id if getattr(args, 'targets', None) else None

        def page(cursor):
            if fetch:
                root = fetch(transport, args)
            else:
                root = transport.query(op, dict(variables, **({'cursor': cursor} if cursor else {})))
            records, bottom, meta = normalize_page(root, op, rows, focal, cursor)
            if card and card.get('is_protected') and card.get('following') is False and not records:
                raise TwitterError(9, 'This profile is protected and you do not follow it.', 'Open a profile accessible to this account.', 'protected')
            if not continuable:
                meta['not_paginable'] = True
            meta.update(card=card, user_id=state.get('user_id'))
            return records, bottom, meta

        result = collect(page, limit=args.limit, state=state, users=sparse,
                         since=args.since, until=args.until, monotonic=op == 'UserTweets', out=output)
        result.update(operation=op, budget=transport.budget.summary(), fetched_bytes=transport.fetched_bytes,
                      warnings=transport.warnings, viewer_id=session['viewer_id'], viewer_changed=transport.changed_viewer,
                      shown=len(result['results']))
        if finish:
            finish(result, args)
        if output:
            result.update(out=str(output.path), stored=output.count)
        remaining = result['state'].get('pending') or not result['state'].get('terminal')
        if remaining and not output and continuable:
            result['next'] = None
            result['next_handle'] = store.save(context, dict(result['state'], limit=args.limit, explicit_limit=explicit))
        if not result['results'] and not result.get('other_items') and not output and result['code'] == 0 and rows != 'trend':
            result.update(code=7, error='empty', message='The valid response contained no matching items.', fix='Try a different target or date window.')
        return result
    finally:
        if output:
            output.close()
