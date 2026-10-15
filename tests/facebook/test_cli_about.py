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
