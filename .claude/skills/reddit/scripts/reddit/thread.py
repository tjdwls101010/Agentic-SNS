"""post and comments: one post in full and its comment tree, read in batches from a snapshot.

The first read of a post asks Reddit for up to 500 comments, 10 levels deep; the rest of the tree comes back as gaps
(`more` pointers). A snapshot keeps the tree of one read generation: which comments arrived, which were shown, which
gaps are left. A batch is the next unshown comments in depth-first order within --depth. When none is left to show,
the next gap is expanded: ids of the same post are gathered across gaps, up to 100, into one request; each comment that
comes back takes its own gap's place in that gap's order, what hangs under it goes under it, and a gap inside the
answer becomes a new gap. Reddit cuts an answer at about 100 things and drops whole requested comments from it, so an
id absent from a cut answer is asked again in a batch of only such ids, half as large each time; an id absent from an
answer that was not cut, or asked alone, is gone (missing). A 'continue this thread' gap is its comment's subtree, one
request; a branch that answers with nothing new is stalled alone, the rest goes on.
"""
import math
import time
from datetime import datetime, timezone

from reddit import connect
from reddit.errors import RedditError
from reddit.reddit_web import COMMENT_SORTS, parse_target, permalink, require
from reddit.snapshots import Snapshots

DISPLAY = 25
DEPTH = 2
BATCH = 100
CUT = 90      # an answer this large may have been cut (Reddit stops at about 100 things)


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec='seconds') if epoch else None


# --- the tree (pure: state in, state out)


def create(post, items, sort, key, generation, observed, anchor=None):
    state = {'key': key, 'generation': generation, 'post': post, 'sort': sort, 'anchor': anchor, 'nodes': {},
             'children': {post['id']: []}, 'gaps': {}, 'gap_seq': 0, 'consumed': [], 'tries': {}, 'missing': [],
             'requested': 0, 'observed_at': time.time(), 'expanded_at': [], 'reddit_account': observed}
    ingest(state, items)
    return state


def _gap_key(parent, ids):
    return 'gap:' + parent + ':' + ','.join(sorted(ids)) if ids else 'gap:' + parent + ':subtree'


def ingest(state, items, slots=None):
    """Add comments and gaps in answer order. A comment already present is skipped (what was shown stays shown); a
    requested comment (in slots: id → [gap, index]) takes its gap's place; a gap is kept once per (parent, ids)."""
    slots = slots or {}
    parents = {name: node['parent'] for name, node in state['nodes'].items()}
    for item in items:
        if item['type'] == 'comment':
            parents.setdefault(item['record']['id'], item['record']['parent_id'])
    for name in parents:
        seen, current = set(), name
        while current in parents:
            if current in seen:
                raise RedditError(6, 'Reddit sent comments that answer each other in a loop.', 'Retry once; if it '
                                                                                                'persists, report it.',
                                  reason='shape_changed')
            seen.add(current)
            current = parents[current]
    added = 0
    for item in items:
        if item['type'] == 'gap':
            key = _gap_key(item['parent'], item['ids'])
            if key in state['gaps'] or key in state['consumed']:
                continue
            ids = [i for i in item['ids'] if 't1_' + i not in state['nodes']]
            state['gaps'][key] = {'parent': item['parent'], 'ids': ids, 'count': item['count'], 'subtree': not item['ids'],
                                  'stalled': False, 'order': list(item['ids'])}
            state['children'].setdefault(item['parent'], []).append(key)
            added += 1
            continue
        record = item['record']
        name = record['id']
        if name in state['nodes']:
            continue
        parent = record['parent_id'] or state['post']['id']
        state['nodes'][name] = {'record': record, 'parent': parent, 'shown': False, 'seen_at': time.time()}
        state['children'].setdefault(name, [])
        siblings = state['children'].setdefault(parent, [])
        slot = slots.get(name[3:])
        if slot and slot[0] in siblings:
            gap, index = slot
            position = siblings.index(gap)
            # before the gap, after the comments this gap already gave that come earlier in its order
            while position > 0:
                before = state['nodes'].get(siblings[position - 1])
                if not before or before.get('slot', [None])[0] != gap or before['slot'][1] < index:
                    break
                position -= 1
            siblings.insert(position, name)
            state['nodes'][name]['slot'] = [gap, index]
        else:
            siblings.append(name)
        added += 1
    for gap in state['gaps'].values():
        gap['ids'] = [i for i in gap['ids'] if 't1_' + i not in state['nodes']]
    return added


