"""about through the real cli.py and a fake Aside."""
import base64
import json

from tests.sns.facebook.scenes import (GRAPHQL, HOME, known_tab, page_result, queries, query_result, run, state_of)


def section(name, *texts):
    return {'field_section_type': name, 'profile_fields': {'nodes': [{'title': {'text': t}, 'field_type': name}
                                                                      for t in texts]}}


def about_body(sections, collections=None):
    node = {'activeCollections': {'nodes': [{'style_renderer': {'profile_field_sections': sections}}]}}
    if collections is not None:
        node['all_collections'] = {'nodes': [{'name': n, 'id': i} for n, i in collections]}
    return json.dumps({'data': {'user': {'about_app_sections': {'nodes': [node]}}}})


def script(browser, *, numeric=False):
    known_tab(browser)
    if not numeric:
        browser.respond('facebook.page', page_result('https://www.facebook.com/some.person',
                                                     '<script>{"userID":"4"}</script>'))
    browser.respond('facebook.query', query_result(about_body([section('overview', 'Works at Example Co')],
                                                              [('Work', 'COL_W'), ('Places', 'COL_P')])))


def test_overview_then_every_collection(browser):
    script(browser)
    browser.respond('facebook.query', query_result(about_body([section('directory_work', 'Works at Example Co',
                                                                       'Studied at X')])))
    browser.respond('facebook.query', query_result(about_body([section('directory_places', 'Lives in Example City')])))
    code, out, _ = run(browser, 'about', 'some.person')
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == 'facebook about · 4 shown · stopped=exhausted · requests=4'
    assert lines[1:] == ['overview: Works at Example Co', 'directory_work: Works at Example Co',
                         'directory_work: Studied at X', 'directory_places: Lives in Example City']
    variables = [q['args']['variables'] for q in queries(browser)]
    assert [q['collectionToken'] for q in variables] == [None, 'COL_W', 'COL_P']
    assert variables[0]['userID'] == variables[0]['pageID'] == '4'
    assert variables[0]['sectionToken'] == base64.b64encode(b'app_section:4:2327158227').decode()


def test_section_stops_at_the_first_tab_that_shows_it(browser):
    script(browser, numeric=True)
    browser.respond('facebook.query', query_result(about_body([section('directory_work', 'Works at Example Co')])))
    code, out, _ = run(browser, 'about', '4', '--section', 'directory_work', '--json')
    result = json.loads(out)
    assert code == 0 and [f['text'] for f in result['results']] == ['Works at Example Co']
    assert result['request_count'] == 2


def test_a_section_nobody_shows_is_reported_not_invented(browser):
    script(browser, numeric=True)
    browser.respond('facebook.query', query_result(about_body([])))
    browser.respond('facebook.query', query_result(about_body([])))
    code, out, _ = run(browser, 'about', '4', '--section', 'directory_school', '--json')
    result = json.loads(out)
    assert code == 7 and "not in this profile's visible About" in ' '.join(result['coverage'])


def test_a_failed_collection_is_named_and_the_rest_kept(browser):
    script(browser, numeric=True)
    browser.respond('facebook.query', {'status': 500, 'url': GRAPHQL, 'body': 'x', 'used': {'source': 'live'},
                                       'explicit': 1, 'resources': 1, 'statuses': [500], 'unwatched': [],
                                       'limited': False})
    browser.respond('facebook.query', query_result(about_body([section('directory_places', 'Lives in Example City')])))
    code, out, _ = run(browser, 'about', '4', '--json')
    result = json.loads(out)
    assert code == 8 and result['error'] == 'partial'
    assert [f['text'] for f in result['results']] == ['Works at Example Co', 'Lives in Example City']
    assert result['failed_sections'][0]['collection'] == 'Work' and result['failed_sections'][0]['kind'] == 'failed'
    assert 'collection Work failed' in ' '.join(result['coverage'])


def test_a_block_met_on_a_collection_stops_the_remaining_ones(browser):
    script(browser, numeric=True)
    browser.respond('facebook.query', query_result(json.dumps({'checkpoint_url': 'https://www.facebook.com/checkpoint/1/'})))
    code, out, _ = run(browser, 'about', '4', '--json')
    result = json.loads(out)
    assert code == 5 and len(queries(browser)) == 2  # the overview and the one that met the checkpoint; no third
    assert state_of()['person']['reason'] == 'checkpoint'
    assert [f['collection'] for f in result['failed_sections']] == ['Work']  # the next tab was not even tried


