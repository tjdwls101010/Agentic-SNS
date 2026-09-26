"""Search posts, people, pages and groups in the server's result order."""
from urllib.parse import quote

from facebook.errors import FacebookError
from facebook.graphql.records import entity as _entity
from facebook.graphql.records.connection import connection_has_items, find_page_info, search_records
from facebook.graphql.registry import build_variables, get_query
from facebook.reading.paging import page_options, paginate


def search(args, transport, state, commit):
    spec = get_query('search')
    variables = build_variables(spec)
    variables['args']['text'] = args.target
    variables['args']['experience']['type'] = _entity.SEARCH_EXPERIENCE_TYPES[args.type]

    def fetch(cursor):
        raw = transport.query('search', {**variables, 'cursor': cursor},
                              referer='https://www.facebook.com/search/' + args.type + '/?q=' + quote(args.target))
        records = search_records(raw, args.type)
        if not records and connection_has_items(raw, spec.connection_key):
            raise FacebookError(6, 'A nonempty search connection contains no readable results.', 'Run refresh, then retry.')
        return records, find_page_info(raw, spec.connection_key)

    return paginate(fetch, **page_options(args, state, commit))
