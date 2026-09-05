"""Pure thread reading state and locked, bounded local persistence."""
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import math
import time

from ._errors import RedditError
from ._models import build_post
from ._output import _open, _safe
from ._target import parse_target
from ._tree import ingest, ordered_nodes, reconnect, walk_things


def target_dict(target):
    if isinstance(target, str):
        target = parse_target(target)
    return asdict(target) if is_dataclass(target) else dict(target)


def create_state(response, target, sort='best', account=None):
    """Normalize a previously fetched post response without performing I/O."""
    post = next((thing['data'] for thing, _ in walk_things(response) if thing['kind'] == 't3'), None)
    if post is None:
        raise RedditError(6, 'Thread response has no post.')
    state = {'post': build_post(post).to_dict(), 'nodes': {}, 'children': {}, 'root_children': [],
             'orphans': {}, 'pending_more': {}, 'requested_ids': [], 'received_ids': [], 'missing': [],
             'unresolved': [], 'stalled': False, 'fetched_at': time.time(), 'expanded_at': [],
             'account': account, 'context': {'target': target_dict(target), 'sort': sort}}
    ingest(state, response)
    target = state['context']['target']
    if (target.get('post_id') and state['post']['fullname'] != 't3_' + target['post_id']) or (
        target.get('comment_id') and 't1_' + target['comment_id'] not in state['nodes']
    ):
        raise RedditError(9, 'The requested post or comment is absent from this response.')
    return state


def metadata(state, shown=0):
    nodes = state['nodes']
    unshown = sum(not node['shown'] for node in nodes.values())
    pending = sum(len(p['ids']) for p in state['pending_more'].values())
    if not unshown and not state['pending_more'] and (state['orphans'] or state['missing'] or state['unresolved']):
        state['stalled'] = True
    complete = not (unshown or state['pending_more'] or state['orphans'] or state['missing'] or state['unresolved'])
    return {'parents': sum(n in nodes for n in state['root_children']), 'parsed': len(nodes),
            'shown': shown, 'unshown': unshown, 'pending_ids': pending, 'min_requests': math.ceil(pending / 100),
            'orphans': sum(len(v) for v in state['orphans'].values()), 'missing': len(state['missing']),
            'complete': complete, 'stop_reason': 'exhausted' if complete else 'stalled' if state['stalled'] else 'limit_reached',
            'fetched_at': state['fetched_at'], 'expanded_at': state['expanded_at'], 'account': state['account']}


def select_batch(state, limit=25, depth=2, anchor=None):
    """Select unseen DFS comments; context rows do not consume the limit."""
    if limit < 1 or depth < 0:
        raise ValueError('limit must be positive and depth nonnegative')
    anchor = anchor or state['context']['target'].get('comment_id')
    if anchor and not anchor.startswith('t1_'):
        anchor = 't1_' + anchor
    if anchor and anchor not in state['nodes']:
        raise RedditError(9, 'The requested comment is absent from this response.')
    ordered = list(ordered_nodes(state))
    selected = [(name, orphan) for name, level, orphan in ordered
                if level <= depth and not state['nodes'][name]['shown']][:limit]
    if anchor and not state['nodes'][anchor]['shown'] and anchor not in dict(selected):
        selected = selected[:limit - 1] + [(anchor, next(o for n, _, o in ordered if n == anchor))]
        selected.sort(key=lambda item: next(i for i, (n, _, _) in enumerate(ordered) if n == item[0]))
    records, emitted = [], set()
    for name, orphan in selected:
        ancestors, parent = [], state['nodes'][name]['parent']
        while parent in state['nodes'] and parent not in emitted and parent not in ancestors:
            ancestors.append(parent)
            parent = state['nodes'][parent]['parent']
        for ancestor in reversed(ancestors):
            records.append(dict(state['nodes'][ancestor]['data'], context=True, shown_earlier=state['nodes'][ancestor]['shown'], anchor=False, orphan=orphan))
            emitted.add(ancestor)
        records.append(dict(state['nodes'][name]['data'], context=False, anchor=name == anchor, orphan=orphan))
        emitted.add(name)
        state['nodes'][name]['shown'] = True
    return {'records': records, 'metadata': metadata(state, len(selected))}


def next_expansion(state):
    """Describe the first DFS pointer; the caller owns all network activity."""
    if state['stalled']:
        return None
    roots = state['root_children'] + [key for keys in state['orphans'].values() for key in keys]
    stack, seen = list(reversed(roots)), set()
    while stack:
        key = stack.pop()
        if key in seen:
            continue
        seen.add(key)
        if key in state['nodes']:
            stack.extend(reversed(state['nodes'][key]['children']))
        elif key in state['pending_more']:
            pointer = state['pending_more'][key]
            if pointer['ids']:
                attempted = set(state['requested_ids'])
                pointer['ids'] = [i for i in pointer['ids'] if i not in attempted and 't1_' + i not in state['nodes']]
                if not pointer['ids']:
                    del state['pending_more'][key]
                    state['children'][pointer['parent']].remove(key)
                    reconnect(state)
                    state.setdefault('consumed_more', []).append(key)
                    continue
            descriptor = {'kind': 'morechildren', 'pointer': key, 'ids': pointer['ids'][:100],
                          'parent': pointer['parent']}
            if pointer['ids']:
                return descriptor
            parent = state['nodes'].get(pointer['parent'])
            if parent:
                return dict(descriptor, kind='subtree', target=parent['data']['url'])
            state['unresolved'].append(key)
            del state['pending_more'][key]
            state['children'][pointer['parent']].remove(key)
            reconnect(state)
            state.setdefault('consumed_more', []).append(key)
    if state['unresolved']:
        state['stalled'] = True
    return None


