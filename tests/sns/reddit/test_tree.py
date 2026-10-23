"""The comment-tree reading policy (reddit.TREE, fixture tree.json): where comments go, what one expansion asks for,
how an answer is merged, when a branch is stalled, and what coverage says — on snapshots built from compact
comment notation, against a fake Reddit that answers morechildren the way P2 R1 measured (about 100 things a reply,
requested comments that do not fit simply absent). The commands that wire this to Reddit are tested in test_cli_thread."""
import math

import pytest

from sns.errors import SnsError
from sns.reddit import TREE as thread
from tests.sns.reddit.scene import fixture

TREE = fixture('tree.json')
POST = {'kind': 'post', 'id': 't3_aaa1', 'num_comments': None}


def items(comments):
    """Compact notation → the items reddit_web reads from an answer (depth-first)."""
    out = []
    for c in comments:
        if 'more' in c:
            out.append({'type': 'gap', 'parent': c['parent'], 'ids': list(c['more']), 'count': c.get('count', 0)})
            continue
        out.append({'type': 'comment', 'record': {'kind': 'comment', 'id': 't1_' + c['id'], 'parent_id': c['parent'],
                                                  'text': c.get('body', c['id']), 'depth': 0}})
        out += items(c.get('replies') or [])
    return out


def state(initial, post=POST):
    return thread.create(post, items(initial), 'best', ['aaa1', None, 'best'], 'g', 'viewer')


def names(s):
    return [name for name, _, _ in thread.order(s) if name.startswith('t1_')]


def show_all(s):
    thread.select(s, 10 ** 6, 10 ** 6)


@pytest.mark.parametrize('case', [c for c in TREE['ingest']['cases'] if 'error' not in c['expected']],
                         ids=lambda c: c['name'])
def test_ingest(case):
    s = state(case['responses'][0])
    if 'after_first' in case['expected']:
        orphans = sum(1 for _, _, orphan in thread.order(s) if orphan)
        assert orphans == case['expected']['after_first']['orphans']
    for response in case['responses'][1:]:
        thread.ingest(s, items(response))
    expected = case['expected'].get('after_second', case['expected'])
    if 'order' in expected:
        assert names(s) == expected['order']
    if 'texts' in expected:
        assert {k: s['nodes'][k]['record']['text'] for k in expected['texts']} == expected['texts']
    if 'gaps' in expected:
        assert len(s['gaps']) == expected['gaps']
    if 'depths' in expected:
        assert {name: depth for name, depth, _ in thread.order(s)} == expected['depths']


def test_a_parent_loop_is_malformed():
    case = next(c for c in TREE['ingest']['cases'] if c['name'] == 'cycle-is-malformed')
    with pytest.raises(SnsError) as caught:
        state(case['responses'][0])
    assert caught.value.kind == 'failed' and caught.value.reason == 'shape_changed'


class FakeReddit:
    """A whole comment tree, answered the way Reddit does: morechildren returns requested comments with what hangs
    under them (two levels, deeper as a gap), at most `cap` things, the rest absent; deleted ids never come."""

    def __init__(self, tree, deleted=(), cap=100):
        self.tree, self.deleted, self.cap = tree, set(deleted), cap   # tree: id → (parent fullname, [child ids])
        self.requests = []

    def _thing(self, identity, depth, out):
        parent, children = self.tree[identity]
        out.append({'type': 'comment', 'record': {'kind': 'comment', 'id': 't1_' + identity, 'parent_id': parent,
                                                  'text': identity, 'depth': 0}})
        live = [c for c in children if c not in self.deleted]
        if not live:
            return
        if depth >= 2:
            out.append({'type': 'gap', 'parent': 't1_' + identity, 'ids': live, 'count': len(live)})
            return
        for child in live:
            self._thing(child, depth + 1, out)

    def expand(self, ids):
        self.requests.append(('ids', list(ids)))
        out = []
        for identity in ids:
            if identity in self.deleted or identity not in self.tree:
                continue
            part = []
            self._thing(identity, 0, part)
            room = self.cap - len(out)
            if len(part) > room:
                continue  # cut: a requested comment that does not fit is simply not in the answer
            out += part
        return out

    def subtree(self, identity):
        self.requests.append(('subtree', identity))
        out = []
        self._thing(identity, 0, out)
        return out


