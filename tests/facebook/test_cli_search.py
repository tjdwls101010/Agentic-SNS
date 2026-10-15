"""search through the real cli.py and a fake Aside."""
import json

from conftest import STATE_OK, command_of, known_tab, query_result, run_cli, story


def results_body(edges, has_next=True, cursor='S1'):
    return json.dumps({'data': {'serpResponse': {'results': {
        'edges': edges, 'page_info': {'has_next_page': has_next, 'end_cursor': cursor if has_next else None}}}}})


def person(identity, name='Sample Person', verified=None):
    profile = {'__typename': 'User', 'id': identity, 'name': name, 'url': f'https://www.facebook.com/p.{identity}'}
    if verified is not None:
        profile['is_verified'] = verified
    return {'node': {'role': 'ENTITY_USER', '__typename': 'SearchRenderable'}, 'rendering_strategy': {'view_model': {'profile': profile}}}


def test_people_search_lists_entities_with_their_next_argument(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', query_result(results_body([person('500', verified=True), person('501')])))
    code, out, _ = run_cli(browser, 'search', 'Sample Person', '--type', 'people', '--limit', '2')
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == 'search · type=people · 2 shown · stopped=limit_reached · requests=1/25'
    assert lines[1] == '[e1] person id=500 · Sample Person · verified · url: "https://www.facebook.com/p.500"'
    assert lines[2] == '[e2] person id=501 · Sample Person · verified=? · url: "https://www.facebook.com/p.501"'
    sent = [c for c in browser.calls() if c['op'] == 'query'][0]['args']
    assert sent['name'] == 'SearchCometResultsPaginatedResultsQuery'
    assert sent['variables']['args']['text'] == 'Sample Person'
    assert sent['variables']['args']['experience']['type'] == 'PEOPLE_TAB'
    assert lines[-1].endswith("search 'Sample Person' --type people --limit 2 --after 1")


def test_top_search_mixes_posts_and_entities_in_order(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', query_result(results_body([person('510'), {'node': {**story('SF1'), '__typename': 'Story'}}],
                                                       has_next=False)))
    code, out, _ = run_cli(browser, 'search', 'ai')
    assert code == 0
    assert [line.split(' ')[0] for line in out.splitlines() if line.startswith('[')] == ['[e1]', '[p1]']


def test_search_continues_from_its_cursor(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', query_result(results_body([person('1')], cursor='S1')))
    code, out, _ = run_cli(browser, 'search', 'x', '--type', 'people', '--limit', '1')
    browser.respond('state', STATE_OK)
    browser.respond('query', query_result(results_body([person('2')], has_next=False)))
    code, out, _ = run_cli(browser, *command_of(out.splitlines()[-1]))
    assert code == 0 and 'id=2' in out
    assert [c for c in browser.calls() if c['op'] == 'query'][1]['args']['variables']['cursor'] == 'S1'


def test_option_like_search_text_goes_after_a_double_dash(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', query_result(results_body([person('1')], cursor='S1')))
    code, out, _ = run_cli(browser, 'search', '--type', 'people', '--limit', '1', '--', '-dash')
    assert code == 0 and out.splitlines()[-1].endswith(' -- -dash')


def test_empty_search_text_is_refused(browser, data_dir):
    code, out, _ = run_cli(browser, 'search', '   ')
    assert code == 2 and browser.calls() == []
