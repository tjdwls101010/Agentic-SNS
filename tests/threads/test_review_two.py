"""Contract defects found in review: each reachable in an ordinary session, each pinned here."""
import re

from .fixtures.builders import envelope, preloader, route
from .helpers import CLI, POST, calls, data, run_cli

PROFILE_LOADER = 'adp_BarcelonaProfilePageDirectQueryRelayPreloader_hash'


def test_a_renamed_profile_query_is_rotation_not_an_unavailable_profile(routes):
    routes.edit('/@fixture_user', lambda html: html.replace(PROFILE_LOADER, 'adp_BarcelonaProfileHeaderV2QueryRelayPreloader_hash')).write()
    body = data(run_cli('about', '@fixture_user', '--json'))
    assert body['error'] == 'operation_rotated'


def test_a_logged_in_route_without_any_profile_is_unavailable(routes):
    routes.set('/@fixture_user', route([preloader('BarcelonaProfileCompletionQuery')],
                                       url='https://www.threads.com/@fixture_user')).write()
    result = run_cli('about', '@fixture_user', '--json')
    assert (result.returncode, data(result)['error']) == (9, 'unavailable')


def test_a_rendered_payload_of_another_shape_under_its_own_preloader_is_a_shape_change(routes):
    routes.edit('/', lambda html: html.replace('"feedData"', '"feedDataV2"')).write()
    assert data(run_cli('home', '--json'))['error'] == 'shape_changed'


def test_a_deleted_post_answering_404_is_unavailable(routes):
    routes.set('/@fixture_user/post/FIX_2', envelope('<html>not found</html>', status=404, url=POST)).write()
    result = run_cli('post', POST, '--json')
    assert (result.returncode, data(result)['error']) == (9, 'unavailable')


def test_refresh_reports_a_post_page_the_reader_could_not_read(routes):
    routes.copy('/@fixture_user', '/@fixture_viewer')
    routes.edit('/@fixture_user/post/FIX_2', lambda html: html.replace('"direct_replies": {"edges"', '"direct_replies": {"items"'))
    routes.write()
    assert data(run_cli('post', POST, '--json'))['error'] == 'shape_changed'
    assert data(run_cli('refresh', '--post', POST))['post_route'] == 'failed'


def test_a_listing_cap_too_small_to_continue_is_refused(fake_aside):
    for arguments in (('home', '--max-requests', '1'), ('user', '@fixture_user', '--max-requests', '1')):
        assert run_cli(*arguments).returncode == 2
    assert calls(fake_aside) == []
    assert run_cli('post', POST, '--max-requests', '1', '--json').returncode == 0


def test_chars_zero_is_refused_for_account_search_too(fake_aside):
    assert run_cli('search', 'python', '--type', 'users', '--chars', '0').returncode == 2
    assert calls(fake_aside) == []


def test_a_refresh_that_verified_nothing_is_a_failure_that_says_what_to_do(routes):
    routes.set('/@fixture_viewer', {'mode': 'fail'}).write()
    result = run_cli('refresh', '--post', POST)
    body = data(result)
    assert result.returncode == 6 and body['updated'] == [] and body['ok'] is False
    assert body['error'] and body['message'] and body['fix']


def test_a_refresh_that_verified_some_says_what_remains(routes):
    routes.copy('/@fixture_user', '/@fixture_viewer').write()
    result = run_cli('refresh', '--post', POST)
    body = data(result)
    assert result.returncode == 8 and body['updated'] and body['message'] and body['fix']


def test_commands_in_fixes_are_this_cli_invoked_the_way_more_is(routes):
    routes.set('BarcelonaFeedDirectQuery', {'status': 200, 'url': 'https://www.threads.com/graphql/query',
                                            'body': '{"data": null, "errors": [{"message": "execution error"}]}'})
    routes.write()
    fix = data(run_cli('home', '--feed', 'following', '--json'))['fix']
    named = re.findall(r'`([^`]+)`', fix)
    assert named and all(command.startswith(f'uv run "{CLI}" ') for command in named)
