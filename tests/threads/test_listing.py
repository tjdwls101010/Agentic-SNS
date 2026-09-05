from threads_skill._listing import collect
from threads_skill._walk import Page
from threads_skill._errors import ThreadsError


def test_pending_records_survive_limits_and_no_cursor_progress_is_silently_accepted():
    pages = iter([Page(records=[{'id': '1'}, {'id': '2'}, {'id': '3'}], cursor='A', has_next=True),
                  Page(records=[{'id': '3'}, {'id': '4'}], cursor=None, has_next=False)])
    first = collect(lambda _: next(pages), limit=2)
    assert [x['id'] for x in first['results']] == ['1', '2']
    second = collect(lambda _: next(pages), limit=2, state=first['state'])
    assert [x['id'] for x in second['results']] == ['3', '4']
    assert second['stop_reason'] == 'exhausted'


def test_empty_intermediate_page_advances_and_failed_fetch_keeps_last_good_cursor():
    calls = []
    def fetch(after):
        calls.append(after)
        if after is None:
            return Page(cursor='A', has_next=True)
        if after == 'A':
            return Page(records=[{'id': '1'}], cursor='B', has_next=True)
        raise ThreadsError(6, 'Temporary failure')
    result = collect(fetch, limit=4)
    assert calls == [None, 'A', 'B']
    assert result['state']['after'] == 'B' and result['code'] == 8
    assert result['results'] == [{'id': '1'}]


def test_same_cursor_stops_with_partial_results_instead_of_looping():
    result = collect(lambda _: Page(records=[{'id': '1'}], cursor='A', has_next=True), limit=10)
    assert result['stop_reason'] == 'query_failure'