def test_a_numeric_profiles_about_screen_is_the_query_form(browser):
    """Appendix C: the screen a refused About query is relearned from was profile.php?id=N/about, which is no screen."""
    known_tab(browser)
    rejected = json.dumps({'errors': [{'message': 'PersistedQueryNotFound', 'code': 1675002}]})
    browser.respond('facebook.query', query_result(rejected, source='stored', doc_id='9'))
    browser.respond('facebook.route', {'location': HOME, 'user_id': '1000123', 'explicit': 0, 'resources': 1,
                                       'statuses': [200], 'unwatched': [], 'limited': False,
                                       'live': {'ProfileCometAboutAppSectionQuery': {'doc_id': '8', 'flags': {}}}})
    browser.respond('facebook.query', query_result(about_body([section('overview', 'Works at Example Co')])))
    code, out, _ = run(browser, 'about', '1000123', '--section', 'overview')
    [route] = [c for c in browser.calls() if c['op'] == 'facebook.route']
    assert code == 0 and route['args']['path'] == '/profile.php?id=1000123&sk=about'


def group_header(group_id='700'):
    return json.dumps({'data': {'group': {'id': group_id, 'profile_header_renderer': {'group': {
        '__typename': 'Group', 'id': group_id, 'name': 'Example Group',
        'url': 'https://www.facebook.com/groups/examplegroup/', 'group_address': 'examplegroup',
        'privacy_info': {'icon_name': 'globe-americas', 'title': {'text': 'Public group'}},
        'group_member_profiles': {'formatted_count_text': '90K members'}, 'viewer_join_state': 'CAN_JOIN',
        'has_membership_questions': False}}}}})


def group_about_body(group_id='700'):
    return json.dumps({'data': {'group': {'id': group_id, 'about_feed_units': [
        {'__typename': 'GroupsAboutFeedAboutCardUnit',
         'group': {'id': group_id, 'description_with_entities': {'text': 'All about examples.'}}},
        {'__typename': 'GroupsAboutFeedActivityCardUnit',
         'group': {'id': group_id, 'number_of_posts_in_last_day': 3, 'number_of_posts_in_last_month': 90,
                   'created_time': 1767225600, 'group_total_members_info_text': '90,355 total members'}},
        {'__typename': 'GroupsAboutFeedRulesCardUnit', 'group': {'id': group_id, 'group_rules': {'nodes': [
            {'id': 'r1', 'rule_title': 'Be kind', 'description': 'No insults.'}]}}}]}}})


def script_group(browser, group_id='700'):
    browser.respond('facebook.query', query_result(group_header(group_id)), name='CometGroupRootQuery')
    browser.respond('facebook.query', query_result(group_about_body(group_id)), name='CometGroupAboutRootQuery')


def test_a_group_url_gets_the_group_card(browser):
    known_tab(browser)
    browser.respond('facebook.page', page_result('https://www.facebook.com/groups/examplegroup/',
                                                 '<script>{"groupID":"700"}</script>'))
    script_group(browser)
    code, out, _ = run(browser, 'about', 'https://www.facebook.com/groups/examplegroup/')
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == 'facebook about · 1 shown · stopped=exhausted · requests=3'
    assert lines[1] == ('[e1] group id=700 · Example Group · Public group · 90,355 total members · you: CAN_JOIN · '
                        'url: "https://www.facebook.com/groups/examplegroup/"')
    assert lines[2] == '     description: "All about examples."'
    assert lines[3] == '     activity: 3 posts in the last day · 90 in the last month · created 2026-01-01'
    assert lines[4] == '     rule 1: "Be kind" — "No insults."'
    names = [q['args'] for q in queries(browser)]
    assert [a['name'] for a in names] == ['CometGroupRootQuery', 'CometGroupAboutRootQuery']
    assert names[0]['variables']['groupID'] == names[1]['variables']['groupID'] == '700'


def test_a_numeric_group_id_needs_the_groups_url_form(browser):
    known_tab(browser)
    script_group(browser, '701')
    code, out, _ = run(browser, 'about', 'https://www.facebook.com/groups/701/', '--json')
    result = json.loads(out)
    assert code == 0 and result['results'][0]['id'] == '701' and result['request_count'] == 2
    assert result['results'][0]['rules'] == [{'title': 'Be kind', 'description': 'No insults.'}]


def test_a_group_has_one_card_and_no_sections(browser):
    code, out, _ = run(browser, 'about', 'https://www.facebook.com/groups/701/', '--section', 'overview')
    assert code == 2 and browser.calls() == []
