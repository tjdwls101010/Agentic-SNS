"""What a read sends (fixtures/requests.json): the variables each surface asks Threads with, run through the real CLI and
the scripted Aside; which relay provider values are accepted from a document; and which query names may ever be sent.
The headers and the form the page function builds are test_snippets.py's."""
import pytest

from sns.threads import web
from tests.sns.threads.data import fixture
from tests.sns.threads.scenes import feed_body, known_tab, post, query_result, queries, rerun, run, state
from tests.sns.threads.test_cli_profile import by_name, item, repost_screen, tab_body
from tests.sns.threads.test_cli_thread import URL, scripted_post

REQUESTS = fixture('requests.json')
CASES = {case['name']: case for case in REQUESTS['variables']}
USER = {'pk': '1000000001', 'username': 'example.author'}


def subset(expected, actual, path='$'):
    if isinstance(expected, dict):
        for key, value in expected.items():
            assert key in actual, f'{path}.{key} missing from {actual}'
            subset(value, actual[key], f'{path}.{key}')
    else:
        assert expected == actual, f'{path}: expected {expected!r}, got {actual!r}'


def sent(browser, index=-1):
    return queries(browser)[index]['args']['variables']


def test_the_profile_threads_tab_asks_ten_a_page(browser):
    known_tab(browser).respond('threads.query', by_name()).respond('threads.query', query_result(tab_body([item('3000000000000000401')])))
    run(browser, 'profile', '@example.author')
    subset(CASES['profile-threads-tab-first-10']['expected'], sent(browser))


def test_the_other_profile_tabs_ask_a_larger_page(browser):
    known_tab(browser).respond('threads.query', by_name()).respond('threads.page', repost_screen('BarcelonaProfileRepliesTabDirectQuery'))
    browser.respond('threads.query', query_result(tab_body([item('3000000000000000402')]), source='stored'))
    run(browser, 'profile', '@example.author', '--tab', 'replies')
    subset(CASES['profile-other-tabs-first']['expected'], sent(browser))


@pytest.mark.parametrize('name, words', [('search-posts-default', ['--sort', 'top']),
                                         ('search-posts-tag-recent', ['--type', 'tags', '--sort', 'recent'])])
def test_search_sends_the_words_the_surface_and_the_order(browser, name, words):
    case = CASES[name]
    known_tab(browser).respond('threads.query', query_result({'data': {'searchResults': {'edges': [], 'page_info': {
        'has_next_page': False, 'end_cursor': None}}}}))
    run(browser, 'search', case['input']['query'], *words)
    subset(case['expected'], sent(browser))


@pytest.mark.parametrize('name, feed, cursor', [('feed-for-you-next-page', 'foryou', 'FEEDCUR1'),
                                                ('feed-following-variant', 'following', 'FEEDCUR2')])
def test_the_next_feed_page_asks_with_the_cursor_and_the_pagination_source(browser, name, feed, cursor):
    case = CASES[name]
    known_tab(browser).respond('threads.query', query_result(feed_body([[post('A', '2026-10-08T03:00:00Z')]], True, cursor)))
    browser.respond('threads.query', query_result(feed_body([[post('B', '2026-10-08T02:00:00Z')]], False, None)))
    code, out, _ = run(browser, 'feed', '--feed', feed, '--limit', '2')
    assert code == 0, out
    subset(case['expected'], sent(browser))
    # the following feed's pagination variables are not confirmed by an observation of the app (appendix C, open item):
    # the variant and pagination source are pinned, nothing more is claimed


def test_the_post_page_asks_the_downward_query_with_the_sort(browser):
    scripted_post(browser)
    run(browser, 'post', URL)
    subset(CASES['post-page-downward']['expected'], sent(browser))


def test_the_next_reply_batch_asks_ten_where_the_app_was_seen_to_ask_four(browser):
    """P1 flagged: the app was observed asking for 4 replies a batch (observed_first); the reader has always asked for
    10, which the live smoke runs read without complaint. The observation does not overturn the shipped value, and a
    live-measured maximum would; until then the shipped 10 is pinned here and the difference named."""
    case = CASES['replies-next-batch']
    scripted_post(browser)
    code, out, _ = run(browser, 'post', URL)
    more = next(line for line in out.splitlines() if line.startswith('more: '))
    browser.respond('threads.state', state()).respond('threads.query', query_result(
        {'data': {'media': {'text_post_app_info': {'direct_replies': {'edges': [], 'page_info': {
            'has_next_page': False, 'end_cursor': None}}}}}}))
    rerun(browser, more)
    subset(case['expected'], sent(browser))
    assert case['observed_first'] == 4 and sent(browser)['first'] == 10


def test_followers_ask_twenty_for_the_profile(browser):
    known_tab(browser).respond('threads.query', by_name(USER)).respond('threads.query', query_result(
        {'data': {'fetch__XDTUserDict': {'followers': {'edges': []}}}}))
    run(browser, 'graph', '@example.author', 'followers')
    subset(CASES['followers-first-page']['expected'], sent(browser))


def test_following_pages_by_the_offset_with_the_tab_query(browser):
    page = {'data': {'user': {'following': {'edges': [{'node': {'pk': '2000000001', 'username': 'a.one'}}],
                                            'page_info': {'has_next_page': True, 'end_cursor': '20'}}}}}
    last = {'data': {'user': {'following': {'edges': [{'node': {'pk': '2000000002', 'username': 'b.two'}}],
                                            'page_info': {'has_next_page': False, 'end_cursor': None}}}}}
    known_tab(browser).respond('threads.query', by_name(USER)).respond('threads.query', query_result(page))
    browser.respond('threads.query', query_result(last))
    code, out, _ = run(browser, 'graph', '@example.author', 'following', '--limit', '2')
    assert code == 0, out
    subset(CASES['following-next-page']['expected'], sent(browser))


# --- the relay providers a document may teach, and the names that may ever be sent ----------------------------------------

def test_only_booleans_integers_and_constant_strings_are_taken_from_a_documents_providers():
    case = REQUESTS['provider_flags']
    assert web.provider_values(case['input']) == case['expected']


def test_the_variables_file_covers_every_surface_it_names():
    assert set(CASES) == {'profile-threads-tab-first-10', 'profile-other-tabs-first', 'search-posts-default',
                          'search-posts-tag-recent', 'feed-for-you-next-page', 'feed-following-variant',
                          'post-page-downward', 'replies-next-batch', 'followers-first-page', 'following-next-page'}
