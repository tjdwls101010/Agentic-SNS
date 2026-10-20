"""Pagination in the server's order (paging.paginate): a repeated cursor is caught across continuations too."""
from reddit.paging import paginate


def test_a_cursor_repeated_across_continuations_is_a_failure():
    calls = []

    def fetch(cursor):
        calls.append(cursor)
        return [{'id': 't3_same'}], {'has_next_page': True, 'end_cursor': 'C'}, True

    result = paginate(fetch, max_pages=1)
    for _ in range(3):
        if result['failure'] or result['state'] is None:
            break
        result = paginate(fetch, state=result['state'], max_pages=1)
    assert result['failure'] is not None and result['failure'].reason == 'pagination'
    assert len(calls) <= 3


def test_a_page_that_failed_to_arrive_can_be_asked_again():
    from reddit.errors import RedditError
    answers = [([{'id': 't3_a'}], {'has_next_page': True, 'end_cursor': 't3_a'}, True), RedditError(8, 'spent', 'x')]

    def fetch(cursor):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    first = paginate(fetch, limit=3)
    assert first['failure'].code == 8 and first['state']['cursor'] == 't3_a'
    answers.append(([{'id': 't3_b'}], {'has_next_page': False}, True))
    second = paginate(fetch, limit=3, state=first['state'])
    assert second['failure'] is None and [r['id'] for r in second['results']] == ['t3_b']