def drive(s, reddit, limit=200):
    """Expand until the plan has nothing left (or `limit` requests), the way comments does."""
    while len(reddit.requests) < limit:
        descriptor = thread.plan(s)
        if descriptor is None:
            return
        answer = reddit.subtree(descriptor['comment']) if descriptor['kind'] == 'subtree' else \
            reddit.expand(descriptor['ids'])
        thread.merge(s, descriptor, answer)


def test_requested_comments_take_their_gaps_place_in_the_gaps_order():
    scenario = next(c for c in TREE['batching']['scenarios'] if c['name'] == 'two-gaps-same-parent')
    reddit = FakeReddit({'c1': ('t3_aaa1', []), 'a1': ('t3_aaa1', []), 'a2': ('t3_aaa1', []), 'x1': ('t3_aaa1', []),
                         'b1': ('t3_aaa1', [])})
    s = state(scenario['initial'])
    reddit.expand = lambda ids, original=reddit.expand: list(reversed(original(ids)))  # any reply order
    drive(s, reddit)
    assert names(s) == scenario['expected_order'] and len(reddit.requests) == 1


def test_an_id_absent_from_an_uncut_answer_is_gone():
    case = next(c for c in TREE['merge']['cases'] if c['name'] == 'missing-ids-counted')
    reddit = FakeReddit({'c1': ('t3_aaa1', []), 'c2': ('t3_aaa1', [])})
    s = state(case['initial'])
    drive(s, reddit)
    assert s['missing'] == case['expected']['missing'] and len(reddit.requests) == case['expected']['requests']
    assert not s['gaps']


def test_an_empty_answer_does_not_stop_the_other_gaps():
    case = TREE['stall']['cases'][0]
    reddit = FakeReddit({'c1': ('t3_aaa1', []), 'c2': ('t3_aaa1', []), 'c3': ('t3_aaa1', [])}, deleted=['d1'])
    s = state(case['initial'])
    drive(s, reddit)
    show_all(s)
    info = thread.coverage(s, 0, 0)
    assert 't1_c3' in s['nodes'] and s['missing'] == case['expected']['missing'] and info['complete']
    assert len(reddit.requests) == case['expected']['requests']


def test_continue_this_thread_reads_the_subtree():
    case = next(c for c in TREE['merge']['cases'] if c['name'] == 'continue-this-thread')
    reddit = FakeReddit({'c1': ('t3_aaa1', ['c2']), 'c2': ('t1_c1', ['c6', 'c7']), 'c6': ('t1_c2', []),
                         'c7': ('t1_c2', [])})
    s = state(case['initial'])
    drive(s, reddit)
    assert names(s) == case['expected']['order'] and reddit.requests == [('subtree', 'c2')] and not s['gaps']


def test_a_top_level_continue_cannot_be_followed():
    case = next(c for c in TREE['merge']['cases'] if c['name'] == 'top-level-continue-unresolved')
    s = state(case['initial'])
    show_all(s)
    assert thread.plan(s) is None and thread.coverage(s, 0, 0)['complete'] is False


def test_a_branch_that_answers_nothing_new_is_stalled_alone():
    s = state([{'id': 'c1', 'parent': 't3_aaa1', 'replies': [{'more': [], 'parent': 't1_c1', 'count': 0}]},
               {'id': 'c2', 'parent': 't3_aaa1'}, {'more': ['c3'], 'parent': 't3_aaa1', 'count': 1}])
    reddit = FakeReddit({'c1': ('t3_aaa1', []), 'c2': ('t3_aaa1', []), 'c3': ('t3_aaa1', [])})
    drive(s, reddit)
    show_all(s)
    info = thread.coverage(s, 0, 0)
    assert 't1_c3' in s['nodes'] and info['stalled'] == 1 and not info['complete']
    assert reddit.requests == [('subtree', 'c1'), ('ids', ['c3'])], 'one try for the branch, then the rest goes on'


def test_coverage_counts():
    case = TREE['coverage']['cases'][0]
    s = state(case['initial'], {**POST, 'num_comments': case['num_comments']})
    records, shown, hidden = thread.select(s, case['shown'], 10)
    info = thread.coverage(s, shown, hidden)
    expected = case['expected']
    assert info['reported'] == expected['reported'] and info['received'] == expected['parsed']
    assert info['shown'] == expected['shown'] and info['unexpanded'] == expected['unexpanded_ids']
    assert info['min_requests'] == expected['min_requests'] and info['complete'] is expected['complete']