def merge_more(state, things, requested_ids, pointer):
    """Merge a fetched expansion into its original sibling slot, recording coverage."""
    key = pointer['pointer'] if isinstance(pointer, dict) else pointer
    slot = state['pending_more'][key]
    siblings = state['children'][slot['parent']]
    position = siblings.index(key)
    before = set(siblings)
    repeated_empty = not slot['ids'] and any(
        thing['kind'] == 'more' and thing['data'].get('parent_id') == slot['parent']
        and not thing['data'].get('children') and thing['data'].get('count', 0) > 0
        for thing, _ in walk_things(things))
    added = ingest(state, things)
    if repeated_empty and key not in state['unresolved']:
        state['unresolved'].append(key)
    inserted = [name for name in siblings if name not in before]
    siblings[:] = [name for name in siblings if name not in inserted]
    siblings[position:position] = inserted
    requested = {str(i).removeprefix('t1_') for i in requested_ids}
    received = {thing['data'].get('name', 't1_' + thing['data'].get('id', ''))[3:]
                for thing, _ in walk_things(things) if thing['kind'] == 't1'}
    state['requested_ids'] = sorted(set(state['requested_ids']) | requested)
    state['received_ids'] = sorted(set(state['received_ids']) | received)
    state['missing'] = sorted(set(state['requested_ids']) - set(state['received_ids']))
    slot['ids'] = [i for i in slot['ids'] if i not in requested]
    if not slot['ids']:
        siblings.remove(key)
        del state['pending_more'][key]
        state.setdefault('consumed_more', []).append(key)
    state['expanded_at'].append(time.time())
    state['stalled'] = not added
    reconnect(state)
    return metadata(state)


class ThreadStateStore:
    """Keep the lock through read/select/fetch/merge/save using transaction()."""

    def __init__(self, home=None, ttl=86400, max_bytes=200 * 1024 * 1024, clock=time.time):
        self.home = _safe(home or os.environ.get('REDDIT_HOME', Path.home() / '.cache/reddit-skill'))
        self.ttl, self.max_bytes, self.clock = ttl, max_bytes, clock
        self.directory = _safe(self.home / 'threads')
        self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.home.chmod(0o700)
        self.directory.chmod(0o700)

    def key(self, target, sort='best'):
        target = target_dict(target)
        context = [target.get('post_id'), target.get('comment_id'), sort]
        return hashlib.sha256(json.dumps(context).encode()).hexdigest()

    def _path(self, key):
        if not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{64}', key):
            raise RedditError(2, 'Invalid thread cache key.')
        return _safe(self.directory / (key + '.json'))

    @contextmanager
    def _lock(self):
        # 성진: One cache-wide lock serializes threads; split locks if concurrent reading becomes a bottleneck.
        _safe(self.directory)
        _safe(self.home / 'cursors')
        with os.fdopen(_open(self.home / 'threads.lock', os.O_RDWR | os.O_CREAT), 'r+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _load(self, key):
        path = self._path(key)
        if not path.exists() or self.clock() - path.stat().st_mtime >= self.ttl:
            return None
        try:
            with os.fdopen(_open(path, os.O_RDONLY), 'r') as source:
                return json.load(source)
        except (ValueError, OSError) as exc:
            raise RedditError(2, 'Thread cache is unreadable; open the target again.') from exc

    def load(self, key):
        with self._lock():
            return self._load(key)

    def _save(self, key, state):
        path = self._path(key)
        encoded = json.dumps(state, ensure_ascii=False).encode('utf-8')
        if len(encoded) > self.max_bytes:
            raise RedditError(8, 'Thread exceeds the cache capacity; use a smaller target.')
        self._cleanup(protect=path, reserve=len(encoded))
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory,
                                             suffix='.tmp', delete=False) as output:
                temporary = output.name
                output.write(encoded.decode('utf-8'))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def save(self, state):
        key = self.key(**state['context'])
        with self._lock():
            self._save(key, state)
        return key

    @contextmanager
    def transaction(self, key, initial=None):
        with self._lock():
            state = self._load(key)
            if state is None:
                state = initial
            if state is None:
                raise RedditError(2, 'Thread cache expired or is missing; open the target again.')
            if self.key(**state['context']) != key:
                raise RedditError(2, 'Thread target and sort do not match this cache key.')
            yield state
            self._save(key, state)


    def _cleanup(self, protect=None, reserve=0):
        files, removed = [], []
        for directory in (self.directory, self.home / 'cursors'):
            directory = _safe(directory)
            if directory.exists():
                directory.chmod(0o700)
            for path in directory.glob('*'):
                if path.suffix not in ('.json', '.tmp'):
                    continue
                _safe(path)
                try:
                    info = path.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise RedditError(2, 'Cache entries must be regular, unshared files.')
                except FileNotFoundError:
                    continue
                if path != protect and self.clock() - info.st_mtime >= self.ttl:
                    path.unlink(missing_ok=True)
                    removed.append(str(path))
                else:
                    files.append((info.st_mtime, info.st_size, path))
        total = reserve + sum(size for _, size, path in files if path != protect)
        for _, size, path in sorted(files):
            if total <= self.max_bytes:
                break
            if path != protect:
                path.unlink(missing_ok=True)
                total -= size
                removed.append(str(path))
        return {'bytes': total, 'removed': removed}

    def cleanup(self):
        """Expire thread/cursor JSON and crash temporaries; evict oldest files to fit capacity."""
        with self._lock():
            return self._cleanup()
