"""refresh through the CLI: discover on the app's own routes, verify by replay, keep what cannot be verified."""
import json
import os
from pathlib import Path

from .fixtures.builders import envelope, person, users
from .helpers import POST, calls, data, run_cli

CAPTURE = ['refresh', '--capture', '--post', POST]


def home():
    return Path(os.environ['THREADS_HOME'])


def viewer_profile(routes):
    """The viewer's own profile route, which refresh visits first."""
    return routes.copy('/@fixture_user', '/@fixture_viewer')


def test_refresh_keeps_unobserved_operations_and_never_saves_instance_variables(routes):
    viewer_profile(routes).write()
    result = run_cli('refresh')
    assert result.returncode == 8, result.stdout + result.stderr
    body = data(result)
    assert 'BarcelonaProfileThreadsTabDirectQuery' in body['updated']
    assert 'BarcelonaSavedPageViewerQuery' in body['missing']
    assert 'BarcelonaFeedDirectQuery' not in body['missing']  # feeds are read as rendered, never queried
    saved = json.loads((home() / 'registry.json').read_text())
    assert 'synthetic-csrf' not in json.dumps(saved)
    threads_tab, = [e for e in saved['operations'].values() if e['name'] == 'BarcelonaProfileThreadsTabDirectQuery']
    # The preloader's own variables (this profile's userID) are an instance, not the operation: only id and flags stay.
    assert threads_tab['doc_id'] == '1001' and '42' not in json.dumps(threads_tab)


def test_a_preloader_missing_a_required_variable_is_reported_never_sent_incomplete(routes):
    viewer_profile(routes)
    routes.edit('/@fixture_viewer', lambda html: html.replace(
        '"variables": {"allow_page_info_for_lox_user": false, "first": 4, "userID": "42"}',
        '"variables": {"allow_page_info_for_lox_user": false, "first": 4}')).write()
    body = data(run_cli('refresh'))
    assert body['missing']['BarcelonaProfileThreadsTabDirectQuery'] == 'arguments'
    assert not [c for c in calls(routes.path.parent / 'requests.ndjson')
                if c['name'] == 'BarcelonaProfileThreadsTabDirectQuery']


def test_refresh_only_checks_that_a_post_route_still_decodes(routes):
    viewer_profile(routes).write()
    body = data(run_cli('refresh', '--post', POST))
    assert body['post_route'] == 'decoded'
    assert 'post_route' not in body['failed']
    assert not [name for name in [*body['missing'], *body['updated']] if name.startswith('BarcelonaPostPage')]
    routes.edit('/@fixture_user/post/FIX_2', lambda html: html.replace('direct_replies', 'x')).write()
    result = run_cli('refresh', '--post', POST)
    assert result.returncode == 8
    assert data(result)['post_route'] == 'failed'


def test_capture_requires_its_seed_before_spending_a_request(fake_aside):
    result = run_cli('refresh', '--capture')
    assert result.returncode == 2
    assert calls(fake_aside) == []


def observed(queries, count=3, failed=None, envelopes=()):
    return envelope(json.dumps({'queries': queries, 'missing': [], 'envelopes': list(envelopes), 'request_count': count,
                                'count_complete': True, 'failed': failed, 'attempts': []}), url=POST)


def test_a_captured_query_is_replayed_before_it_is_saved(routes):
    query = {'name': 'BarcelonaFriendshipsFollowersTabQuery', 'doc_id': '3001',
             'variables': {'userID': '42', 'first': 20, '__relay_internal__pv__Examplerelayprovider': True}}
    routes.set('capture', observed([query]))
    routes.set('BarcelonaFriendshipsFollowersTabQuery',
               envelope(users('followers', [person(50)], cursor=False, counts={'followers': 1})))
    routes.write()
    result = run_cli(*CAPTURE)
    body = data(result)
    assert body['updated'] == ['BarcelonaFriendshipsFollowersTabQuery']
    assert body['capture']['cleanup_confirmed'] is True
    replay = calls(routes.path.parent / 'requests.ndjson')[-1]
    assert (replay['doc_id'], replay['variables']['__relay_internal__pv__Examplerelayprovider']) == ('3001', True)
    assert run_cli('graph', '@fixture_user', 'followers', '--json').returncode == 0
    assert calls(routes.path.parent / 'requests.ndjson')[-1]['doc_id'] == '3001'
    assert data(run_cli('doctor'))['capture_cleanup_uncertain'] is False