def order(state):
    """(name, depth, orphan) depth-first: the post's comments, then comments whose parent never arrived."""
    post = state['post']['id']
    roots = [(name, 0, False) for name in state['children'].get(post, [])]
    known = set(state['nodes']) | {post}
    for parent, children in state['children'].items():
        if parent not in known:
            roots += [(name, 1, True) for name in children]
    stack, seen = list(reversed(roots)), set()
    while stack:
        name, depth, orphan = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        yield name, depth, orphan
        if name in state['nodes']:
            stack.extend((child, depth + 1, orphan) for child in reversed(state['children'].get(name, [])))


def select(state, limit, depth, anchor=None):
    """The next batch: up to `limit` unshown comments within `depth` levels (relative to the anchor when there is
    one), depth-first; the anchor always, with its ancestors as context rows that do not count."""
    nodes, rows = state['nodes'], list(order(state))
    depths = {name: d for name, d, _ in rows}
    base = depths.get(anchor, 0) if anchor else 0
    within = (lambda n: _under(state, n, anchor)) if anchor else (lambda n: True)
    chosen = []
    for name, level, orphan in rows:
        if name in nodes and not nodes[name]['shown'] and level - base <= depth and within(name):
            chosen.append(name)
    chosen = chosen[:limit]
    if anchor and anchor in nodes and anchor not in chosen:
        chosen = [anchor] + chosen[:max(0, limit - 1)]
    position = {name: index for index, (name, _, _) in enumerate(rows)}
    chosen.sort(key=lambda name: position.get(name, 0))
    records, emitted = [], set()
    for name in chosen:
        ancestors, parent = [], nodes[name]['parent']
        while parent in nodes and parent not in emitted and parent not in chosen:
            ancestors.append(parent)
            parent = nodes[parent]['parent']
        for ancestor in reversed(ancestors):
            if nodes[ancestor].get('record') is not None:  # a resumed --out tree keeps no text of what it wrote
                records.append({**nodes[ancestor]['record'], 'depth': depths.get(ancestor, 0), 'context': True})
            emitted.add(ancestor)
        records.append({**nodes[name]['record'], 'depth': depths.get(name, 0),
                        **({'anchor': True} if name == anchor else {})})
        emitted.add(name)
        nodes[name]['shown'] = True
    hidden = sum(1 for name, level, _ in rows if name in nodes and not nodes[name]['shown'] and level - base > depth
                 and within(name))
    return records, len(chosen), hidden


def _under(state, name, anchor):
    current = name
    while current in state['nodes']:
        if current == anchor:
            return True
        current = state['nodes'][current]['parent']
    return False


def plan(state):
    """The next expansion: {kind: ids, ids, slots} gathered across gaps (ids asked before first), or {kind: subtree,
    gap, comment}; None when no gap can be expanded. A subtree gap under the post itself cannot be followed."""
    gaps = state['gaps']
    keys = [name for name, _, _ in order(state) if name in gaps] + \
        [key for key in gaps if key not in {n for n, _, _ in order(state)}]
    for key in keys:
        gap = gaps[key]
        if gap['stalled']:
            continue
        if gap['subtree']:
            if gap['parent'].startswith('t1_') and gap['parent'] in state['nodes']:
                return {'kind': 'subtree', 'gap': key, 'comment': gap['parent'][3:]}
            gap['stalled'] = True  # 'continue this thread' under the post: nothing to read it with
            continue
        if not gap['ids']:
            continue
        pool = [(key, i) for key in keys if not gaps[key]['subtree'] and not gaps[key]['stalled']
                for i in gaps[key]['ids']]
        retry = [(k, i) for k, i in pool if state['tries'].get(i)]
        if retry:  # ids a cut answer dropped: only them, in a batch half as large as the last one that dropped them
            size = max(1, BATCH >> max(state['tries'][i] for _, i in retry))
            chosen = retry[:size]
        else:
            chosen = pool[:BATCH]
        return {'kind': 'ids', 'ids': [i for _, i in chosen],
                'slots': {i: [k, gaps[k]['order'].index(i)] for k, i in chosen}}
    return None


