"""Connect normalized pages, continuation state and page-committed output."""
import shlex
from pathlib import Path
from ._cmds_browse import operation
from ._entities import build_user, build_place, build_trend
from ._models import build_tweet
from ._walk import walk
from ._thread import thread_records, completeness
from ._listing import collect
from ._output import CursorStore, OutFile
from ._transport import Transport, root_at
from ._errors import TwitterError


def context_for(args, op, viewer):
    targets = [t.handle.lower() if t.handle else t.tweet_id or t.list_id or t.community_id for t in args.targets] if hasattr(args, 'targets') else args.target
    return dict(command=args.command, target=targets, operation=op, viewer_id=viewer,
                **{key: getattr(args, key) for key in ('tab', 'sort', 'feed', 'type', 'scope', 'relation', 'collection', 'since', 'until')})


def more_command(args, number):
    parts = ['python3', str(Path(__file__).with_name('twitter.py')), args.command]
    if args.target:
        parts.extend(args.target if isinstance(args.target, list) else [args.target])
    if args.relation:
        parts.append(args.relation)
    if args.collection:
        parts.append(args.collection)
    for key in ('tab', 'sort', 'feed', 'type', 'scope', 'since', 'until'):
        value = getattr(args, key)
        if value is not None:
            parts.extend(['--in' if key == 'scope' else '--' + key, value])
    parts.extend(['--limit', str(args.limit), '--after', str(number)])
    return shlex.join(parts)


def normalize_page(root, op, args, cursor=None):
    if op in ('UserByScreenName', 'UsersByScreenNames', 'TweetResultsByRestIds', 'ListByRestId', 'CommunityByRestId'):
        nodes = root if isinstance(root, list) else [root]
        records = []
        for node in nodes:
            if not node or node.get('__typename') in ('UserUnavailable', 'TweetTombstone'):
                continue
            item = (build_user(node) if op.startswith('User') else build_tweet(node) if op.startswith('Tweet') else
                    build_place(node, 'list' if op == 'ListByRestId' else 'community'))
            if item:
                records.append(item.to_dict())
        return records, None, dict(not_paginable=True)
    page = walk(root)
    if op == 'TweetDetail':
        rows, metadata = thread_records(page, args.targets[0].tweet_id, continuing=bool(cursor))
    else:
        rows, metadata = [], {}
        desired = 'user' if op in ('Following', 'Followers', 'BlueVerifiedFollowers', 'FollowersYouKnow', 'Retweeters', 'ListMembers', 'CommunityAboutTimeline') or args.command == 'search' and args.type == 'users' else 'trend' if args.command == 'trends' else 'tweet'
        for entry in page.entries:
            if entry.kind not in (('trend', 'event') if desired == 'trend' else (desired,)):
                if entry.kind != 'cursor':
                    page.other_items += 1
                continue
            item = build_tweet(entry.node, entry.pinned) if entry.kind == 'tweet' else build_user(entry.node) if entry.kind == 'user' else build_trend(entry.node, entry.entry_id, entry.kind == 'event')
            if not item:
                continue
            row = item.to_dict()
            if row.get('promoted'):
                page.promoted += 1
                continue
            if entry.module_id:
                row['module'] = entry.module_id
                if entry.module_id.startswith(('communityModerators', 'communityMembers')):
                    row['role'] = 'moderator' if entry.module_id.startswith('communityModerators') else 'member'
            if entry.social_context.get('landingUrl'):
                landing = entry.social_context['landingUrl']
                row['community_url'] = landing.get('url') if isinstance(landing, dict) else landing
            rows.append(row)
        if args.command == 'trends':
            metadata.update(other_items=page.other_items, promoted=page.promoted, not_paginable=True)
    metadata['terminated'] = page.terminated
    return rows, page.bottom_cursor, metadata


def run(args):
    maximum = 40 if args.explicit_limit or args.since or args.out else 10
    transport = Transport(maximum)
    session = transport.session(personal=args.command in ('home', 'me'))
    op, variables = operation(args)
    context = context_for(args, op, session['viewer_id'])
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
                            shown=0, out=str(output.path), already_complete=True, operation=op, code=0)
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
            result['next'] = more_command(args, number)
            result['next_handle'] = number
        if not result['results'] and not result.get('other_items') and not output and result['code'] == 0 and args.command != 'trends':
            result.update(code=7, error='empty', message='The valid response contained no matching items.', fix='Try a different target or date window.')
        return result
    finally:
        if output:
            output.close()
