"""Anchored connection paths; a missing pagination contract is never exhaustion."""
from ..errors import changed
from ..model import Page
from .operations import CAPPED, OFFSET, RELAY, SINGLE_BATCH, SSR_ONLY
from .normalize import build_post, build_user


def drift(message):
    return changed(message)


def at(value, path):
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            raise drift('Missing response path: ' + path)
        value = value[key]
    return value


def read_page(response, operation):
    """One page of a declared connection: its records grouped by edge, and its continuation."""
    data = response.get('data', response)
    if operation.connection is None:
        raise drift('Unsupported connection operation: ' + operation.id)
    root, item_path, policy = operation.connection, operation.items, operation.pagination
    user_nodes = item_path is None
    connection = at(data, root)
    if not isinstance(connection, dict) or not isinstance(connection.get('edges'), list):
        raise drift('Expected explicit edges at ' + root)
    page = Page(stop={CAPPED: 'server_capped', SINGLE_BATCH: 'not_paginable', SSR_ONLY: 'not_paginable'}.get(policy, 'exhausted'))
    if policy in (RELAY, OFFSET):
        info = connection.get('page_info')
        if not isinstance(info, dict) or type(info.get('has_next_page')) is not bool:
            raise drift('Expected page_info.has_next_page at ' + root)
        page.has_next, page.cursor = info['has_next_page'], info.get('end_cursor')
        if page.has_next and (not isinstance(page.cursor, str) or not page.cursor):
            raise drift('A continuing page must provide a cursor.')
        if policy == OFFSET and page.has_next and not page.cursor.isdigit():
            raise drift('Following cursor must be an offset string.')
    counts = data.get('counts') or {}
    page.reported_total = counts.get('followers' if policy == CAPPED else 'following')
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
