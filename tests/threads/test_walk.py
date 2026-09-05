import pytest

from threads_skill._walk import read_page
from threads_skill._errors import ThreadsError


def test_empty_intermediate_page_preserves_cursor_but_missing_page_info_is_drift():
    page = read_page({'data': {'feedData': {'edges': [], 'page_info': {'has_next_page': True, 'end_cursor': 'next'}}}}, 'BarcelonaFeedDirectQuery')
    assert page.has_next and page.cursor == 'next' and page.records == []
    with pytest.raises(ThreadsError) as error:
        read_page({'data': {'feedData': {'edges': []}}}, 'BarcelonaFeedDirectQuery')
    assert error.value.error == 'envelope_drift'


def test_policy_distinguishes_followers_search_and_terminal_relay():
    followers = read_page({'data': {'user': {'followers': {'edges': [], 'page_info': {'has_next_page': False}}},
                                  'counts': {'followers': 1000}}}, 'BarcelonaFriendshipsFollowersTabQuery')
    assert followers.stop == 'server_capped' and followers.reported_total == 1000
    accounts = read_page({'data': {'xdt_api__v1__users__search_connection': {'edges': []}}}, 'useBarcelonaAccountSearchGraphQLDataSourceQuery')
    assert accounts.stop == 'not_paginable'
    feed = read_page({'data': {'feedData': {'edges': [], 'page_info': {'has_next_page': False}}}}, 'BarcelonaFeedDirectQuery')
    assert feed.stop == 'exhausted'
