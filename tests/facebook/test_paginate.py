from _paginate import paginate


def test_limit_preserves_unshown_items_without_fetching_same_page_twice():
    calls = []
    def fetch(cursor):
        calls.append(cursor)
        return ([{'id': '1'}, {'id': '2'}, {'id': '3'}], {'end_cursor': 'next', 'has_next_page': True})
    first = paginate(fetch, limit=2)
    assert [x['id'] for x in first['results']] == ['1', '2']
    assert first['stop_reason'] == 'limit_reached'
    assert first['cursor'] == 'next'
    assert first['pending'] == [{'id': '3'}]
    second = paginate(fetch, limit=1, cursor=first['cursor'], pending=first['pending'])
    assert [x['id'] for x in second['results']] == ['3']
    assert calls == [None]


def test_exhausted_last_page_pending_does_not_restart_from_beginning():
    def fetch(cursor):
        return ([{'id': '1'}, {'id': '2'}], {'has_next_page': False, 'end_cursor': None})
    first = paginate(fetch, limit=1)
    def forbidden(cursor):
        raise AssertionError('must not fetch after explicit exhaustion')
    second = paginate(forbidden, limit=5, cursor=first['cursor'], pending=first['pending'])
    assert [x['id'] for x in second['results']] == ['2']
    assert second['stop_reason'] == 'exhausted'


def test_ranked_date_window_filters_without_resorting_or_stopping_at_old_post():
    pages = {
        None: ([{'id': 'old', 'created_at': '2020-01-01T00:00:00Z'},
                {'id': 'pinned', 'pinned': True, 'created_at': '2020-01-01T00:00:00Z'}],
               {'end_cursor': 'b', 'has_next_page': True}),
        'b': ([{'id': 'newer', 'created_at': '2026-09-03T00:00:00Z'},
               {'id': 'old'}, {'id': 'new', 'created_at': '2026-09-02T00:00:00Z'},
               {'id': 'future', 'created_at': '2026-10-01T00:00:00Z'}], {'has_next_page': False}),
    }
    result = paginate(pages.__getitem__, since='2026-09-01', until='2026-09-30')
    assert [x['id'] for x in result['results']] == ['pinned', 'newer', 'new']
    assert result['stop_reason'] == 'exhausted'


def test_missing_page_info_is_partial_failure_not_honest_exhaustion():
    calls = []
    def fetch(cursor):
        assert not calls, 'must not repeat a page with no continuation metadata'
        calls.append(cursor)
        return [{'id': '1'}], {}
    result = paginate(fetch)
    assert result['ok'] is False
    assert result['stop_reason'] == 'query_failure'
    assert [x['id'] for x in result['results']] == ['1']


def test_page_commit_limit_keeps_whole_page_and_deduplicates_existing_ids():
    commits = []
    result = paginate(lambda _: ([{'id': '1'}, {'id': '2'}, {'id': '3'}],
                                 {'has_next_page': True, 'end_cursor': 'b'}),
                      limit=1, seen={'1'}, page_limit=True,
                      commit=lambda records, cursor, reason: commits.append((records, cursor, reason)))
    assert [x['id'] for x in result['results']] == ['2', '3']
    assert commits == [([{'id': '2'}, {'id': '3'}], 'b', 'limit_reached')]


def test_budget_failure_retains_results_and_uncommitted_cursor():
    from _errors import FacebookError
    def fetch(cursor):
        if cursor:
            raise FacebookError(8, 'Request budget reached.', 'Continue later.')
        return [{'id': '1'}], {'has_next_page': True, 'end_cursor': 'next'}
    result = paginate(fetch)
    assert result['ok'] is False
    assert result['stop_reason'] == 'budget'
    assert result['cursor'] == 'next'
    assert result['results'] == [{'id': '1'}]


def test_deferred_pagination_ignores_nested_other_connections():
    from _paginate import find_page_info
    raw = b'{"data":{"news_feed":{"edges":[]},"other":{"page_info":{"end_cursor":"wrong"}}}}\n'
    raw += b'{"path":["viewer","news_feed"],"data":{"page_info":{"has_next_page":false}}}\n'
    assert find_page_info(raw, 'news_feed') == {'has_next_page': False}


def test_page_info_accepts_the_same_anti_json_prefix_as_transport():
    from _paginate import find_page_info
    raw = b'for (;;);{"data":{"news_feed":{"edges":[],"page_info":{"has_next_page":true,"end_cursor":"next"}}}}'
    assert find_page_info(raw, 'news_feed') == {'has_next_page': True, 'end_cursor': 'next'}
