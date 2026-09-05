"""Pure normalization and ordered graph assembly for Reddit comment trees."""
import json
import re
import time

from ._errors import RedditError
from ._models import build_comment, fullname


def walk_things(response):
    """Yield validated (thing, nested depth); malformed nested data is error 6."""
    def require(condition):
        if not condition:
            raise RedditError(6, 'Malformed nested Reddit thread response.')

    stack = [(response, 0)]
    while stack:
        item, depth = stack.pop()
        if isinstance(item, list):
            stack.extend((child, depth) for child in reversed(item))
            continue
        require(isinstance(item, dict))
        kind, data = item.get('kind'), item.get('data')
        if kind is None and 'json' in item:
            envelope = item['json']
            require(isinstance(envelope, dict) and not envelope.get('errors'))
            data = envelope.get('data')
            require(isinstance(data, dict) and isinstance(data.get('things'), list))
            stack.append((data['things'], depth))
            continue
        require(kind in ('Listing', 't1', 't3', 'more') and isinstance(data, dict))
        if kind == 'Listing':
            require(isinstance(data.get('children'), list))
            stack.append((data['children'], depth))
            continue
        require(isinstance(data.get('parent_id', ''), str))
        if kind == 'more':
            ids = data.get('children')
            require(isinstance(ids, list) and all(isinstance(i, str) and
                    re.fullmatch(r'(?:t1_)?[A-Za-z0-9]+', i) for i in ids))
            require(type(data.get('count', 0)) is int and data.get('count', 0) >= 0)
        else:
            require(isinstance(data.get('id', ''), str) and isinstance(data.get('name', ''), str))
            require(bool(re.fullmatch(kind + r'_[A-Za-z0-9]+', fullname(data, kind))))
        if kind == 't1':
            require(type(data.get('depth', depth)) is int and data.get('depth', depth) >= 0)
            replies = data.get('replies', '')
            require(replies == '' or isinstance(replies, dict) and replies.get('kind') == 'Listing')
            if replies != '':
                stack.append((replies, depth + 1))
        yield item, depth


def ingest(state, response):
    """Add comments in response order; preserve first-seen and shown state."""
    things = list(walk_things(response))
    parents = {name: node['parent'] for name, node in state['nodes'].items()}
    for thing, _ in things:
        if thing['kind'] == 't1':
            parents.setdefault(fullname(thing['data'], 't1'), thing['data'].get('parent_id'))
    checked = set()
    for name in parents:
        chain = set()
        while name in parents and name not in checked:
            if name in chain:
                raise RedditError(6, 'Cyclic comment parent relationships in Reddit response.')
            chain.add(name)
            name = parents[name]
        checked.update(chain)
    added = []
    for thing, depth in things:
        if thing['kind'] == 'more':
            raw = thing['data']
            parent = raw.get('parent_id') or state['post']['fullname']
            ids = list(dict.fromkeys(str(i).removeprefix('t1_') for i in raw.get('children', [])))
            key = 'more:' + json.dumps([parent, ids], separators=(',', ':'))
            if key not in state['pending_more'] and key not in state.get('consumed_more', []):
                state['pending_more'][key] = {'parent': parent, 'ids': ids,
                    'count': raw.get('count', 0), 'from_pointer_key': key}
                state['children'].setdefault(parent, []).append(key)
                added.append(key)
            continue
        if thing['kind'] != 't1':
            continue
        raw = dict(thing['data'])
        raw.setdefault('depth', depth)
        raw.setdefault('link_id', state['post']['fullname'])
        data = build_comment(raw).to_dict()
        name = data['fullname']
        if name in state['nodes']:
            continue
        parent = data['parent'] or state['post']['fullname']
        state['nodes'][name] = {'data': data, 'parent': parent, 'children': [],
                                'shown': False, 'first_seen_at': time.time()}
        state['children'].setdefault(parent, []).append(name)
        state['children'].setdefault(name, [])
        added.append(name)
    reconnect(state)
    return added


def reconnect(state):
    """Reconnect flat children when their parent arrives, without dropping orphans."""
    post = state['post']['fullname']
    state['root_children'] = state['children'].setdefault(post, [])
    state['orphans'] = {parent: list(children) for parent, children in state['children'].items()
                        if parent != post and parent not in state['nodes'] and children}
    for name, node in state['nodes'].items():
        node['children'] = state['children'].setdefault(name, [])
    for name, depth, _orphan in ordered_nodes(state):
        state['nodes'][name]['data']['depth'] = depth


def ordered_nodes(state):
    """DFS followed by disconnected replies; cycle-safe for malformed responses."""
    seen = set()
    roots = [(name, 0, False) for name in state['root_children']]
    roots += [(name, state['nodes'][name]['data']['depth'], True)
              for children in state['orphans'].values() for name in children if name in state['nodes']]
    stack = list(reversed(roots))
    while stack:
        name, depth, orphan = stack.pop()
        if name in seen or name not in state['nodes']:
            continue
        seen.add(name)
        yield name, depth, orphan
        stack.extend((child, depth + 1, orphan) for child in reversed(state['nodes'][name]['children']))
