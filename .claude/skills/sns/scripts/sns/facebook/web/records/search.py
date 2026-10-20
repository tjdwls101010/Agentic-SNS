"""Search results: posts, and people, pages and groups as entity records, in the connection's order.

Only result wrappers are followed from a result root, so a post's author or a group's admin is never mistaken for a
result. The requested vertical decides the kind of a User node (Facebook sends pages as User in the pages vertical);
Group is unambiguous, and the groups vertical keeps only groups. A top search keeps the connection's index order even
when deferred pieces arrive out of order.
"""
import json

from sns.facebook.web.records import posts
from sns.facebook.web.records.moment import iso
from sns.facebook.web.records.parse import pieces, unplaced

FIELDS = {
    'kind': 'string — person | page | group',
    'id': 'string — numeric id; the profile, about or group command\'s argument',
    'name': 'string | null — display name',
    'url': 'string | null — the entity\'s Facebook URL; two results with one name are different entities',
    'created_at': 'null — an entity has no creation time here',
    'verified': 'boolean | null — the verified badge; null when Facebook did not say',
    'captured_at': 'string — ISO-8601 UTC time this tool received it; changes every run',
}
VERTICALS = {'top': 'GLOBAL_SEARCH', 'posts': 'POSTS_TAB', 'people': 'PEOPLE_TAB', 'pages': 'PAGES_TAB',
             'groups': 'GROUPS_TAB'}
def filters(*, recent=False, since=None, until=None, today=None):
    """Facebook's search filter strings: recent_posts, and creation_time for a day range (observed in P2)."""
    found = []
    if recent:
        found.append(json.dumps({'name': 'recent_posts', 'args': ''}, separators=(',', ':')))
    if since or until:
        start, end = since or FIRST_DAY, until or today
        dates = {'start_year': start[:4], 'start_month': start[:7], 'end_year': end[:4], 'end_month': end[:7],
                 'start_day': start, 'end_day': end}
        found.append(json.dumps({'name': 'creation_time', 'args': json.dumps(dates, separators=(',', ':'))},
                                separators=(',', ':')))
    return found


FIRST_DAY = '2004-02-04'  # Facebook's first day: an open start of a date filter
WRAPPERS = frozenset({'node', 'result', 'entity', 'profile', 'group', 'page', 'user', 'rendering_strategy', 'view_model',
                      'result_rendering_strategies'})
# A top search lists entities in titled modules (groups, pages, people); the module's see-more type names their kind,
# which the entities do not (a page arrives as a User). Observed 2026-10-21.
MODULE_KINDS = {'browse_type_group': 'group', 'browse_type_profile_with_biz_tools': 'page', 'browse_type_user': 'person'}
CONNECTIONS = ('results', 'search_results')
_KIND_OF_VERTICAL = {'people': 'person', 'pages': 'page', 'groups': 'group'}


def _entity_shaped(obj):
    return (isinstance(obj, dict) and obj.get('__typename') in ('User', 'Page', 'Group') and obj.get('id') is not None
            and isinstance(obj.get('name'), str) and isinstance(obj.get('url'), str))


def _module_kind(node):
    model = node.get('view_model')
    more = model.get('see_more_model') if isinstance(model, dict) else None
    return MODULE_KINDS.get(more.get('type')) if isinstance(more, dict) else None


def _result_entities(node, kind=None):
    """(entity node, the kind its module names or None) for each result entity under `node`."""
    if not isinstance(node, dict):
        return
    if _entity_shaped(node):
        yield node, kind
        return
    if node.get('__typename') in ('Story', 'Comment') or 'feedback' in node:
        return
    kind = _module_kind(node) or kind
    # 성진: 아는 결과 래퍼만 따라간다. 캡처에서 다른 래퍼가 보이면 WRAPPERS에 더할 것
    for key, child in node.items():
        if key in WRAPPERS:
            for item in child if isinstance(child, list) else [child]:
                yield from _result_entities(item, kind)


def _result_tail(path):
    """The part of a piece's path after the results connection, or None when it is not inside one."""
    indices = [i for i, key in enumerate(path) if key in CONNECTIONS]
    return path[indices[-1] + 1:] if indices else None


def _is_result_piece(path, data):
    tail = _result_tail(path or [])
    return tail is not None and (not tail or (len(tail) >= 1 and tail[0] in ('edges', 'nodes')))


def edges(chunks):
    """(connection index, its result edges) in index order, deferred pieces included; arrival order does not decide."""
    positions = {}

    def connection(value):
        for key in ('edges', 'nodes'):
            for index, item in enumerate(value.get(key) or []):
                positions.setdefault(index, []).append(item if key == 'edges' else {'node': item})

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in CONNECTIONS and isinstance(child, dict):
                    connection(child)
                elif key != 'incremental':
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for path, data, _, _ in pieces(chunks):
        tail = _result_tail(path or [])
        if not path:
            walk(data)
        elif tail is not None:
            if not tail and isinstance(data, dict):
                connection(data)
            elif len(tail) == 1 and tail[0] in ('edges', 'nodes') and isinstance(data, list):
                connection({tail[0]: data})
            elif (len(tail) >= 2 and tail[0] in ('edges', 'nodes') and type(tail[1]) is int
                  and all(type(key) is int or key in WRAPPERS for key in tail[2:])):
                positions.setdefault(tail[1], []).append({'node': data})
    for index in sorted(positions):
        yield index, positions[index]


def _entity(node, vertical, captured_at, module_kind=None):
    typename = node.get('__typename')
    kind = {'Group': 'group', 'Page': 'page'}.get(typename, module_kind or _KIND_OF_VERTICAL.get(vertical, 'person'))
    return {'kind': kind, 'id': str(node['id']), 'name': node['name'], 'url': node['url'],
            'created_at': None, 'verified': node['is_verified'] if isinstance(node.get('is_verified'), bool) else None,
            'captured_at': iso(captured_at)}


def _candidates(edge, vertical, captured_at, module, seen):
    """The records one result edge holds that are not already listed (seen is updated)."""
    candidates, found = [], []
    if vertical in ('top', 'posts'):
        candidates += posts.top_level([{'data': edge}], source='search', captured_at=captured_at)[0]
    if vertical != 'posts':
        for node, module_kind in _result_entities(edge, module):
            if vertical == 'groups' and node.get('__typename') != 'Group':
                continue
            candidates.append(_entity(node, vertical, captured_at, module_kind))
    for record in candidates:
        key = (record.get('kind') or 'post', record['id'])
        if key not in seen:
            seen.add(key)
            found.append(record)
    return found


def results(chunks, *, vertical, captured_at):
    """(records in result order, response issues)."""
    records, seen = [], set()
    for _, pieces in edges(chunks):
        # an entity delivered in a later piece of its module takes the kind the module's own piece names
        module = next((kind for kind in (_module_kind(p.get('rendering_strategy') or {}) for p in pieces
                                         if isinstance(p, dict)) if kind), None)
        for edge in pieces:
            records += _candidates(edge, vertical, captured_at, module, seen)
    if vertical in ('top', 'posts'):
        # Posts whose pieces are spread over the response are merged across it; replace each with its merged form.
        merged = {r['id']: r for r in posts.top_level(chunks, source='search', captured_at=captured_at)[0]}
        records = [merged.get(r['id'], r) if 'kind' not in r else r for r in records]
        records += [r for key, r in merged.items() if ('post', key) not in seen]
    touched, issues = unplaced(chunks, consumed=_is_result_piece)
    return records, list(dict.fromkeys(issues + [reason for reasons in touched.values() for reason in reasons]))
