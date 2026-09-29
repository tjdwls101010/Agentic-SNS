"""Connect normalized pages, continuation state and page-committed output; the caller turns a handle into more:."""
from .operations import operation
from .pagination import collect
from ..continuation import CursorStore
from ..export import OutFile
from ..errors import TwitterError
from ..graphql.protocol.transport import Transport, root_at
from ..graphql.responses.pages import normalize_page
from ..graphql.responses.records import build_place, build_user
from ..graphql.responses.thread import completeness


def run(args, context):
    """Fetch and collect one query; `context` is its identity, to which the viewer is attached here."""
    maximum = 40 if args.explicit_limit or args.since or args.out else 10
    transport = Transport(maximum)
    session = transport.session(personal=args.command in ('home', 'me'))
    op, variables = operation(args)
    context['viewer_id'] = session['viewer_id']
    store = CursorStore()
    state = store.load(args.after, context) if args.after else {}
    output = OutFile(args.out, context) if args.out else None
    try:
        if output:
            if args.after:
                raise TwitterError(2, '--out resumes from its own page commits.', 'Repeat the same --out command without --after.')
            state = output.state
            if state.get('metadata', {}).get('user_id'):
                state['user_id'] = state['metadata']['user_id']
            if output.complete:
                return dict(ok=True, results=[], stop_reason=state.get('terminal', 'exhausted'), stored=output.count,
                            shown=0, out=str(output.path), already_complete=True, operation=op, code=0,
                            budget=transport.budget.summary(), fetched_bytes=transport.fetched_bytes)
        card = state.get('card') or state.get('metadata', {}).get('card')
        if args.command in ('user', 'graph'):
            if not state.get('user_id'):
                card = build_user(transport.query('UserByScreenName', {'screen_name': args.targets[0].handle})).to_dict()
                state['user_id'] = card['id']
            variables['userId'] = state['user_id']
        if args.command == 'me' and args.collection == 'likes':
            variables['userId'] = session['viewer_id']
        if args.command == 'community' and not card:
            card = build_place(transport.query('CommunityByRestId', {'communityId': args.targets[0].community_id}), 'community').to_dict()
        state['card'] = card
        metadata = state.setdefault('metadata', {})
        metadata.update(card=card, user_id=state.get('user_id'))

        def fetch(cursor):
            if args.command == 'trends':
                body = transport.query('ExplorePage')
                if args.tab == 'foryou':
                    root = root_at(body, 'initialTimeline.timeline.timeline.instructions')
                else:
                    tab = next((t for t in body.get('timelines', []) if t.get('id') == args.tab), None)
                    timeline_id = tab.get('timeline', {}).get('id') if tab else None
                    if not timeline_id:
                        raise TwitterError(6, 'Explore tab ID is missing.', 'Update the Explore parser.', 'envelope_drift')
                    root = transport.query('GenericTimelineById', {'timelineId': timeline_id})
            else:
                root = transport.query(op, dict(variables, **({'cursor': cursor} if cursor else {})))
            rows, bottom, meta = normalize_page(root, op, args, cursor)
            if card and card.get('is_protected') and card.get('following') is False and not rows:
                raise TwitterError(9, 'This profile is protected and you do not follow it.', 'Open a profile accessible to this account.', 'protected')
            if args.command == 'community' and args.tab == 'about':
                meta['not_paginable'] = True
            meta.update(card=card, user_id=state.get('user_id'))
            return rows, bottom, meta

        result = collect(fetch, limit=args.limit, state=state, users=args.command in ('graph', 'reposts') or args.type == 'users',
                         since=args.since, until=args.until, monotonic=op == 'UserTweets', out=output)
        result.update(operation=op, budget=transport.budget.summary(), fetched_bytes=transport.fetched_bytes,
                      warnings=transport.warnings, viewer_id=session['viewer_id'], viewer_changed=transport.changed_viewer,
                      shown=len(result['results']))
        if args.command == 'post' and len(args.targets) == 1:
            result.update(completeness(result['results'], args.targets[0].tweet_id, result))
        if args.command == 'about':
            resolved = {row['screen_name'].lower() for row in result['results']}
            result['unresolved'] = [t.handle for t in args.targets if t.handle.lower() not in resolved]
        if output:
            result.update(out=str(output.path), stored=output.count)
        remaining = result['state'].get('pending') or not result['state'].get('terminal')
        if remaining and not output and op != 'TweetResultsByRestIds' and args.command not in ('about', 'trends') and not (args.command == 'community' and args.tab == 'about'):
            number = store.save(context, result['state'])
            result['next'] = None
            result['next_handle'] = number
        if not result['results'] and not result.get('other_items') and not output and result['code'] == 0 and args.command != 'trends':
            result.update(code=7, error='empty', message='The valid response contained no matching items.', fix='Try a different target or date window.')
        return result
    finally:
        if output:
            output.close()
