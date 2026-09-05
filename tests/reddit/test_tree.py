"""Public pure tree seam: synthetic Reddit response to ordered reading state."""
from reddit_skill._target import Target
from reddit_skill._thread import create_state, select_batch


def listing(*children):
    return {'kind': 'Listing', 'data': {'children': list(children)}}


def comment(identity, parent='t3_p', replies=(), **data):
    return {'kind': 't1', 'data': {'id': identity, 'name': 't1_' + identity,
            'parent_id': parent, 'link_id': 't3_p', 'body': identity,
            'replies': listing(*replies) if replies else '', **data}}


def pair(*children):
    return [listing({'kind': 't3', 'data': {'id': 'p', 'title': 'Post'}}), listing(*children)]


def test_500_comments_are_cached_and_display_limits_do_not_trim_tree():
    response = pair(*(comment(str(i), replies=(comment(f'{i}b', f't1_{i}', replies=(
        comment(f'{i}c', f't1_{i}b', replies=(comment(f'{i}d', f't1_{i}c', replies=(
            comment(f'{i}e', f't1_{i}d'),)),)),)),)) for i in range(100)))
    state = create_state(response, Target('post', post_id='p'), 'best', 'alice')
    first = select_batch(state)
    assert len(state['nodes']) == 500
    assert len(first['records']) == 25
    assert max(r['depth'] for r in first['records']) == 2
    assert [r['fullname'] for r in first['records'][:4]] == ['t1_0', 't1_0b', 't1_0c', 't1_1']
    second = select_batch(state)
    assert len([r for r in second['records'] if not r['context']]) == 25
    assert second['records'][0]['fullname'] == 't1_8'
    assert second['records'][0]['context'] is True
    assert second['metadata']['unshown'] == 450


def test_increasing_depth_reveals_deep_reply_with_ancestor_context():
    state = create_state(pair(comment('a', replies=(comment('b', 't1_a', replies=(
        comment('c', 't1_b'),)),))), Target('post', post_id='p'))
    select_batch(state, depth=1)
    batch = select_batch(state, depth=2)
    assert [(r['fullname'], r['context']) for r in batch['records']] == [
        ('t1_a', True), ('t1_b', True), ('t1_c', False)]
    assert batch['metadata']['complete'] is True


def test_anchor_is_validated_and_included_beyond_depth_even_with_limit_one():
    import pytest
    from reddit_skill._errors import RedditError
    response = pair(comment('a', replies=(comment('b', 't1_a', replies=(comment('c', 't1_b'),)),)))
    state = create_state(response, Target('comment', post_id='p', comment_id='c'))
    batch = select_batch(state, limit=1, depth=0)
    assert [(r['fullname'], r['context'], r['anchor']) for r in batch['records']] == [
        ('t1_a', True, False), ('t1_b', True, False), ('t1_c', False, True)]
    for target in (Target('comment', post_id='p', comment_id='absent'), Target('post', post_id='other')):
        with pytest.raises(RedditError) as error:
            create_state(response, target)
        assert error.value.code == 9


def more(parent, *ids, count=1):
    return {'kind': 'more', 'data': {'parent_id': parent, 'children': list(ids), 'count': count}}


def test_flat_expansion_keeps_pointer_slot_reconnects_orphans_and_tracks_missing():
    from reddit_skill._thread import merge_more, next_expansion
    state = create_state(pair(comment('a'), more('t3_p', 'b', 'missing'), comment('z'),
                              more('t3_p', 'c')), Target('post', post_id='p'))
    expansion = next_expansion(state)
    assert expansion['ids'] == ['b', 'missing']
    merge_more(state, [comment('child', 't1_b'), comment('b'), more('t1_b', 'later')],
               expansion['ids'], expansion['pointer'])
    batch = select_batch(state)
    assert [r['fullname'] for r in batch['records']] == ['t1_a', 't1_b', 't1_child', 't1_z']
    assert state['missing'] == ['missing']
    assert state['orphans'] == {}
    assert next_expansion(state)['ids'] == ['later']
    assert len(state['pending_more']) == 2  # same parent/count, different children are distinct
    assert batch['metadata']['complete'] is False


def test_orphan_is_visible_then_reconnects_when_parent_arrives():
    from reddit_skill._thread import merge_more, next_expansion
    state = create_state(pair(more('t3_p', 'child'), more('t3_p', 'parent')), Target('post', post_id='p'))
    exp = next_expansion(state)
    merge_more(state, [comment('child', 't1_parent')], exp['ids'], exp['pointer'])
    batch = select_batch(state)
    assert batch['records'][0]['orphan'] is True
    assert batch['records'][0]['parent'] == 't1_parent'
    exp = next_expansion(state)
    merge_more(state, [comment('parent')], exp['ids'], exp['pointer'])
    assert state['orphans'] == {}
    assert state['nodes']['t1_child']['shown'] is True
    assert state['nodes']['t1_child']['data']['depth'] == 1
    assert [r['fullname'] for r in select_batch(state)['records']] == ['t1_parent']


def test_empty_pointer_uses_subtree_and_repeated_response_stalls():
    from reddit_skill._thread import merge_more, next_expansion
    state = create_state(pair(comment('a', replies=(more('t1_a', count=2),)),
                              more('t3_p', count=5)), Target('post', post_id='p'))
    select_batch(state)
    exp = next_expansion(state)
    assert exp['kind'] == 'subtree'
    assert exp['target'] == 'https://www.reddit.com/comments/p/_/a/'
    merge_more(state, pair(comment('a', replies=(more('t1_a', count=2),))), [], exp['pointer'])
    assert select_batch(state)['metadata']['stop_reason'] == 'stalled'
    assert next_expansion(state) is None
    root_state = create_state(pair(more('t3_p', count=3)), Target('post', post_id='p'))
    assert next_expansion(root_state) is None
    assert root_state['unresolved']
    assert select_batch(root_state)['metadata']['complete'] is False


