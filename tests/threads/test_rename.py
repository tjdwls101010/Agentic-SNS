"""refresh adopts a renamed route query only when the route itself proves it, and says so; anything less is reported."""
import ast
import json
import os
from pathlib import Path

import pytest

from .fixtures.builders import ERRORS, envelope, listed_post, tab
from .helpers import SKILL, calls, data, run_cli

OLD = 'BarcelonaProfileThreadsTabDirectQuery'
NEW = 'BarcelonaProfileThreadsTabRenamedQuery'
PAGE = 'BarcelonaProfilePageDirectQuery'


def home():
    return Path(os.environ['THREADS_HOME'])


TAB_VARIABLES = '"variables": {"allow_page_info_for_lox_user": false, "first": 4, "userID": "42"}'
PAGE_VARIABLES = '"variables": {"canSeeFeedsTab": true, "showLinkedIGStats": false, "userID": "42"}'


def rename(routes, old=OLD, new=NEW, variables=None, current=TAB_VARIABLES):
    """Threads now renders a preloader under a new name (and maybe new variables) on every profile route."""
    def change(html):
        html = html.replace(f'adp_{old}RelayPreloader', f'adp_{new}RelayPreloader')
        if variables is not None:
            html = html.replace(current, '"variables": ' + json.dumps(variables))
        return html
    routes.edit('/@fixture_user', change)
    return routes.copy('/@fixture_user', '/@fixture_viewer')


def replay(routes, name=NEW, posts=None):
    routes.set(name, envelope(tab(posts if posts is not None else [listed_post(1), listed_post(2)])))
    return routes


def override():
    path = home() / 'registry.json'
    return json.loads(path.read_text()) if path.exists() else None


def test_a_renamed_route_query_is_adopted_after_replay_and_the_read_works_again(routes):
    rename(routes)
    replay(routes).write()
    before = run_cli('user', '@fixture_user', '--limit', '6', '--json')
    assert data(before)['error'] == 'operation_rotated'
    body = data(run_cli('refresh'))
    assert body['renamed'] == {'profile.threads': {'from': OLD, 'to': NEW}}
    assert override()['operations']['profile.threads']['name'] == NEW
    routes.set(NEW + ':after', envelope(tab([listed_post(5), listed_post(6)]))).write()
    after = run_cli('user', '@fixture_user', '--limit', '6', '--json')
    assert after.returncode == 0, after.stdout + after.stderr
    assert calls(routes.path.parent / 'requests.ndjson')[-1]['name'] == NEW


@pytest.mark.parametrize('case,reason', [('two-candidates', 'does not prove a rename'),
                                         ('extra-variable', 'does not prove a rename'),
                                         ('unmatched-page', 'does not prove a rename'),
                                         ('bad-shape', 'shape_changed'), ('wrong-author', 'role_mismatch'),
                                         ('mutation', 'arguments')])
def test_a_rename_the_route_does_not_prove_is_reported_and_nothing_is_saved(routes, case, reason):
    if case == 'two-candidates':
        rename(routes)
        routes.edit('/@fixture_viewer', lambda html: html.replace(
            '"items": [', '"items": [{"preloaderID": "adp_BarcelonaProfileThreadsTabOtherQueryRelayPreloader_hash", '
                          '"queryID": "1002", ' + TAB_VARIABLES + '}, '))
    elif case == 'extra-variable':
        rename(routes, variables={'userID': '42', 'first': 4, 'allow_page_info_for_lox_user': False, 'somethingNew': 1})
    elif case == 'unmatched-page':
        rename(routes)
        rename(routes, old=PAGE, new='BarcelonaProfileHeaderQuery', variables={'viewer': True}, current=PAGE_VARIABLES)
    elif case == 'bad-shape':
        rename(routes)
        routes.set(NEW, envelope({'data': {'somethingElse': {}}}))
    elif case == 'wrong-author':
        rename(routes)
        stranger = listed_post(1, user={'pk': '77', 'username': 'fixture_stranger'})
        replay(routes, posts=[stranger])
    elif case == 'mutation':
        rename(routes, new='BarcelonaProfileThreadsTabMutationQuery')
        replay(routes, name='BarcelonaProfileThreadsTabMutationQuery')
    if case not in ('bad-shape', 'wrong-author', 'mutation'):
        replay(routes)
    routes.write()
    body = data(run_cli('refresh'))
    assert body['renamed'] == {}
    assert reason in body['failed'][OLD]
    saved = override()
    assert saved is None or saved['operations'].get('profile.threads', {}).get('name', OLD) == OLD
    if case == 'mutation':
        assert not [c for c in calls(routes.path.parent / 'requests.ndjson') if 'Mutation' in (c['name'] or '')]


def test_a_checkpoint_during_a_provisional_replay_stops_everything(routes):
    rename(routes)
    routes.set(NEW, ERRORS['checkpoint']).write()
    result = run_cli('refresh')
    assert result.returncode == 5
    log = routes.path.parent / 'requests.ndjson'
    assert calls(log)[-1]['name'] == NEW
    count = len(calls(log))
    assert run_cli('home', '--json').returncode == 5 and len(calls(log)) == count
    assert override() is None


def test_only_refresh_can_send_a_name_the_registry_does_not_hold():
    senders = []
    for path in (SKILL / 'scripts').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and any(k.arg == 'provisional' for k in node.keywords):
                senders.append(path.relative_to(SKILL / 'scripts').as_posix())
    assert set(senders) == {'threads/graphql/refresh.py'}


def test_an_app_only_query_that_was_not_seen_may_have_been_renamed(routes):
    routes.set('capture', envelope(json.dumps({'queries': [], 'missing': [], 'envelopes': [], 'request_count': 2,
                                                'count_complete': True, 'failed': None, 'attempts': []}),
                                    url='https://www.threads.com/@fixture_user/post/FIX_2')).write()
    body = data(run_cli('refresh', '--capture', '--post', 'https://www.threads.com/@fixture_user/post/FIX_2'))
    assert 'may be renamed' in body['failed']['BarcelonaFriendshipsFollowersTabQuery']
    assert 'needs an update' in body['failed']['BarcelonaFriendshipsFollowersTabQuery']


def test_a_capture_whose_tab_did_not_close_keeps_its_cleanup_marker(routes):
    routes.set('capture', envelope(json.dumps({'queries': [], 'missing': [], 'envelopes': [], 'request_count': 2,
                                                'count_complete': True, 'failed': 'capture_cleanup_failed',
                                                'attempts': []}),
                                    url='https://www.threads.com/@fixture_user/post/FIX_2')).write()
    body = data(run_cli('refresh', '--capture', '--post', 'https://www.threads.com/@fixture_user/post/FIX_2'))
    assert body['capture']['cleanup_confirmed'] is False
    assert data(run_cli('doctor'))['capture_cleanup_uncertain'] is True
