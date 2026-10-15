"""paging core: server order, dedupe, boundary stop, unshown tail, cursor repeats (fixtures/paging.json).

Date-window policy belongs to listing and is tested through the CLI; here the boundary and skip are plain callbacks.
"""
import pytest

from conftest import fixture
from facebook import paging
from facebook.errors import FacebookError

CORE = ['server-order-and-dedupe', 'limit-keeps-unshown-tail', 'tail-then-end', 'sponsored-skipped-once',
        'explicit-empty-first-page', 'readable-zero-from-nonempty-connection', 'items-without-page-info',
        'repeated-cursor', 'failure-keeps-earlier-records']
SCENARIOS = {s['name']: s for s in fixture('paging.json')['scenarios']}


class Source:
    """Serves the scenario's pages in order; records the cursors it was asked for."""

    def __init__(self, pages):
        self.pages, self.asked = list(pages), []

    def __call__(self, cursor):
        page = self.pages.pop(0)
        if 'error' in page:
            raise FacebookError(page['error'], 'the request failed', 'retry')
        self.asked.append(cursor)  # pages fetched: the ones that came back
        if page.get('empty'):
            return [], {'has_next_page': False, 'end_cursor': None}, False
        return page['records'], page['page_info'], page.get('has_items', bool(page['records']))


def read(scenario, pages, state=None, limit=None):
    options = scenario['options']
    skip = (lambda record: record.get('sponsored')) if options['skip_sponsored'] else None
    source = Source(pages)
    result = paging.paginate(source, limit=limit if limit is not None else options['limit'], state=state, skip=skip)
    return result, source


def check(expected, result, source):
    assert [r['id'] for r in result['results']] == expected['shown']
    assert len(source.asked) == expected['pages_fetched']
    if 'failure' in expected:
        failure = result['failure']
        assert failure is not None
        if expected['failure'] == 'query':
            assert failure.code == 6 and failure.reason not in ('pagination', 'stale_query')
        else:
            assert failure.reason == expected['failure']
        return
    assert result['failure'] is None
    assert result['stop_reason'] == expected['stop_reason']
    assert [r['id'] for r in (result['state'] or {}).get('pending', [])] == expected['pending']
    assert (result['state'] is not None and result['state']['cursor'] != paging.END
            or bool((result['state'] or {}).get('pending'))) == expected['continues']
    if 'sponsored_skipped' in expected:
        assert len(result['skipped']) == expected['sponsored_skipped']


@pytest.mark.parametrize('name', CORE)
def test_core_scenarios(name):
    scenario = SCENARIOS[name]
    result, source = read(scenario, scenario['pages'])
    check(scenario['expected'], result, source)
    if 'then' in scenario:
        later = scenario['then']
        result, source = read(scenario, later['pages'], state=result['state'], limit=later['continue_with']['limit'])
        check(later['expected'], result, source)


def test_a_boundary_callback_closes_the_source_on_that_page():
    pages = [{'records': [{'id': 'A'}, {'id': 'B', 'old': True}], 'page_info': {'has_next_page': True, 'end_cursor': 'C1'}},
             {'records': [{'id': 'NEVER'}], 'page_info': {'has_next_page': False, 'end_cursor': None}}]
    source = Source(pages)
    result = paging.paginate(source, closes=lambda records: any(r.get('old') for r in records),
                             keep=lambda record: not record.get('old'))
    assert [r['id'] for r in result['results']] == ['A']
    assert result['stop_reason'] == 'window_reached' and len(source.asked) == 1


def test_whole_pages_are_kept_together_for_collections():
    pages = [{'records': [{'id': 'A'}, {'id': 'B'}, {'id': 'C'}], 'page_info': {'has_next_page': True, 'end_cursor': 'C1'}}]
    committed = []
    result = paging.paginate(Source(pages), limit=2, whole_pages=True,
                             commit=lambda records, state, reason, skipped: committed.append(([r['id'] for r in records], reason)))
    assert [r['id'] for r in result['results']] == ['A', 'B', 'C']
    assert committed == [(['A', 'B', 'C'], 'limit_reached')]


def test_max_pages_stops_after_one_page_and_continues_later():
    pages = [{'records': [{'id': 'A'}], 'page_info': {'has_next_page': True, 'end_cursor': 'C1'}}]
    result = paging.paginate(Source(pages), max_pages=1)
    assert result['stop_reason'] == 'limit_reached' and result['state']['cursor'] == 'C1'


def test_a_budget_stop_keeps_the_cursor_of_the_unread_page():
    def fetch(cursor):
        if cursor is None:
            return [{'id': 'A'}], {'has_next_page': True, 'end_cursor': 'C1'}, True
        raise FacebookError(8, 'The request budget (--max-requests) is spent.', 'more')
    result = paging.paginate(fetch)
    assert [r['id'] for r in result['results']] == ['A']
    assert result['failure'].code == 8 and result['state']['cursor'] == 'C1'