def test_expansion_batches_100_ids_and_does_not_request_known_or_attempted_ids_again():
    from reddit_skill._thread import merge_more, next_expansion
    ids = [str(i) for i in range(105)]
    state = create_state(pair(comment('before'), more('t3_p', *ids), comment('after')),
                         Target('post', post_id='p'))
    exp = next_expansion(state)
    assert len(exp['ids']) == 100
    merge_more(state, [comment(i) for i in exp['ids']], exp['ids'], exp['pointer'])
    exp = next_expansion(state)
    assert exp['ids'] == ['100', '101', '102', '103', '104']
    merge_more(state, [comment(i) for i in exp['ids']] + [more('t1_0', '0', '100')],
               exp['ids'], exp['pointer'])
    assert next_expansion(state) is None
    batch = select_batch(state, limit=200)
    assert batch['records'][0]['fullname'] == 't1_before'
    assert batch['records'][-1]['fullname'] == 't1_after'
    assert len(batch['records']) == 107
    assert batch['metadata']['complete'] is True


def test_expand_connected_dfs_before_orphans_and_remove_consumed_orphan_slots():
    from reddit_skill._thread import merge_more, next_expansion
    state = create_state(pair(more('t3_p', 'a'), more('t1_absent', 'a')),
                         Target('post', post_id='p'))
    exp = next_expansion(state)
    assert exp['parent'] == 't3_p'
    merge_more(state, [comment('a')], exp['ids'], exp['pointer'])
    assert next_expansion(state) is None
    assert select_batch(state)['metadata']['complete'] is True
    assert state['orphans'] == {}


def test_same_empty_subtree_pointer_preserves_unresolved_remainder():
    from reddit_skill._thread import merge_more, next_expansion
    state = create_state(pair(comment('a', replies=(more('t1_a', count=3),))), Target('post', post_id='p'))
    select_batch(state)
    exp = next_expansion(state)
    merge_more(state, pair(comment('a', replies=(comment('b', 't1_a'), more('t1_a', count=2)))),
               [], exp['pointer'])
    result = select_batch(state)
    assert [r['fullname'] for r in result['records'] if not r['context']] == ['t1_b']
    assert result['metadata']['complete'] is False
    assert result['metadata']['stop_reason'] == 'stalled'
    assert next_expansion(state) is None


def test_unexpandable_orphan_stalls_after_display_but_hidden_depth_can_resume():
    state = create_state(pair(comment('a', 't1_absent')), Target('post', post_id='p'))
    assert select_batch(state)['metadata']['stop_reason'] == 'stalled'
    hidden = create_state(pair(comment('a', replies=(comment('b', 't1_a'),))), Target('post', post_id='p'))
    assert select_batch(hidden, depth=0)['metadata']['stop_reason'] == 'limit_reached'
    assert select_batch(hidden, depth=1)['metadata']['complete'] is True


def test_parent_cycles_are_rejected_at_initial_and_expansion_boundaries():
    import pytest
    from reddit_skill._errors import RedditError
    from reddit_skill._thread import merge_more, next_expansion
    cyclic = [comment('a', 't1_b'), comment('b', 't1_a')]
    with pytest.raises(RedditError) as error:
        create_state(pair(*cyclic), Target('comment', post_id='p', comment_id='a'))
    assert error.value.code == 6
    state = create_state(pair(more('t3_p', 'a')), Target('post', post_id='p'))
    exp = next_expansion(state)
    with pytest.raises(RedditError) as error:
        merge_more(state, cyclic, exp['ids'], exp['pointer'])
    assert error.value.code == 6


def test_malformed_nested_shapes_are_error_six_without_partial_expansion():
    import copy
    import pytest
    from reddit_skill._errors import RedditError
    from reddit_skill._thread import merge_more, next_expansion
    bad_replies = comment('a')
    bad_replies['data']['replies'] = {'kind': 'Listing', 'data': None}
    bad_ids = more('t3_p', 'abc')
    bad_ids['data']['children'] = 'abc'
    malformed = [bad_replies, bad_ids, {'kind': 't1', 'data': None},
                 {'kind': 'Listing', 'data': {'children': {}}},
                 {'kind': 'more', 'data': {'children': [None]}},
                 {'kind': 't1', 'data': {'id': 'a', 'parent_id': []}},
                 {'kind': 'unknown', 'data': {}}, 42]
    for bad in malformed:
        with pytest.raises(RedditError) as error:
            create_state(pair(bad), Target('post', post_id='p'))
        assert error.value.code == 6
        state = create_state(pair(more('t3_p', 'a')), Target('post', post_id='p'))
        exp = next_expansion(state)
        before = copy.deepcopy(state)
        with pytest.raises(RedditError) as error:
            merge_more(state, [comment('valid'), bad], exp['ids'], exp['pointer'])
        assert error.value.code == 6
        assert state == before


def test_anchor_ancestors_are_not_claimed_as_previously_seen():
    state = create_state(pair(comment('a', replies=(comment('b', 't1_a'),))), Target('comment', post_id='p', comment_id='b'))
    rows = select_batch(state, limit=1, depth=0)['records']
    assert rows[0]['context'] and rows[0].get('shown_earlier') is False
