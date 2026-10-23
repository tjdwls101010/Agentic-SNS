"""profile and group through the real cli.py and a fake Aside: id resolution, the server-filtered window of a profile,
the order of a group, and how one date-window unit treats pinned and undated posts."""
import json

from tests.sns.facebook.data import fixture
from tests.sns.facebook.scenes import (graphql_body, known_tab, look, page_result, queries, query_result,
                                       rerun, run, story)

TIMELINE = ['node', 'timeline_list_feed_units']
GROUP = ['node', 'group_feed']
SCENARIOS = {s['name']: s for s in fixture('paging.json')['scenarios']}
WINDOWS = {c['tz']: c for c in fixture('requests.json')['profile_window']['cases']}


def serve(browser, path, scenario):
    for served in scenario['pages']:
        stories = [story(r['id'], r.get('created_at'), pinned=r.get('pinned')) for r in served['records']]
        info = served['page_info']
        browser.respond('facebook.query', query_result(graphql_body(path, stories, info['has_next_page'],
                                                                    info['end_cursor'])))


def test_profile_window_is_server_filtered_and_closes_at_the_end(browser):
    scenario = SCENARIOS['server-filtered-window-closes-at-end']
    known_tab(browser)
    browser.respond('facebook.page', page_result('https://www.facebook.com/some.person',
                                                 '<script>{"userID":"1000777"}</script>'))
    serve(browser, TIMELINE, scenario)
    code, out, _ = run(browser, 'profile', 'some.person', '--since', '2026-09-01', '--until', '2026-09-30', '--json',
                       env={'TZ': 'Asia/Seoul'})
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == scenario['expected']['shown']
    assert result['window']['coverage'] == 'closed (server-filtered)' and result['stop_reason'] == 'exhausted'
    sent = queries(browser)[0]['args']
    assert sent['name'] == 'ProfileCometTimelineFeedRefetchQuery' and sent['variables']['id'] == '1000777'
    assert sent['variables']['afterTime'] == WINDOWS['Asia/Seoul']['afterTime']
    assert sent['variables']['beforeTime'] == WINDOWS['Asia/Seoul']['beforeTime']
    assert result['request_count'] == 2


def test_the_days_of_a_window_are_the_local_days(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(graphql_body(TIMELINE, [story('A', '2026-09-20T00:00:00Z')], False)))
    run(browser, 'profile', '1000777', '--since', '2026-09-01', '--until', '2026-09-30', env={'TZ': 'UTC'})
    sent = queries(browser)[0]['args']['variables']
    assert (sent['afterTime'], sent['beforeTime']) == (WINDOWS['UTC']['afterTime'], WINDOWS['UTC']['beforeTime'])


def test_without_a_limit_a_profile_reads_one_page(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(graphql_body(TIMELINE, [story('A'), story('B')], True, 'T1')))
    code, out, _ = run(browser, 'profile', '1000777')
    assert code == 0 and len(queries(browser)) == 1
    assert out.splitlines()[0] == 'facebook profile · 2 shown · stopped=limit_reached · requests=1'
    assert out.splitlines()[-1].startswith('more: ')


def test_numeric_profile_needs_no_page_and_continuation_keeps_the_id(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result(graphql_body(TIMELINE, [story('A'), story('B')], True, 'T1')))
    code, out, _ = run(browser, 'profile', '1000777', '--limit', '1')
    assert code == 0 and 'requests=1' in out.splitlines()[0]
    assert not [c for c in browser.calls() if c['op'] == 'facebook.page']
    look(browser).respond('facebook.query', query_result(graphql_body(TIMELINE, [story('C')], False)))
    code, out, _ = rerun(browser, out.splitlines()[-1], '--limit', '5')
    assert code == 0, out
    assert 'Author B' in out and 'Author C' in out
    assert [c['args']['variables']['id'] for c in queries(browser)] == ['1000777', '1000777']


def test_reserved_paths_are_not_profiles(browser):
    code, out, _ = run(browser, 'profile', 'https://www.facebook.com/groups/abc')
    assert code == 2 and browser.calls() == []


