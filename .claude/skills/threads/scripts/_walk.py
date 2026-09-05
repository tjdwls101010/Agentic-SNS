"""Anchored connection paths; a missing pagination contract is never exhaustion."""
from dataclasses import dataclass, field

from ._entities import build_user
from ._errors import ThreadsError
from ._models import build_post


def drift(message):
    return ThreadsError(6, message, 'Run refresh; the expected response shape changed.', error='envelope_drift')


def at(value, path):
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            raise drift('Missing response path: ' + path)
        value = value[key]
    return value


@dataclass
class Page:
    records: list = field(default_factory=list)
    cursor: str | None = None
    has_next: bool = False
    stop: str = 'exhausted'
    groups: list = field(default_factory=list)
    reported_total: int | None = None


def read_page(response, operation):
    data = response.get('data', response)
    user_nodes = False
    policy, item_path = 'relay', 'thread_items'
    if operation == 'BarcelonaFeedDirectQuery':
        root, item_path = 'feedData', 'text_post_app_thread.thread_items'
    elif operation.startswith('BarcelonaProfile') and 'Tab' in operation:
        root = 'mediaData'
    elif operation == 'BarcelonaSearchResultsQuery':
        root, item_path = 'searchResults', 'thread.thread_items'
    elif operation == 'useBarcelonaAccountSearchGraphQLDataSourceQuery':
        root, policy, user_nodes = 'xdt_api__v1__users__search_connection', 'single_batch', True
    elif 'Friendships' in operation:
        user_nodes = True
        if 'Followers' in operation:
            root, policy = 'user.followers', 'capped'
        elif 'Refetchable' in operation:
            root, policy = 'fetch__XDTUserDict.following', 'offset'
        else:
            root, policy = 'user.following', 'offset'
    elif operation in ('BarcelonaLikedPageViewerQuery', 'BarcelonaSavedPageViewerQuery'):
        root, policy = 'xdt_text_app_viewer.' + ('liked_media' if 'Liked' in operation else 'saved_media'), 'single_batch'
    else:
        raise drift('Unsupported connection operation: ' + operation)
    connection = at(data, root)
    if not isinstance(connection, dict) or not isinstance(connection.get('edges'), list):
        raise drift('Expected explicit edges at ' + root)
    page = Page(stop={'capped': 'server_capped', 'single_batch': 'not_paginable'}.get(policy, 'exhausted'))
    if policy in ('relay', 'offset'):
        info = connection.get('page_info')
        if not isinstance(info, dict) or type(info.get('has_next_page')) is not bool:
            raise drift('Expected page_info.has_next_page at ' + root)
        page.has_next, page.cursor = info['has_next_page'], info.get('end_cursor')
        if page.has_next and (not isinstance(page.cursor, str) or not page.cursor):
            raise drift('A continuing page must provide a cursor.')
        if policy == 'offset' and page.has_next and not page.cursor.isdigit():
            raise drift('Following cursor must be an offset string.')
    counts = data.get('counts') or {}
    page.reported_total = counts.get('followers' if policy == 'capped' else 'following')
    for edge in connection['edges']:
        node = at(edge, 'node')
        if not isinstance(node, dict):
            raise drift('Expected an edge node.')
        raw_items = [node] if user_nodes else at(node, item_path)
        if not isinstance(raw_items, list):
            raise drift('Expected thread items.')
        group = []
        for raw in raw_items:
            item = build_user(raw) if user_nodes else build_post(at(raw, 'post'))
            if item is None:
                raise drift('Result node has no usable identity.')
            group.append(item.to_dict())
        page.groups.append(group)
        page.records.extend(group)
    return page
