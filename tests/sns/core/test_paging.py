"""Cursor and page-number pagination in the server's order (paging.paginate)."""
import pytest

from sns.errors import SnsError
from sns.page import Page
from sns.paging import paginate, record_key


def pages(*answers):
    """A fetch that hands out the answers in order (an exception is raised), recording the cursors asked for."""
    queue, asked = list(answers), []

    def fetch(cursor):
        asked.append(cursor)
        answer = queue.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
    fetch.asked = asked
    return fetch


def ids(records):
    return [r['id'] for r in records]


def test_a_limit_inside_a_page_keeps_the_rest_for_the_continuation_without_a_request():
    fetch = pages(Page([{'id': 'a'}, {'id': 'b'}, {'id': 'c'}], next='C2'))
    first = paginate(fetch, limit=2)
    assert ids(first['results']) == ['a', 'b'] and first['stop_reason'] == 'limit_reached'
    second = paginate(fetch, limit=2, state=first['state'], max_pages=1)
    assert ids(second['results']) == ['c'] and fetch.asked == [None]  # the tail came from the state
    assert second['stop_reason'] == 'limit_reached' and second['state']['cursor'] == 'C2'


def test_whole_pages_are_committed_once_each_and_never_split():
    committed = []
    fetch = pages(Page([{'id': 'a'}, {'id': 'b'}], next='C2'), Page([{'id': 'c'}], end=True))
    result = paginate(fetch, limit=1, whole_pages=True,
                      commit=lambda records, state, reason, skipped: committed.append((ids(records), reason)))
    assert committed == [(['a', 'b'], 'limit_reached')]
    assert ids(result['results']) == ['a', 'b']


def test_repeats_are_dropped_and_the_source_end_is_exhausted():
    fetch = pages(Page([{'id': 'a'}, {'id': 'b'}], next='C2'), Page([{'id': 'b'}, {'id': 'c'}], end=True))
    result = paginate(fetch)
    assert ids(result['results']) == ['a', 'b', 'c'] and result['stop_reason'] == 'exhausted'
    assert result['state'] is None


def test_a_page_that_closes_the_window_ends_reading_as_window_reached():
    fetch = pages(Page([{'id': 'a'}], next='C2'), Page([{'id': 'b'}], next='C3'))
    result = paginate(fetch, closes=lambda records: records[0]['id'] == 'b')
    assert result['stop_reason'] == 'window_reached' and fetch.asked == [None, 'C2']


def test_a_cursor_repeated_across_continuations_is_a_failure():
    calls = []

    def fetch(cursor):
        calls.append(cursor)
        return Page([{'id': 'same'}], next='C')

    result = paginate(fetch, max_pages=1)
    for _ in range(3):
        if result['failure'] or result['state'] is None:
            break
        result = paginate(fetch, state=result['state'], max_pages=1)
    assert result['failure'] is not None and result['failure'].reason == 'pagination'
    assert len(calls) <= 3


def test_a_page_that_failed_to_arrive_can_be_asked_again():
    fetch = pages(Page([{'id': 'a'}], next='C1'), SnsError('failed', 'lost', 'retry'))
    first = paginate(fetch, limit=3)
    assert first['failure'].kind == 'failed' and first['state']['cursor'] == 'C1'
    again = pages(Page([{'id': 'b'}], end=True))
    second = paginate(again, limit=3, state=first['state'])
    assert second['failure'] is None and ids(second['results']) == ['b'] and again.asked == ['C1']


def test_pages_with_nothing_new_stop_after_the_idle_limit():
    fetch = pages(Page([{'id': 'a'}], next='C1'), Page([{'id': 'a'}], next='C2'), Page([], next='C3'),
                  Page([], next='C4'))
    two = paginate(fetch)
    assert two['failure'].reason == 'pagination' and fetch.asked == [None, 'C1', 'C2']
    fetch = pages(Page([{'id': 'a'}], next='C1'), Page([], next='C2'), Page([], next='C3'), Page([], next='C4'))
    three = paginate(fetch, idle_limit=3)
    assert three['failure'].reason == 'pagination' and fetch.asked == [None, 'C1', 'C2', 'C3']


def test_a_page_of_only_unreadable_entries_is_a_changed_answer_not_an_empty_one():
    result = paginate(pages(Page([], next='C1', unreadable=3)))
    assert result['failure'].reason == 'stale_query' and result['failure'].kind == 'failed'


def test_a_page_without_usable_pagination_data_is_a_failure_after_its_records():
    result = paginate(pages(Page([{'id': 'a'}])))
    assert ids(result['results']) == ['a'] and result['failure'].reason == 'pagination'


def test_a_platform_stop_ends_reading_with_its_reason_and_keeps_the_page():
    result = paginate(pages(Page([{'id': 'a'}], next={'page': 2}, stop='server_capped')))
    assert ids(result['results']) == ['a'] and result['stop_reason'] == 'server_capped' and result['failure'] is None
    assert result['state'] is None


def test_page_number_cursors_are_cursors():
    fetch = pages(Page([{'id': 'a'}], next={'page': 2}), Page([{'id': 'b'}], end=True))
    result = paginate(fetch)
    assert fetch.asked == [None, {'page': 2}] and result['stop_reason'] == 'exhausted'


def test_what_a_page_left_out_is_added_up():
    fetch = pages(Page([{'id': 'a'}], next='C1', left_out={'promoted': 1}),
                  Page([{'id': 'b'}], end=True, left_out={'promoted': 2, 'other': 1}))
    result = paginate(fetch)
    assert result['left_out'] == {'promoted': 3, 'other': 1}


def test_skipped_records_are_counted_once_across_continuations():
    fetch = pages(Page([{'id': 'a'}, {'id': 'x'}], next='C1'))
    first = paginate(fetch, skip=lambda r: r['id'] == 'x', max_pages=1)
    assert ids(first['results']) == ['a'] and first['skipped'] == ['x']


def test_record_key_falls_back_to_username_then_url():
    assert record_key({'id': '1', 'username': 'A'}) == '1'
    assert record_key({'username': 'Alice'}) == '@alice'
    assert record_key({'url': 'https://x'}) == 'https://x'


def test_a_natural_stop_on_a_page_split_by_the_limit_survives_into_the_continuation():
    """Found by review (facebook depth-2 replies, 2026-10-21): the page that ends the source with a natural stop
    (server_capped) was split by --limit; the continuation served the rest from the saved state and called it
    exhausted. The saved state carries the stop."""
    from sns.page import Page
    from sns.paging import paginate

    def fetch(cursor):
        return Page([{'id': 'a'}, {'id': 'b'}], stop='server_capped')

    first = paginate(fetch, limit=1)
    assert first['stop_reason'] == 'limit_reached' and first['state'] is not None
    rest = paginate(lambda cursor: pytest.fail('nothing more is requested'), limit=5, state=first['state'])
    assert [r['id'] for r in rest['results']] == ['b'] and rest['stop_reason'] == 'server_capped'
    assert rest['state'] is None