def merge(state, descriptor, items):
    """Put an expansion's answer in place; returns whether it made progress (a new comment or gap, or an id that
    finished as received or missing)."""
    state['requested'] += 1
    state['expanded_at'].append(time.time())
    if descriptor['kind'] == 'subtree':
        added = ingest(state, items)
        key = descriptor['gap']
        if added:
            _drop_gap(state, key)
        else:
            state['gaps'][key]['stalled'] = True
        return bool(added)
    received = {item['record']['id'][3:] for item in items if item['type'] == 'comment'}
    cut = len(items) >= CUT and len(descriptor['ids']) > 1
    added = ingest(state, items, descriptor['slots'])
    finished = 0
    for identity in descriptor['ids']:
        if identity in received or 't1_' + identity in state['nodes']:
            state['tries'].pop(identity, None)
            finished += 1
        elif cut:
            state['tries'][identity] = state['tries'].get(identity, 0) + 1
        else:
            state['tries'].pop(identity, None)
            state['missing'].append(identity)
            finished += 1
    gone = set(state['missing'])
    for key in {slot[0] for slot in descriptor['slots'].values()}:
        gap = state['gaps'].get(key)
        if gap is not None:
            gap['ids'] = [i for i in gap['ids'] if i not in gone and 't1_' + i not in state['nodes']]
            if not gap['ids']:
                _drop_gap(state, key)
    return bool(added or finished)


def _drop_gap(state, key):
    gap = state['gaps'].pop(key)
    siblings = state['children'].get(gap['parent'], [])
    if key in siblings:
        siblings.remove(key)
    state['consumed'].append(key)


def coverage(state, shown_now, hidden):
    ids = sum(len(g['ids']) for g in state['gaps'].values() if not g['subtree'] and not g['stalled'])
    subtrees = sum(1 for g in state['gaps'].values() if g['subtree'] and not g['stalled'])
    stalled = sum(1 for g in state['gaps'].values() if g['stalled'])
    post = state['post']
    return {'reported': post.get('num_comments'), 'received': len(state['nodes']),
            'shown': sum(1 for n in state['nodes'].values() if n['shown']), 'shown_now': shown_now,
            'hidden_by_depth': hidden, 'unexpanded': ids, 'continue_threads': subtrees,
            'min_requests': math.ceil(ids / BATCH) + subtrees, 'missing': len(state['missing']),
            'stalled': stalled, 'sort': state['sort'], 'suggested_sort': post.get('suggested_sort'),
            'contest_mode': post.get('contest_mode'), 'observed_at': _iso(state['observed_at']),
            'expanded_at': _iso(state['expanded_at'][-1]) if state['expanded_at'] else None,
            'complete': not ids and not subtrees and not stalled and not _unshown(state)}


# --- the commands


def _target(options, command):
    kinds = ('post', 'comment', 'share')
    return require(parse_target(options['target']), kinds, command)


def post(options):
    """The post in full and the first batch of its comments, from a new read generation."""
    return _thread(options, 'post')


def comments(options):
    """The next batch of a thread (by handle or the post's latest generation), or one comment in full with what hangs
    under it (a comment link)."""
    return _thread(options, 'comments')


def _thread(options, command):
    target = _target(options, command) if not options.get('after') else parse_target(options['target'])
    sort = options.get('sort') or 'best'
    identity = {'sort': sort}

    def read(connection, state, out):
        return _read(connection, options, command, target, sort, state, out)

    name = target.name if target.kind != 'share' else target.url
    return connect.run(options, command='comments' if options.get('after') else command, target=name,
                       identity=identity, reader=read)


def _read(connection, options, command, target, sort, handle, out):
    snapshots = Snapshots(connection.account)
    limit = options.get('limit') or DISPLAY
    depth = options.get('depth') if options.get('depth') is not None else DEPTH
    with snapshots.locked():
        if target.kind == 'share':
            target = connection.network().resolve(target)
        anchor = 't1_' + target.comment_id if target.comment_id else None
        state = _open(connection, snapshots, command, target, sort, handle, out, options)
        if anchor and anchor not in state['nodes']:
            raise RedditError(9, 'The linked comment is not in this thread (deleted, removed or never sent).',
                              'Tell the user; open the post itself with post <url>.', reason='not_found')
        reading = {'observed': state['reddit_account']}
        failure = None
        records = [state['post']] if command == 'post' and out is None and not handle else []
        shown_now, hidden = 0, 0
        try:
            if out is not None:
                failure = _collect(connection, state, out, options)
            else:
                batch, shown_now, hidden = select(state, limit, depth, anchor)
                while not shown_now and command == 'comments' and plan(state) is not None:
                    _expand(connection, state)
                    batch, shown_now, hidden = select(state, limit, depth, anchor)
                records += batch
        except RedditError as error:
            failure = error
        finally:
            snapshots.save(state['generation'], state)
    info = coverage(state, shown_now, hidden)
    if info['complete']:
        stop = 'exhausted'
    elif not _unshown(state) and plan(state) is None:
        stop = 'stalled'  # only stalled branches are left
    else:
        stop = 'limit_reached'
    reading.update(results=records, failure=failure, details={'thread': info}, stop_reason=stop, partial=bool(records))
    reading['coverage'] = _notes(info, depth)
    if stop == 'limit_reached' and out is None:
        words = ['--sort', sort] + (['--depth', str(options['depth'])] if options.get('depth') is not None else [])
        reading['continuation'] = {'command': 'comments', 'target': permalink(target.post_id), 'identity': {'sort': sort},
                                   'words': words, 'state': {'generation': state['generation']}}
    if out is not None:
        reading['results'] = []
    return reading