def test_the_anchor_is_always_shown_with_its_ancestors_as_context():
    s = state([{'id': 'c1', 'parent': 't3_aaa1', 'replies': [{'id': 'c2', 'parent': 't1_c1', 'replies': [
        {'id': 'c3', 'parent': 't1_c2', 'replies': [{'id': 'c4', 'parent': 't1_c3'}]}]}]}])
    show_all(s)
    s['nodes']['t1_c3']['shown'] = False
    records, shown, _ = thread.select(s, 25, 0, 't1_c3')
    assert [(r['id'], bool(r.get('context')), bool(r.get('anchor'))) for r in records] == [
        ('t1_c1', True, False), ('t1_c2', True, False), ('t1_c3', False, True)]
    assert shown == 1


def big_thread(seed=7):
    """A thread shaped like the measured one: 795 comments; the first answer holds most of the tree and leaves gaps
    of 1-3 ids under comments, one long top-level gap, and 'continue this thread' at depth 4."""
    import random
    rng = random.Random(seed)
    tree, top, first = {}, [], []
    count = 0

    def add(parent, depth):
        nonlocal count
        count += 1
        identity = f'k{count}'
        tree[identity] = (parent, [])
        if parent.startswith('t1_'):
            tree[parent[3:]][1].append(identity)
        return identity

    while count < 795:
        root = add('t3_aaa1', 0)
        top.append(root)
        frontier = [(root, 0)]
        while frontier and count < 795:
            node, depth = frontier.pop()
            for _ in range(rng.choice([0, 0, 1, 1, 2, 3]) if depth < 6 else 0):
                if count >= 795:
                    break
                frontier.append((add('t1_' + node, depth + 1), depth + 1))

    def compact(identity, depth):
        _, children = tree[identity]
        node = {'id': identity, 'parent': tree[identity][0], 'replies': []}
        if depth == 4 and children:
            node['replies'].append({'more': [], 'parent': 't1_' + identity, 'count': 0})
            return node
        shown, hidden = children[:2], children[2:]
        node['replies'] = [compact(c, depth + 1) for c in shown]
        if hidden:
            node['replies'].append({'more': hidden, 'parent': 't1_' + identity, 'count': len(hidden)})
        return node

    half = len(top) // 2
    first = [compact(r, 0) for r in top[:half]]
    first.append({'more': top[half:], 'parent': 't3_aaa1', 'count': len(top) - half})
    return tree, first


def test_a_large_thread_is_read_to_the_end_in_few_requests():
    scenario = next(c for c in TREE['batching']['scenarios'] if c['name'] == 'large-thread-795')
    tree, first = big_thread()
    in_gaps = [i for g in state(first)['gaps'].values() for i in g['ids']]
    deleted = [i for i in in_gaps if not tree[i][1]][::7][:scenario['spec']['missing']]  # leaves: nothing hangs under
    reddit = FakeReddit(tree, deleted=deleted)
    s = state(first, {**POST, 'num_comments': scenario['spec']['reported']})
    received_first = len(s['nodes'])
    drive(s, reddit)
    show_all(s)
    info = thread.coverage(s, 0, 0)
    gap_ids = len(in_gaps)
    assert info['complete'] and info['received'] == len(tree) - len(deleted), info
    assert sorted(s['missing']) == sorted(deleted)
    bound = math.ceil(gap_ids / 100) * 3 + sum(1 for g in state(first)['gaps'].values() if g['subtree']) + 10
    assert len(reddit.requests) <= bound, (len(reddit.requests), bound, received_first)
    print('received first', received_first, 'requests', len(reddit.requests), 'bound', bound, 'missing', info['missing'])


def test_an_id_absent_from_a_cut_answer_is_asked_again_in_smaller_batches():
    tree = {f'r{i}': ('t3_aaa1', [f'r{i}a', f'r{i}b']) for i in range(60)}
    for i in range(60):
        tree[f'r{i}a'] = (f't1_r{i}', [])
        tree[f'r{i}b'] = (f't1_r{i}', [])
    reddit = FakeReddit(tree)
    s = state([{'more': [f'r{i}' for i in range(60)], 'parent': 't3_aaa1', 'count': 180}])
    drive(s, reddit)
    assert not s['missing'] and len(s['nodes']) == 180
    first, retry = reddit.requests[0][1], reddit.requests[1][1]
    assert len(first) == 60 and len(reddit.requests) == 2, 'one cut answer (33 fit at 3 things each), one retry'
    assert set(retry) == set(first) - set(retry and first[:33]) and len(retry) <= 50, 'only the dropped ids, half the size'


