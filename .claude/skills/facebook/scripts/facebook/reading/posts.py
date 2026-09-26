"""Post-reading commands; one shared pagination path preserves server order."""
from datetime import datetime, time, date

from facebook.errors import FacebookError
from facebook.graphql.records.connection import find_page_info, connection_has_items
from facebook.graphql.records.post import build_post, posts_from_raw
from facebook.graphql.registry import get_query, FEED_SORT_TOKENS, GROUP_SORT_TOKENS
from facebook.graphql.resolve import resolve_profile_id, resolve_group_id
from facebook.reading.comments import comments, fetch_post_story
from facebook.reading.paging import page_options, paginate


def run(args, transport, *, state=None, commit=None):
    state = state or {}
    if args.command == 'post':
        story = fetch_post_story(transport, args.target)
        post = build_post(story, source='permalink', captured_at=datetime.now().astimezone(),
                          include_raw=False).to_dict()
        result = comments(args, transport, state={}, commit=None, story=story, first_batch=True)
        result['results'].insert(0, post)
        result['continuation_command'] = 'comments'
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
        order = 'server' if args.command == 'profile' else 'chronological' if args.sort == 'recent' else 'ranked'
        result['window'] = {'order': order, 'since': args.since, 'until': args.until}
    return result