def test_group_recent_until_filters_without_closing(browser):
    scenario = SCENARIOS['until-filters-without-closing']
    known_tab(browser)
    serve(browser, GROUP, scenario)
    code, out, _ = run(browser, 'group', '1000000000000001', '--sort', 'recent', '--until', '2026-09-10', '--limit', '2',
                       '--json')
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == scenario['expected']['shown']
    assert result['window']['coverage'] == 'open — more: continues' and 'next' in result
    sent = queries(browser)[0]['args']
    assert sent['name'] == 'GroupsCometFeedRegularStoriesPaginationQuery'
    assert sent['variables']['sortingSetting'] == 'CHRONOLOGICAL' and sent['variables']['id'] == '1000000000000001'


def test_group_ranked_window_is_a_sample(browser):
    scenario = SCENARIOS['ranked-window-is-a-sample']
    known_tab(browser)
    browser.respond('facebook.page', page_result('https://www.facebook.com/groups/example.group/',
                                                 '<script>{"groupID":"555000"}</script>'))
    serve(browser, GROUP, scenario)
    code, out, _ = run(browser, 'group', 'https://www.facebook.com/groups/example.group/', '--sort', 'activity',
                       '--since', '2026-09-10', '--limit', '3', '--json')
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == scenario['expected']['shown']
    assert result['window']['coverage'] == 'sample (not in date order)'
    assert queries(browser)[0]['args']['variables']['sortingSetting'] == 'RECENT_ACTIVITY'


def test_a_group_read_to_its_oldest_post_covers_the_window(browser):
    """A group's chronological end is its oldest post (unlike the feed's depth cut-off)."""
    known_tab(browser)
    browser.respond('facebook.query', query_result(graphql_body(GROUP, [story('G1', '2026-09-12T00:00:00Z')], False)))
    code, out, _ = run(browser, 'group', '1000000000000001', '--sort', 'recent', '--since', '2026-09-01', '--json')
    result = json.loads(out)
    assert code == 0 and result['window']['coverage'] == 'closed (read to the end)'


def test_a_pinned_post_is_judged_by_its_date_and_never_closes_the_window(browser):
    """Intended change (one window unit for every list): a pinned post older than --since is left out like any other
    old post, and it does not end the read."""
    known_tab(browser)
    browser.respond('facebook.query', query_result(graphql_body(GROUP, [
        story('PIN', '2025-01-01T00:00:00Z', pinned=True), story('G1', '2026-09-12T00:00:00Z'),
        story('G2', '2026-09-11T00:00:00Z')], True, 'C1')))
    browser.respond('facebook.query', query_result(graphql_body(GROUP, [story('G3', '2026-08-01T00:00:00Z')], True, 'C2')))
    code, out, _ = run(browser, 'group', '1000000000000001', '--sort', 'recent', '--since', '2026-09-01', '--json')
    result = json.loads(out)
    assert [r['id'] for r in result['results']] == ['G1', 'G2'] and result['stop_reason'] == 'window_reached'
    assert len(queries(browser)) == 2


def test_a_post_without_a_date_cannot_be_placed_in_a_window_and_is_counted(browser):
    """Intended change: undated posts used to pass every window; the shared unit leaves them out and says so."""
    known_tab(browser)
    browser.respond('facebook.query', query_result(graphql_body(GROUP, [
        story('G1', '2026-09-12T00:00:00Z'), story('NODATE', None)], False)))
    code, out, _ = run(browser, 'group', '1000000000000001', '--sort', 'recent', '--since', '2026-09-01', '--json')
    result = json.loads(out)
    assert [r['id'] for r in result['results']] == ['G1']
    assert '1 undated record left out: no date places it in the window' in result['coverage']


def test_unresolvable_group_is_a_read_failure(browser):
    known_tab(browser)
    browser.respond('facebook.page', page_result('https://www.facebook.com/groups/nope/', '<html></html>'))
    code, out, _ = run(browser, 'group', 'nope')
    assert code == 6 and json.loads(out)['error'] == 'failed'


def test_a_page_facebook_says_is_not_there_is_exit_9_and_leaves_no_handle(browser):
    """A 404 for the page of a named profile: the target cannot be read by this account, so nothing is left to
    continue from (appendix C: the old (4, 5) left handles behind deleted targets)."""
    known_tab(browser)
    browser.respond('facebook.page', page_result('https://www.facebook.com/no.such', 'Not found', status=404))
    code, out, _ = run(browser, 'profile', 'no.such')
    result = json.loads(out)
    assert code == 9 and result['error'] == 'unavailable' and 'next' not in result
