"""What a failure tells the caller to do: a stale query is refreshed, a changed shape is reported, and every command a
fix names can be run as written."""
import re

import pytest

from .fixtures.builders import ERRORS, envelope, feed, listed_post, null_profile, tab
from .helpers import POST, calls, data, more_args, run_cli

FOLLOWING = 'BarcelonaFeedDirectQuery'


def commands(fix):
    """The commands a fix names, as the words after this CLI's invocation."""
    return [' '.join(more_args(command)) for command in re.findall(r'`([^`]+)`', fix)]


def test_a_rotated_route_query_is_refreshed_then_retried(routes):
    routes.set(FOLLOWING, ERRORS['rotated']).write()
    body = data(run_cli('home', '--feed', 'following', '--json'))
    assert body['error'] == 'operation_rotated'
    assert commands(body['fix']) == ['refresh'] and 'retry' in body['fix']


def test_a_rotated_app_only_query_needs_capture_and_the_user_first(routes):
    routes.set('BarcelonaFriendshipsFollowersTabQuery', ERRORS['rotated']).write()
    body = data(run_cli('graph', '@fixture_user', 'followers', '--json'))
    assert body['error'] == 'operation_rotated'
    assert commands(body['fix']) == ['refresh --capture --post <public post URL>']
    assert 'ask the user first' in body['fix'].lower() and 'tab' in body['fix']


def test_a_changed_shape_is_not_sent_to_refresh(routes):
    routes.set(FOLLOWING, envelope({'data': {'feedData': {'edges': []}}})).write()
    body = data(run_cli('home', '--feed', 'following', '--json'))
    assert body['error'] == 'shape_changed'
    assert 'refresh cannot repair' in body['fix'] and 'home reader' in body['fix']
    assert commands(body['fix']) == []


def test_the_rendered_cursor_falls_back_once_when_its_page_has_changed_shape(routes):
    routes.set('BarcelonaProfileThreadsTabDirectQuery:after', envelope({'data': {'mediaData': {'edges': [{}]}}}))
    routes.set('BarcelonaProfileThreadsTabDirectQuery', envelope(tab([listed_post(i) for i in range(1, 8)])))
    routes.write()
    body = data(run_cli('user', '@fixture_user', '--limit', '6', '--json'))
    assert [p['id'] for p in body['results']] == ['1', '2', '3', '4', '5', '6']


def test_a_block_is_never_followed_by_the_fallback(routes):
    routes.set('BarcelonaProfileThreadsTabDirectQuery:after', ERRORS['checkpoint']).write()
    result = run_cli('user', '@fixture_user', '--limit', '6', '--json')
    assert result.returncode == 5
    assert [c['key'] for c in calls(routes.path.parent / 'requests.ndjson')][-1] == \
        'BarcelonaProfileThreadsTabDirectQuery:after'


def test_an_unavailable_profile_says_so_instead_of_pointing_at_help(routes):
    private = {'pk': '42', 'username': 'fixture_user', 'text_post_app_is_private': True,
               'friendship_status': {'following': False}}
    null_profile(routes, private)
    routes.set('BarcelonaProfileRepliesTabDirectQuery', envelope(tab([]))).write()
    result = run_cli('user', '@fixture_user', '--tab', 'replies', '--json')
    assert result.returncode == 9 and '--help' not in data(result)['fix']


@pytest.mark.parametrize('setup,arguments', [
    (lambda r: r.set(FOLLOWING, ERRORS['rotated']), ('home', '--feed', 'following')),
    (lambda r: r.set('BarcelonaFriendshipsFollowersTabQuery', ERRORS['rotated']), ('graph', '@fixture_user', 'followers')),
    (lambda r: r.set(FOLLOWING, ERRORS['checkpoint']), ('home', '--feed', 'following')),
    (lambda r: r.set(FOLLOWING, ERRORS['login']), ('home', '--feed', 'following')),
    (lambda r: r.set(FOLLOWING, envelope(feed([listed_post(1)], 'A'))), ('home', '--feed', 'following', '--limit', '1')),
])
def test_every_command_a_fix_or_continuation_names_runs_as_written(routes, setup, arguments):
    setup(routes)
    routes.write()
    body = data(run_cli(*arguments, '--json'))
    named = commands(body.get('fix') or '')
    for command in named:
        words = command.replace('<public post URL>', POST).split()
        assert run_cli(*words).returncode != 2, command
    assert named or body.get('next')
