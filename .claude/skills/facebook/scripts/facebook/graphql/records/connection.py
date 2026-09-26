"""Read a connection's pagination metadata, item presence and result order from a raw response."""
import json
from datetime import datetime

from facebook.graphql.transport import iter_chunks
from facebook.graphql.records import entity as _entity
from facebook.graphql.records.parse import iter_json_objects
from facebook.graphql.records.post import posts_from_raw


def find_page_info(raw, connection_key):
    """Read only this connection's inline or path-addressed deferred metadata."""
    def walk(obj):
        if isinstance(obj, dict):
            connection = obj.get(connection_key)
            if isinstance(connection, dict) and isinstance(connection.get('page_info'), dict):
                return connection['page_info']
            for value in obj.values():
                found = walk(value)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for value in obj:
                found = walk(value)
                if found is not None:
                    return found
        return None
    found = None
    for chunk in iter_chunks(raw):
        path, data = chunk.get('path'), chunk.get('data')
        if isinstance(path, list) and path and path[-1] == connection_key and isinstance(data, dict):
            if isinstance(data.get('page_info'), dict):
                found = data['page_info']
        found = walk(data) or found
    return found


def connection_has_items(raw, key):
    """Distinguish an empty continuation page from nonempty data a model could not parse."""
    for chunk in iter_chunks(raw):
        path = chunk.get('path') or []
        data = chunk.get('data')
        if path and path[-1] == key and isinstance(data, dict) and (data.get('edges') or data.get('nodes')):
            return True
        if key in path and any(part in ('edges', 'nodes') for part in path) and chunk.get('data'):
            return True
        stack = [chunk.get('data')]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                connection = item.get(key)
                if isinstance(connection, dict) and (connection.get('edges') or connection.get('nodes')):
                    return True
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
    return False


def search_edges(raw):
    # Connection indices, rather than deferred arrival times, define result order.
    positions = {}
    wrappers = {'node', 'result', 'entity', 'profile', 'group', 'page', 'user',
                'rendering_strategy', 'view_model'}

    def connection(value):
        for key in ('edges', 'nodes'):
            for index, item in enumerate(value.get(key) or []):
                positions.setdefault(index, []).append(item if key == 'edges' else {'node': item})

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('results', 'search_results') and isinstance(child, dict):
                    connection(child)
                elif key != 'incremental':
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for envelope in iter_json_objects([raw]):
        for chunk in [envelope, *(envelope.get('incremental') or [])]:
            if not isinstance(chunk, dict):
                continue
            path, data = chunk.get('path') or [], chunk.get('data')
            indices = [i for i, key in enumerate(path) if key in ('results', 'search_results')]
            if not path:
                walk(data)
            elif indices:
                tail = path[indices[-1] + 1:]
                if not tail and isinstance(data, dict):
                    connection(data)
                elif len(tail) == 1 and tail[0] in ('edges', 'nodes') and isinstance(data, list):
                    connection({tail[0]: data})
                elif (len(tail) >= 2 and tail[0] in ('edges', 'nodes') and type(tail[1]) is int
                      and all(type(key) is int or key in wrappers for key in tail[2:])):
                    positions.setdefault(tail[1], []).append({'node': data})
    for index in sorted(positions):
        yield from positions[index]


def search_records(raw, search_type, captured_at=None):
    """One search page's posts and entities; a top search keeps the connection's mixed order."""
    records = posts_from_raw(raw, 'search', captured_at) if search_type in ('top', 'posts') else []
    if search_type != 'posts':
        records += [r.to_dict() for r in _entity.build_entities(
            [raw], search_type=search_type, captured_at=captured_at or datetime.now().astimezone())]
    if search_type == 'top':
        by_id = {r['id']: r for r in records}
        ordered = []
        emitted = set()
        for edge in search_edges(raw):
            single = json.dumps({'data': {'results': {'edges': [edge]}}}).encode()
            candidates = posts_from_raw(single, 'search', captured_at) + [r.to_dict() for r in _entity.build_entities(
                [single], search_type='top', captured_at=captured_at or datetime.now().astimezone())]
            for record in candidates:
                if record['id'] not in emitted:
                    ordered.append(by_id.pop(record['id'], record))
                    emitted.add(record['id'])
        records = ordered + list(by_id.values())
    return records
