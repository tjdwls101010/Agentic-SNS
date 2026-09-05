"""Post-reading commands; one shared pagination path preserves server order."""
from datetime import datetime, time, date

from _errors import FacebookError
from _paginate import paginate, find_page_info, connection_has_items
from _parse import parse_story_nodes, iter_json_objects
from _post import build_post
from _registry import get_query, FEED_SORT_TOKENS, GROUP_SORT_TOKENS
from _resolve import resolve_profile_id, resolve_group_id, resolve_story_id


def posts_from_raw(raw, source):
    parsed = parse_story_nodes([raw])
    return [build_post(parsed.stories[key], source=source, captured_at=datetime.now().astimezone(),
                       include_raw=False).to_dict() for key in parsed.top_level_ids()]


def page_options(args, state, commit):
    return dict(limit=args.limit, since=args.since, until=args.until,
                cursor=state.get('cursor'), pending=state.get('pending'),
                seen=state.get('seen'), commit=commit, page_limit=bool(args.out))


def fetch_post_story(transport, url):
    raw = transport.query('post', {'storyID': resolve_story_id(transport, url)}, referer=url)
    parsed = parse_story_nodes([raw])
    for chunk in iter_json_objects([raw]):
        if chunk.get('path'):
            continue
        data = chunk.get('data')
        if isinstance(data, dict):
            root = data.get('node_v2') or data.get('node') or data.get('story')
            if isinstance(root, dict):
                identity = (root.get('feedback') or {}).get('id')
                if identity is not None and str(identity) in parsed.stories:
                    return parsed.stories[str(identity)]
    raise FacebookError(6, 'The post response contains no readable post.', 'Run refresh, then retry the permalink.')


def run(args, transport, *, state=None, commit=None):
    state = state or {}
    if args.command == 'post':
        from _cmds_people import comments
        from _paginate import in_window
        story = fetch_post_story(transport, args.target)
        post = build_post(story, source='permalink', captured_at=datetime.now().astimezone(),
                          include_raw=False).to_dict()
        if not in_window(post, args.since, args.until):
            result = dict(ok=True, results=[], stop_reason='exhausted')
        else:
            result = comments(args, transport, state={}, commit=None, story=story, first_batch=True)
            result['results'].insert(0, post)
            result['continuation_command'] = 'comments'
        if commit and result['ok']:
            commit(result['results'], {'exhausted': True}, 'exhausted')
        return result
    variables = {}
    referer = getattr(args, 'target', None)
    if args.command == 'feed':
        key, source = 'newsfeed', 'newsfeed'
        variables.update(FEED_SORT_TOKENS[args.sort])
    elif args.command == 'profile':
        key, source = 'timeline', 'timeline'
        variables['id'] = resolve_profile_id(transport, args.target)
        for flag, field, clock in (('since', 'afterTime', time.min), ('until', 'beforeTime', time.max)):
            value = getattr(args, flag)
            if value:
                variables[field] = int(datetime.combine(date.fromisoformat(value), clock).astimezone().timestamp())
    else:
        key, source = 'group', 'group'
        variables.update(id=resolve_group_id(transport, args.target), sortingSetting=GROUP_SORT_TOKENS[args.sort])
    spec = get_query(key)

    def fetch(cursor):
        raw = transport.query(key, {**variables, spec.cursor_var: cursor}, referer=referer)
        records = posts_from_raw(raw, source)
        if not records and connection_has_items(raw, spec.connection_key):
            raise FacebookError(6, 'A nonempty feed connection contains no readable posts.', 'Run refresh, then retry.')
        return records, find_page_info(raw, spec.connection_key)

    result = paginate(fetch, **page_options(args, state, commit))
    if args.since or args.until:
        result['window_mode'] = 'server' if args.command == 'profile' else 'client'
        result['window_complete'] = args.command == 'profile' and result['stop_reason'] == 'exhausted'
    return result