def test_batches_of_deleted_comments_do_not_stop_the_live_ones_after_them():
    scenario = next(c for c in TREE['batching']['scenarios'] if c['name'] == 'deleted-only-batches-then-normal')
    gone = [f'd{i}' for i in range(200)]
    live = [f'l{i}' for i in range(40)]
    tree = {i: ('t3_aaa1', []) for i in gone + live + [f't{i}' for i in range(5)]}
    reddit = FakeReddit(tree, deleted=gone)
    s = state([{'id': f't{i}', 'parent': 't3_aaa1'} for i in range(5)] +
              [{'more': gone[:100], 'parent': 't3_aaa1'}, {'more': gone[100:], 'parent': 't3_aaa1'},
               {'more': live, 'parent': 't3_aaa1'}])
    drive(s, reddit)
    show_all(s)
    info = thread.coverage(s, 0, 0)
    assert info['complete'] is scenario['expected']['complete'] and len(s['missing']) == scenario['expected']['missing']
    assert all('t1_' + i in s['nodes'] for i in live) and len(reddit.requests) == 3


# --- fixture cases the old tests never ran, and the continuation that repeated itself -------------------------------

def test_a_requested_comment_takes_its_gaps_place_among_its_siblings():
    """tree.json merge.expansion-in-sibling-slot: the answer's comments (and what hangs under them) go where the gap was."""
    case = next(c for c in TREE['merge']['cases'] if c['name'] == 'expansion-in-sibling-slot')
    s = state(case['initial'])
    descriptor = thread.plan(s)
    assert descriptor['kind'] == case['expansions'][0]['request']['kind'] and \
        descriptor['ids'] == case['expansions'][0]['request']['ids']
    assert thread.merge(s, descriptor, items(case['expansions'][0]['answer']))
    assert names(s) == case['expected']['order'] and s['missing'] == case['expected']['missing']


def test_a_subtree_gap_that_brings_nothing_new_is_stalled_once_and_the_others_go_on():
    """tree.json batching.same-descriptor-twice-stalls-only-that-gap."""
    case = next(c for c in TREE['batching']['scenarios'] if c['name'] == 'same-descriptor-twice-stalls-only-that-gap')
    s = state([{'id': 'c1', 'parent': 't3_aaa1', 'replies': [{'more': [], 'parent': 't1_c1', 'count': 0}]},
               {'more': ['c2'], 'parent': 't3_aaa1', 'count': 1}])
    reddit = FakeReddit({'c1': ('t3_aaa1', []), 'c2': ('t3_aaa1', [])})
    drive(s, reddit)
    assert thread.coverage(s, 0, 0)['stalled'] == case['expected']['stalled_gaps'] and 't1_c2' in s['nodes']
    assert [kind for kind, _ in reddit.requests].count('subtree') == 1, 'tried once, not again'


def test_waiting_counts_only_what_a_continuation_could_show_at_this_depth():
    s = state([{'id': 'c1', 'parent': 't3_aaa1', 'replies': [{'id': 'c2', 'parent': 't1_c1'}]},
               {'id': 'c3', 'parent': 't3_aaa1'}])
    assert thread.waiting(s, 0) == 2 and thread.waiting(s, 1) == 3
    thread.select(s, 10, 0)
    assert thread.waiting(s, 0) == 0 and thread.waiting(s, 1) == 1, 'c2 is deeper than depth 0'
    assert thread.plan(s) is None, 'nothing to ask Reddit: a continuation at depth 0 has nothing to do'


def test_waiting_under_a_linked_comment_counts_from_that_comment():
    s = state([{'id': 'c1', 'parent': 't3_aaa1', 'replies': [{'id': 'c2', 'parent': 't1_c1', 'replies': [
        {'id': 'c3', 'parent': 't1_c2'}]}]}])
    assert thread.waiting(s, 0, 't1_c2') == 1 and thread.waiting(s, 1, 't1_c2') == 2
