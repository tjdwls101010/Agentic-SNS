"""Search posts, people, pages and groups in the server's result order."""
from urllib.parse import quote

from facebook.errors import FacebookError
from datetime import datetime

from facebook.graphql.records import entity as _entity
from facebook.graphql.records import search_page
from facebook.graphql.registry import build_variables, get_query
from facebook.outcome import ISSUES
from facebook.reading.paging import page_options, paginate


def search(args, transport, state, commit):
    spec = get_query('search')
    variables = build_variables(spec)
    variables['args']['text'] = args.target
    variables['args']['experience']['type'] = _entity.SEARCH_EXPERIENCE_TYPES[args.type]

    issues = []

    def fetch(cursor):
        raw = transport.query('search', {**variables, 'cursor': cursor},
                              referer='https://www.facebook.com/search/' + args.type + '/?q=' + quote(args.target))
        page = search_page(raw, search_type=args.type, captured_at=datetime.now().astimezone(),
                           connection_key=spec.connection_key)
        if not page.records and page.has_items:
            raise FacebookError(6, 'A nonempty search connection contains no readable results.', 'Run refresh, then retry.')
        issues.extend(page.issues)
        page_notes.extend(ISSUES.get(issue, issue) for issue in page.issues)
        return page.records, page.page_info

    page_notes = []

    def commit_with_notes(records, cursor, reason, skipped=()):
        commit(records, cursor, reason, skipped, list(dict.fromkeys(page_notes)))
        page_notes.clear()

    result = paginate(fetch, **page_options(args, state, commit_with_notes if commit else None))
    result['issues'] = issues
    return result
