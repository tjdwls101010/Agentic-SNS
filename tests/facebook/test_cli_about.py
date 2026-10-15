"""about through the real cli.py and a fake Aside."""
import base64
import json

from conftest import known_tab, query_result, run_cli


def section(name, *texts):
    return {'field_section_type': name, 'profile_fields': {'nodes': [{'title': {'text': t}, 'field_type': name} for t in texts]}}


def about_body(sections, collections=None):
    node = {'activeCollections': {'nodes': [{'style_renderer': {'profile_field_sections': sections}}]}}
    if collections is not None:
        node['all_collections'] = {'nodes': [{'name': n, 'id': i} for n, i in collections]}
    return json.dumps({'data': {'user': {'about_app_sections': {'nodes': [node]}}}})


def script(browser, data_dir, *, numeric=False):
    known_tab(browser, data_dir)
    if not numeric:
        browser.respond('page', {'status': 200, 'url': 'https://www.facebook.com/some.person',
                                 'body': '<script>{"userID":"4"}</script>', 'explicit': 1, 'resources': 1})
    browser.respond('query', query_result(about_body([section('overview', 'Works at Example Co')],
                                                     [('Work', 'COL_W'), ('Places', 'COL_P')])))


def test_overview_then_every_collection(browser, data_dir):
    script(browser, data_dir)
    browser.respond('query', query_result(about_body([section('directory_work', 'Works at Example Co', 'Studied at X')])))
    browser.respond('query', query_result(about_body([section('directory_places', 'Lives in Example City')])))
    code, out, _ = run_cli(browser, 'about', 'some.person')
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == 'about · 4 shown · stopped=exhausted · requests=4/25'
    assert lines[1:] == ['overview: Works at Example Co', 'directory_work: Works at Example Co',
                         'directory_work: Studied at X', 'directory_places: Lives in Example City']
    queries = [c['args']['variables'] for c in browser.calls() if c['op'] == 'query']
    assert [q['collectionToken'] for q in queries] == [None, 'COL_W', 'COL_P']
    assert queries[0]['userID'] == queries[0]['pageID'] == '4'
    assert queries[0]['sectionToken'] == base64.b64encode(b'app_section:4:2327158227').decode()


def test_section_stops_at_the_first_tab_that_shows_it(browser, data_dir):
    script(browser, data_dir, numeric=True)
    browser.respond('query', query_result(about_body([section('directory_work', 'Works at Example Co')])))
    code, out, _ = run_cli(browser, 'about', '4', '--section', 'directory_work', '--json')
    result = json.loads(out)
    assert code == 0 and [f['text'] for f in result['results']] == ['Works at Example Co']
    assert result['request_count'] == 2


def test_a_section_nobody_shows_is_reported_not_invented(browser, data_dir):
    script(browser, data_dir, numeric=True)
    browser.respond('query', query_result(about_body([])))
    browser.respond('query', query_result(about_body([])))
    code, out, _ = run_cli(browser, 'about', '4', '--section', 'directory_school', '--json')
    result = json.loads(out)
    assert code == 7 and "not in this profile's visible About" in ' '.join(result['coverage'])


def test_a_failed_collection_is_named_and_the_rest_kept(browser, data_dir):
    script(browser, data_dir, numeric=True)
    browser.respond('query', {'status': 500, 'url': 'https://www.facebook.com/api/graphql/', 'body': 'x',
                              'used': {'source': 'live'}, 'explicit': 1, 'resources': 1})
    browser.respond('query', query_result(about_body([section('directory_places', 'Lives in Example City')])))
    code, out, _ = run_cli(browser, 'about', '4', '--json')
    result = json.loads(out)
    assert code == 8 and result['error'] == 'partial'
    assert [f['text'] for f in result['results']] == ['Works at Example Co', 'Lives in Example City']
    assert result['failed_sections'][0]['collection'] == 'Work'
    assert 'collection Work failed' in ' '.join(result['coverage'])


def test_budget_names_what_the_profile_needs(browser, data_dir):
    script(browser, data_dir, numeric=True)
    code, out, _ = run_cli(browser, 'about', '4', '--max-requests', '1', '--json')
    result = json.loads(out)
    assert code == 8 and '3 requests' in result['message'] and result['results']


def group_header(group_id='700'):
    return json.dumps({'data': {'group': {'id': group_id, 'profile_header_renderer': {'group': {
        '__typename': 'Group', 'id': group_id, 'name': 'Example Group', 'url': 'https://www.facebook.com/groups/examplegroup/',
        'group_address': 'examplegroup', 'privacy_info': {'icon_name': 'globe-americas', 'title': {'text': 'Public group'}},
        'group_member_profiles': {'formatted_count_text': '90K members'}, 'viewer_join_state': 'CAN_JOIN',
        'has_membership_questions': False}}}}})


def group_about_body(group_id='700'):
    return json.dumps({'data': {'group': {'id': group_id, 'about_feed_units': [
        {'__typename': 'GroupsAboutFeedAboutCardUnit', 'group': {'id': group_id, 'description_with_entities': {'text': 'All about examples.'}}},
        {'__typename': 'GroupsAboutFeedActivityCardUnit', 'group': {'id': group_id, 'number_of_posts_in_last_day': 3,
                                                                    'number_of_posts_in_last_month': 90, 'created_time': 1767225600,
                                                                    'group_total_members_info_text': '90,355 total members'}},
        {'__typename': 'GroupsAboutFeedRulesCardUnit', 'group': {'id': group_id, 'group_rules': {'nodes': [
            {'id': 'r1', 'rule_title': 'Be kind', 'description': 'No insults.'}]}}}]}}})


def script_group(browser, group_id='700'):
    browser.respond('query', query_result(group_header(group_id)), name='CometGroupRootQuery')
    browser.respond('query', query_result(group_about_body(group_id)), name='CometGroupAboutRootQuery')


def test_a_group_url_gets_the_group_card(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('page', {'status': 200, 'url': 'https://www.facebook.com/groups/examplegroup/',
                             'body': '<script>{"groupID":"700"}</script>', 'explicit': 1, 'resources': 1})
    script_group(browser)
    code, out, _ = run_cli(browser, 'about', 'https://www.facebook.com/groups/examplegroup/')
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == 'about · 1 shown · stopped=exhausted · requests=3/25'
    assert lines[1] == ('[e1] group id=700 · Example Group · Public group · 90,355 total members · you: CAN_JOIN · '
                        'url: "https://www.facebook.com/groups/examplegroup/"')
    assert lines[2] == '     description: "All about examples."'
    assert lines[3] == '     activity: 3 posts in the last day · 90 in the last month · created 2026-01-01'
    assert lines[4] == '     rule 1: "Be kind" — "No insults."'
    sent = [c['args'] for c in browser.calls() if c['op'] == 'query']
    assert [a['name'] for a in sent] == ['CometGroupRootQuery', 'CometGroupAboutRootQuery']
    assert sent[0]['variables']['groupID'] == sent[1]['variables']['groupID'] == '700'




def test_a_numeric_group_id_needs_the_groups_url_form(browser, data_dir):
    known_tab(browser, data_dir)
    script_group(browser, '701')
    code, out, _ = run_cli(browser, 'about', 'https://www.facebook.com/groups/701/', '--json')
    result = json.loads(out)
    assert code == 0 and result['results'][0]['id'] == '701' and result['request_count'] == 2
    assert result['results'][0]['rules'] == [{'title': 'Be kind', 'description': 'No insults.'}]
