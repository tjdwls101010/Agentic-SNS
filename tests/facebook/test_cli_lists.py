"""profile and group through the real cli.py and a fake Aside: id resolution, server-filtered and ranked windows."""
import json

from conftest import command_of, STATE_OK, fixture, graphql_body, known_tab, query_result, run_cli, story

TIMELINE = ['node', 'timeline_list_feed_units']
GROUP = ['node', 'group_feed']
SCENARIOS = {s['name']: s for s in fixture('paging.json')['scenarios']}
WINDOWS = {c['tz']: c for c in fixture('requests.json')['profile_window']['cases']}


def serve(browser, path, scenario):
    for served in scenario['pages']:
        stories = [story(r['id'], r.get('created_at'), pinned=r.get('pinned')) for r in served['records']]
        info = served['page_info']
        browser.respond('query', query_result(graphql_body(path, stories, info['has_next_page'], info['end_cursor'])))


def test_profile_window_is_server_filtered_and_closes_at_the_end(browser, data_dir):
    scenario = SCENARIOS['server-filtered-window-closes-at-end']
    known_tab(browser, data_dir)
    browser.respond('page', {'status': 200, 'url': 'https://www.facebook.com/some.person',
                             'body': '<script>{"userID":"1000777"}</script>', 'explicit': 1, 'resources': 1})
    serve(browser, TIMELINE, scenario)
    code, out, _ = run_cli(browser, 'profile', 'some.person', '--since', '2026-09-01', '--until', '2026-09-30', '--json',
                           env={'TZ': 'Asia/Seoul'})
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == scenario['expected']['shown']
    assert result['window']['coverage'] == 'closed (server-filtered)' and result['stop_reason'] == 'exhausted'
    sent = [c for c in browser.calls() if c['op'] == 'query'][0]['args']
    assert sent['name'] == 'ProfileCometTimelineFeedRefetchQuery' and sent['variables']['id'] == '1000777'
    assert sent['variables']['afterTime'] == WINDOWS['Asia/Seoul']['afterTime']
    assert sent['variables']['beforeTime'] == WINDOWS['Asia/Seoul']['beforeTime']
    assert result['request_count'] == 2


def test_numeric_profile_needs_no_page_and_continuation_keeps_the_id(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', query_result(graphql_body(TIMELINE, [story('A'), story('B')], True, 'T1')))
    code, out, _ = run_cli(browser, 'profile', '1000777', '--limit', '1')
    assert code == 0 and 'requests=1/25' in out.splitlines()[0]
    assert not [c for c in browser.calls() if c['op'] == 'page']
    browser.respond('state', STATE_OK)
    browser.respond('query', query_result(graphql_body(TIMELINE, [story('C')], False)))
    code, out, _ = run_cli(browser, *command_of(out.splitlines()[-1]), '--limit', '5')
    assert code == 0, out
    assert 'Author B' in out and 'Author C' in out
    assert [c['args']['variables']['id'] for c in browser.calls() if c['op'] == 'query'] == ['1000777', '1000777']


def test_reserved_paths_are_not_profiles(browser, data_dir):
    code, out, _ = run_cli(browser, 'profile', 'https://www.facebook.com/groups/abc')
    assert code == 2 and browser.calls() == []


def test_group_recent_until_filters_without_closing(browser, data_dir):
    scenario = SCENARIOS['until-filters-without-closing']
    known_tab(browser, data_dir)
    serve(browser, GROUP, scenario)
    code, out, _ = run_cli(browser, 'group', '1000000000000001', '--sort', 'recent', '--until', '2026-09-10',
                           '--limit', '2', '--json')
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == scenario['expected']['shown']
    assert result['window']['coverage'] == 'open — more: continues' and 'next' in result
    sent = [c for c in browser.calls() if c['op'] == 'query'][0]['args']
    assert sent['name'] == 'GroupsCometFeedRegularStoriesPaginationQuery'
    assert sent['variables']['sortingSetting'] == 'CHRONOLOGICAL' and sent['variables']['id'] == '1000000000000001'


def test_group_ranked_window_is_a_sample(browser, data_dir):
    scenario = SCENARIOS['ranked-window-is-a-sample']
    known_tab(browser, data_dir)
    browser.respond('page', {'status': 200, 'url': 'https://www.facebook.com/groups/example.group/',
                             'body': '<script>{"groupID":"555000"}</script>', 'explicit': 1, 'resources': 1})
    serve(browser, GROUP, scenario)
    code, out, _ = run_cli(browser, 'group', 'https://www.facebook.com/groups/example.group/', '--sort', 'activity',
                           '--since', '2026-09-10', '--limit', '3', '--json')
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == scenario['expected']['shown']
    assert result['window']['coverage'] == 'sample (ranked order)'
    assert [c for c in browser.calls() if c['op'] == 'query'][0]['args']['variables']['sortingSetting'] == 'RECENT_ACTIVITY'


def test_unresolvable_group_is_a_read_failure(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('page', {'status': 200, 'url': 'https://www.facebook.com/groups/nope/', 'body': '<html></html>',
                             'explicit': 1, 'resources': 1})
    code, out, _ = run_cli(browser, 'group', 'nope')
    assert code == 6 and json.loads(out)['error'] == 'failed'