def test_a_lost_capture_keeps_its_reservation_and_cleanup_marker(routes):
    routes.set('capture', {'mode': 'fail'}).write()
    assert run_cli(*CAPTURE).returncode == 3
    doctor = data(run_cli('doctor'))
    assert doctor['capture_cleanup_uncertain'] is True
    # The route, the doctor probe, and every request the tab might have made.
    assert doctor['budget']['window_used'] > 3


def test_a_block_seen_during_capture_is_persisted_before_any_candidate_is_used(routes):
    blocked = {'status': 429, 'url': 'https://www.threads.com/checkpoint/', 'body': '{"error_code":"368"}'}
    routes.set('capture', dict(observed([], failed='capture_blocked', envelopes=[blocked]), status=429,
                               url='https://www.threads.com/checkpoint/')).write()
    assert run_cli(*CAPTURE).returncode == 5
    assert run_cli('home', '--json').returncode == 5
    assert data(run_cli('home', '--json'))['error'] == 'checkpoint'


def legacy_override():
    home().mkdir(parents=True, exist_ok=True)
    legacy = Path(__file__).with_name('fixtures') / 'legacy' / 'registry.json'
    (home() / 'registry.json').write_text(legacy.read_text())
    return json.loads(legacy.read_text())


def test_refresh_rewrites_an_old_override_in_the_current_format(routes):
    old = legacy_override()
    viewer_profile(routes).write()
    run_cli('refresh')
    saved = json.loads((home() / 'registry.json').read_text())
    assert saved['version'] == 2
    names = {entry['name'] for entry in saved['operations'].values()}
    # Every entry the old file verified survives except the retired post-page queries, now read from the page itself.
    retired = {'BarcelonaFeedDirectQuery'}  # read as rendered now, like the post page
    assert names == {name for name in old['operations'] if 'PostPage' not in name and name not in retired}
    assert not set(saved['operations']) & set(old['operations'])
    for entry in saved['operations'].values():
        assert set(entry) == {'name', 'doc_id', 'flags', 'captured_at'}
    tab = next(e for e in saved['operations'].values() if e['name'] == 'BarcelonaProfileRepliesTabDirectQuery')
    assert tab['doc_id'] == old['operations']['BarcelonaProfileRepliesTabDirectQuery']['doc_id']


def test_an_override_naming_an_operation_this_skill_does_not_know_is_refused(fake_aside):
    old = legacy_override()
    old['operations']['BarcelonaSomethingNewQuery'] = dict(old['operations']['BarcelonaFeedDirectQuery'])
    (home() / 'registry.json').write_text(json.dumps(old))
    result = run_cli('home', '--json')
    assert result.returncode == 6
    assert 'registry.json' in data(result)['fix'] and 'Remove' in data(result)['fix']
    assert calls(fake_aside) == []


def test_an_old_override_entry_naming_only_a_new_doc_id_keeps_the_bundled_flags(fake_aside):
    home().mkdir(parents=True, exist_ok=True)
    (home() / 'registry.json').write_text(json.dumps(
        {'operations': {'BarcelonaProfileThreadsTabDirectQuery': {'verified': True, 'doc_id': '4242'}}}))
    result = run_cli('user', '@fixture_user', '--limit', '6', '--json')
    assert result.returncode == 0, result.stdout + result.stderr
    sent = calls(fake_aside)[-1]
    assert sent['doc_id'] == '4242'
    assert any(key.startswith('__relay_internal__') for key in sent['variables'])