def _unshown(state):
    return any(not node['shown'] for node in state['nodes'].values())


def _notes(info, depth):
    notes = []
    if info['hidden_by_depth']:
        notes.append(f'{info["hidden_by_depth"]} received comments are deeper than --depth {depth}; a larger --depth '
                     'shows them')
    if info['missing']:
        notes.append(f'{info["missing"]} comments Reddit listed but did not send when asked (deleted or removed)')
    if info['stalled']:
        notes.append(f'{info["stalled"]} branches could not be expanded (Reddit sent nothing new for them)')
    if info['contest_mode']:
        notes.append('contest mode: the moderators set random order and hidden scores, so order and score mean '
                     'nothing here')
    return notes


def _open(connection, snapshots, command, target, sort, handle, out, options):
    """The snapshot to read: the handle's generation, the --out file's, the post's latest (comments), or a new one."""
    key = [target.post_id, None, sort]
    if handle is not None:
        state = snapshots.load(handle.get('generation'))
        if state is None:
            raise RedditError(2, 'The comment thread this handle continued has expired.', 'Run the original post or '
                                                                                          'comments command again.')
        return state
    if out is not None and out.state and out.state.get('generation'):
        state = snapshots.load(out.state['generation']) or _rebuild(out.state)
        return state
    anchor = 't1_' + target.comment_id if target.comment_id else None
    if command == 'comments' and out is None:  # a new collection starts its own reading: it holds every comment
        latest = snapshots.latest(key)
        state = snapshots.load(latest) if latest else None
        if state is not None and (anchor is None or anchor in state['nodes']):
            connection.observed = state['reddit_account']
            if anchor:
                state['nodes'][anchor]['shown'] = False  # a comment link always shows its comment
            return state
    client = connection.network()
    sub_key = [target.post_id, target.comment_id, sort]
    generation = snapshots.new(sub_key)
    context = options.get('context') if command == 'post' else (0 if target.comment_id else None)
    post_record, items = client.thread(target.post_id, sort, target.comment_id, context)
    if post_record['id'] != 't3_' + target.post_id:
        raise RedditError(9, 'Reddit answered with another post than the one asked for.', 'Check the link.',
                          reason='not_found')
    return create(post_record, items, sort, sub_key, generation, connection.reddit_account, anchor)


def _rebuild(saved):
    """A --out file's committed tree when its snapshot was evicted: everything in it is already written."""
    return {**saved, 'nodes': {name: {**node, 'record': None} for name, node in saved['nodes'].items()}}


def _expand(connection, state):
    descriptor = plan(state)
    client = connection.network()
    if descriptor['kind'] == 'subtree':
        _post, items = client.thread(state['post']['id'][3:], state['sort'], descriptor['comment'], 0)
    else:
        items = client.expand(state['post']['id'][3:], descriptor['ids'], state['sort'])
    merge(state, descriptor, items)


def _committed(state):
    """What a --out page marker keeps of the tree: everything but the records, which are in the file."""
    return {**state, 'nodes': {name: {k: v for k, v in node.items() if k != 'record'}
                               for name, node in state['nodes'].items()}}


def _collect(connection, state, out, options):
    """--out: the post once, then every comment flat, a page per expansion, until the tree is complete, the limit or
    a failure."""
    limit = options.get('limit')
    if not out.ids:
        out.commit([state['post']], _committed(state), None)
    while True:
        batch, shown, _hidden = select(state, 10 ** 6, 10 ** 6)
        page = [record for record in batch if not record.get('context') and record.get('id') not in out.ids]
        info = coverage(state, 0, 0)
        reason = 'exhausted' if info['complete'] else ('stalled' if plan(state) is None else None)
        if limit is not None and out.count - 1 + len(page) >= limit:
            reason = 'limit_reached'
        out.commit(page, _committed(state), reason)
        if reason or plan(state) is None:
            return None
        try:
            _expand(connection, state)
        except RedditError as error:
            return error


__all__ = ['COMMENT_SORTS', 'comments', 'post']
