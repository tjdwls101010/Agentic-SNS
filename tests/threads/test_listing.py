"""Listings (home, profile tabs, search, the viewer's collections) through the CLI: pages, continuation and failure."""
import pytest

from .fixtures.builders import ERRORS, PROFILE, bbox, envelope, listed_post, null_profile, collections, preloader, route, tab
from .helpers import calls, data, run_cli, run_more

REPLIES = 'BarcelonaProfileRepliesTabDirectQuery'


def test_home_reads_the_rendered_first_page_and_never_a_feed_query(fake_aside):
    """Threads refuses feed queries from outside its app tab (2026-09-28): a feed is its route's rendered page."""
    first = run_cli('home', '--limit', '3', '--json')
    assert first.returncode == 0, first.stdout + first.stderr
    result = data(first)
    assert [p['id'] for p in result['results']] == ['1', '2', '3']
    assert result['stop_reason'] == 'not_paginable' and result['budget']['used'] == 1
    rest = data(run_more(result['next']))
    assert [p['id'] for p in rest['results']] == ['4'] and rest['next'] is None
    assert [c['snippet'] for c in calls(fake_aside)] == ['page', 'page']


def test_the_following_feed_is_the_following_route(fake_aside):
    result = run_cli('home', '--feed', 'following', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    assert data(result)['results'][0]['text'] == 'Synthetic followed post 1'
    assert [c['path'] for c in calls(fake_aside)] == ['/following']


def test_profile_continues_from_the_rendered_page_cursor(fake_aside):
    result = run_cli('user', '@fixture_user', '--limit', '6', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    assert [p['id'] for p in data(result)['results']] == ['1', '2', '3', '4', '5', '6']
    assert [c['key'] for c in calls(fake_aside)] == ['/@fixture_user', 'BarcelonaProfileThreadsTabDirectQuery:after']


def test_incompatible_ssr_cursor_restarts_direct_once_and_deduplicates(routes):
    routes.set('BarcelonaProfileThreadsTabDirectQuery:after', ERRORS['rotated'])
    routes.set('BarcelonaProfileThreadsTabDirectQuery', envelope(tab([listed_post(i) for i in range(1, 8)], 'B')))
    routes.write()
    result = run_cli('user', '@fixture_user', '--limit', '6', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    body = data(result)
    assert [p['id'] for p in body['results']] == ['1', '2', '3', '4', '5', '6']
    assert body['budget']['used'] == 3


@pytest.mark.parametrize('tab_name', ['replies', 'reposts', 'media'])
def test_private_tabs_are_unavailable_even_when_profile_ssr_is_null(routes, tab_name):
    private = {'pk': '42', 'username': 'fixture_user', 'text_post_app_is_private': True,
               'friendship_status': {'following': False}}
    null_profile(routes, private)
    routes.set('BarcelonaProfile' + tab_name.capitalize() + 'TabDirectQuery', envelope(tab([])))
    routes.write()
    result = run_cli('user', '@fixture_user', '--tab', tab_name, '--json')
    assert result.returncode == 9, result.stdout + result.stderr


def test_an_empty_page_advances_and_a_failed_page_resumes_from_the_last_good_cursor(routes):
    routes.set(REPLIES, envelope(tab([], 'A')))
    routes.set(REPLIES + ':after=A', envelope(tab([listed_post(1)], 'B')))
    routes.set(REPLIES + ':after=B', ERRORS['http'], envelope(tab([listed_post(2), listed_post(3)])))
    routes.write()
    partial = run_cli('user', '@fixture_user', '--tab', 'replies', '--limit', '4', '--json')
    assert partial.returncode == 8, partial.stdout + partial.stderr
    body = data(partial)
    assert [p['id'] for p in body['results']] == ['1'] and body['stop_reason'] == 'query_failure'
    resumed = run_more(body['next'])
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert [p['id'] for p in data(resumed)['results']] == ['2', '3']
    assert [c['key'] for c in calls(routes.path.parent / 'requests.ndjson')][-1] == REPLIES + ':after=B'


def test_a_repeated_cursor_stops_with_what_was_read_instead_of_looping(routes):
    routes.set(REPLIES, envelope(tab([listed_post(1)], 'A')))
    routes.set(REPLIES + ':after=A', envelope(tab([listed_post(2)], 'A')))
    routes.write()
    result = run_cli('user', '@fixture_user', '--tab', 'replies', '--limit', '5', '--json')
    assert result.returncode == 8, result.stdout + result.stderr
    assert data(result)['stop_reason'] == 'query_failure'
    assert [p['id'] for p in data(result)['results']] == ['1']


def test_a_page_without_its_pagination_contract_is_drift_not_the_end(routes):
    routes.set(REPLIES, envelope({'data': {'feedData': {'edges': []}}}))
    routes.write()
    result = run_cli('user', '@fixture_user', '--tab', 'replies', '--json')
    assert result.returncode == 6
    assert data(result)['error'] == 'shape_changed'


def test_a_response_of_another_shape_is_drift(routes):
    routes.set(REPLIES, envelope({'data': {'unexpected': True}}))
    routes.write()
    result = run_cli('user', '@fixture_user', '--tab', 'replies', '--json')
    assert result.returncode == 6
    assert data(result)['error'] == 'shape_changed'


def test_a_rendered_tab_for_another_profile_is_not_read_as_this_one(routes):
    routes.set('/@fixture_user', route([preloader('BarcelonaProfilePageDirectQuery', userID='42'),
                                         preloader('BarcelonaProfileThreadsTabDirectQuery', userID='99'),
                                         bbox({'user': PROFILE}), bbox({'mediaData': {'edges': []}})],
                                        url='https://www.threads.com/@fixture_user'))
    routes.write()
    result = run_cli('user', '@fixture_user', '--json')
    assert result.returncode == 6, result.stdout + result.stderr
    assert 'ThreadsTab' in data(result)['message']


@pytest.mark.parametrize('options,surface,recent', [([], 'default', 0), (['--tag'], 'tags', 0),
                                                    (['--sort', 'recent'], 'default', 1)])
def test_post_search_surface_and_sort_are_query_variables(routes, options, surface, recent):
    collections(routes).write()
    result = run_cli('search', 'python', '--limit', '3', '--json', *options)
    assert result.returncode == 0, result.stdout + result.stderr
    query = calls(routes.path.parent / 'requests.ndjson')[-1]['variables']
    assert (query['search_surface'], query['recent']) == (surface, recent)


def test_account_search_accepts_partial_optional_fields_and_is_one_batch(routes):
    collections(routes).write()
    result = run_cli('search', 'python', '--type', 'users', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    assert data(result)['stop_reason'] == 'not_paginable'


def test_liked_pending_tail_can_resume_but_never_requests_a_second_server_batch(routes):
    collections(routes).write()
    result = data(run_cli('me', 'liked', '--limit', '3', '--json'))
    resumed = run_cli('me', 'liked', '--after', str(result['next_handle']), '--limit', '10', '--json')
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    body = data(resumed)
    assert [p['id'] for p in body['results']] == ['4']
    assert body['budget']['used'] == 1 and body['stop_reason'] == 'not_paginable'


def test_unknown_saved_shape_is_not_claimed_to_be_empty(routes):
    collections(routes).write()
    result = run_cli('me', 'saved', '--json')
    assert result.returncode == 6
    assert data(result)['error'] == 'shape_changed'


def test_date_window_file_completion_is_zero_request_on_repeat(fake_aside, tmp_path):
    path = tmp_path / 'window.ndjson'
    first = run_cli('user', '@fixture_user', '--since', '2027-01-01', '--out', str(path), '--json')
    assert data(first)['stop_reason'] == 'window_reached', first.stdout
    second = run_cli('user', '@fixture_user', '--since', '2027-01-01', '--out', str(path), '--json')
    assert second.returncode == 0, second.stdout + second.stderr
    assert data(second)['budget']['used'] == 0


def test_a_date_window_keeps_only_posts_written_inside_it(routes):
    routes.set(REPLIES, envelope(tab([listed_post(1, taken_at=1790000000), listed_post(2, taken_at=1780000000)])))
    routes.write()
    result = run_cli('user', '@fixture_user', '--tab', 'replies', '--since', '2026-09-01', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    # 1790000000 is 2026-09-21; 1780000000 is 2026-05-28.
    assert [p['id'] for p in data(result)['results']] == ['1']



def test_the_profile_identity_comes_from_the_profile_preloader_not_another_user_id_on_the_page(routes):
    routes.edit('/@fixture_user', lambda html: html.replace(
        '"items": [', '"userID": "7", "items": [{"preloaderID": "adp_BarcelonaSomethingElseQueryRelayPreloader_hash", '
                      '"queryID": "1001", "variables": {"userID": "99"}}, ')).write()
    result = run_cli('user', '@fixture_user', '--limit', '6', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(routes.path.parent / 'requests.ndjson')[-1]['variables']['userID'] == '42'


def test_search_text_is_sent_as_typed_even_when_it_looks_like_a_template(routes):
    collections(routes).write()
    result = run_cli('search', '<b>C|D', '--limit', '1', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(routes.path.parent / 'requests.ndjson')[-1]['variables']['query'] == '<b>C|D'


def test_the_threads_tab_asks_for_pages_threads_still_serves(fake_aside):
    """Threads answers the threads tab's query with an execution error above ten posts a page (seen 2026-09-28)."""
    run_cli('user', '@fixture_user', '--limit', '6', '--json')
    sent = [c for c in calls(fake_aside) if c['name'] == 'BarcelonaProfileThreadsTabDirectQuery']
    assert sent and all(c['variables']['first'] <= 10 for c in sent)
