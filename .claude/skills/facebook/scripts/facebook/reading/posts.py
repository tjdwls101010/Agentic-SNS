"""Post-reading commands; one shared pagination path preserves server order."""
from datetime import datetime, time, date

from facebook.errors import FacebookError
from facebook.graphql.records import post_page, post_record
from facebook.graphql.registry import get_query, FEED_SORT_TOKENS, GROUP_SORT_TOKENS
from facebook.graphql.resolve import resolve_profile_id, resolve_group_id
from facebook.outcome import ISSUES
from facebook.reading.comments import comments, fetch_post_story
from facebook.reading.paging import page_options, paginate


def run(args, transport, *, state=None, commit=None):
    state = state or {}
    if args.command == 'post':
        story, issues = fetch_post_story(transport, args.target)
        post = post_record(story, source='permalink', captured_at=datetime.now().astimezone())
        result = comments(args, transport, state={}, commit=None, story=story, first_batch=True)
        result['results'].insert(0, post)
        result['issues'] = issues
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

    issues = []

    def fetch(cursor):
        raw = transport.query(key, {**variables, spec.cursor_var: cursor}, referer=referer)
        page = post_page(raw, source=source, connection_key=spec.connection_key,
                         captured_at=datetime.now().astimezone())
        if not page.records and page.has_items:
            raise FacebookError(6, 'A nonempty feed connection contains no readable posts.', 'Run refresh, then retry.')
        issues.extend(page.issues)
        page_notes.extend(ISSUES.get(issue, issue) for issue in page.issues)
        return page.records, page.page_info

    page_notes = []

    def commit_with_notes(records, cursor, reason, skipped=()):
        commit(records, cursor, reason, skipped, list(dict.fromkeys(page_notes)))
        page_notes.clear()

    newest_first = args.command in ('feed', 'group') and args.sort == 'recent'
    skip_sponsored = args.command == 'feed' and not args.include_sponsored
    options = page_options(args, state, commit_with_notes if commit else None)
    result = paginate(fetch, **options, newest_first=newest_first, skip_sponsored=skip_sponsored)
    result['issues'] = issues
    return result
