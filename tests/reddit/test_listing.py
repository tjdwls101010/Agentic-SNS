"""Listing selection contracts at the offline page boundary."""
import pytest
from reddit_skill._errors import RedditError
from reddit_skill._listing import walk_listing_nodes, parse_thing, select_page


def thing(kind='t3', identity='a', **data):
    return {'kind': kind, 'data': {'name': kind + '_' + identity, 'id': identity, **data}}


def listing(children, after=None):
    return {'kind': 'Listing', 'data': {'children': children, 'after': after}}


def test_hundred_item_page_drains_without_losing_after_or_mixed_fullnames():
    payload = listing([thing(identity=str(i)) for i in range(99)] + [thing('t1', '0')], 't3_next')
    nodes = list(walk_listing_nodes(payload))
    assert len(nodes) == 100
    assert parse_thing(nodes[-1])['kind'] == 'comment'
    first = select_page(payload, limit=25, account='alice', captured_at='snapshot')
    assert len(first['results']) == 25
    assert len(first['state']['pending']) == 75
    state = first['state']
    records = first['results']
    for _ in range(3):
        page = select_page(state=state, limit=25, account='alice')
        records += page['results']
        state = page['state']
    assert len({r['fullname'] for r in records}) == 100
    assert records[-1]['fullname'] == 't1_0'
    assert state['after'] == 't3_next'
    assert state['captured_at'] == 'snapshot'
    next_page = select_page(listing([thing(identity='0'), thing(identity='next')]), state=state, account='alice')
    assert [r['fullname'] for r in next_page['results']] == ['t3_next']
    assert next_page['stop_reason'] == 'exhausted'


def test_window_marks_pinned_and_undated_without_premature_stopping():
    payload = listing([thing(identity='pin', created_utc=1, stickied=True), thing(identity='unknown'),
                       thing(identity='future', created_utc=31), thing(identity='upper', created_utc=30),
                       thing(identity='lower', created_utc=20), thing(identity='old', created_utc=19)], 't3_older')
    page = select_page(payload, since=20, until=30, limit=2)
    assert [r['window_excluded'] for r in page['results']] == ['pinned', 'undated']
    page = select_page(state=page['state'], since=20, until=30)
    assert [r['fullname'] for r in page['results']] == ['t3_upper', 't3_lower']
    assert page['stop_reason'] == 'window_reached'
    assert page['state']['pending'] == []
    assert select_page(listing([thing(created_utc=25)]), since=20)['stop_reason'] == 'exhausted'


@pytest.mark.parametrize('options', [{'since': 20, 'sort': 'hot'}, {'until': 30, 'sort': 'top'},
                                     {'since': 'bad'}, {'since': 30, 'until': 20}])
def test_invalid_windows_are_argument_errors(options):
    with pytest.raises(RedditError) as error:
        select_page(listing([]), **options)
    assert error.value.code == 2


@pytest.mark.parametrize('payload', [{}, {'kind': 'Listing', 'data': {}}, listing([thing('t3', 'x', name='t1_x')]),
                                     {'json': {'errors': [['BAD']], 'data': {'things': []}}}, listing([{'kind': 'wat', 'data': {}}])])
def test_malformed_envelopes_fail_instead_of_becoming_empty(payload):
    with pytest.raises(RedditError) as error:
        list(walk_listing_nodes(payload))
    assert error.value.code == 6


def test_account_binding_and_input_state_is_not_mutated():
    first = select_page(listing([thing(), thing(identity='b')]), limit=1, account='alice')
    with pytest.raises(RedditError):
        select_page(state=first['state'], account='bob')
    select_page(state=first['state'], account='alice')
    assert len(first['state']['pending']) == 1


def test_user_search_thing_uses_username_for_name_and_id_for_identity():
    page = {'kind': 'Listing', 'data': {'children': [{'kind': 't2', 'data': {'id': 'ab12', 'name': 'reader'}}], 'after': None}}
    result = select_page(page)
    assert result['results'][0]['fullname'] == 't2_ab12'
    assert result['results'][0]['name'] == 'reader'
