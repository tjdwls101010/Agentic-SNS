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
