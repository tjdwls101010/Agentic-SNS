"""feed through the real cli.py and a fake Aside: output contract, continuation, window, sponsored, failures."""
import json
import re

from conftest import fixture, graphql_body, known_tab, query_result, run_cli, story

FEED = ['viewer', 'news_feed']


def page(stories, has_next=True, cursor='CUR1', **kwargs):
    return query_result(graphql_body(FEED, stories, has_next, cursor), **kwargs)


def test_text_page_contract_and_continuation(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', page([story('A'), story('B'), story('C')], cursor='CUR1'))
    code, out, _ = run_cli(browser, 'feed', '--limit', '2')
    assert code == 0, out
    lines = out.splitlines()
    assert lines[0] == 'feed · sort=top · 2 shown · stopped=limit_reached · requests=1/25'
    assert lines[1].startswith('[p1] Author A · 2026-09-12T03:00+00:00 · status · reactions=? comments=? shares=?')
    assert lines[2] == '     text[6 of 6 chars shown, complete]: "post A"'
    assert lines[3] == '     url: "https://www.facebook.com/author.a/posts/A"   author: "https://www.facebook.com/author.a"'
    more = lines[-1]
    assert more.startswith('more: uv run "') and more.endswith('cli.py" feed --sort top --limit 2 --after 1')
    query = [c for c in browser.calls() if c['op'] == 'query'][0]['args']
    assert query['name'] == 'CometNewsFeedPaginationQuery'
    assert query['variables']['orderby'] == ['TOP_STORIES'] and query['variables']['cursor'] is None

    # the continuation shows the unshown tail first, then requests the next page from the saved cursor
    browser.respond('state', {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'runtime': True, 'resources': 0})
    browser.respond('query', page([story('D'), story('E')], has_next=False))
    code, out, _ = run_cli(browser, *more.split('cli.py" ', 1)[1].split())
    assert code == 0, out
    assert out.splitlines()[0] == 'feed · sort=top · 2 shown · stopped=limit_reached · requests=1/25'
    assert [line.split(' ')[1] for line in out.splitlines() if line.startswith('[p')] == ['Author', 'Author']
    assert 'Author C' in out and 'Author D' in out and 'Author E' not in out
    second = [c for c in browser.calls() if c['op'] == 'query'][1]['args']
    assert second['variables']['cursor'] == 'CUR1'


def test_handle_of_another_query_is_refused(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', page([story('A'), story('B')]))
    code, out, _ = run_cli(browser, 'feed', '--limit', '1')
    number = re.search(r'--after (\d+)', out).group(1)
    browser.respond('state', {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'runtime': True, 'resources': 0})
    code, out, _ = run_cli(browser, 'feed', '--sort', 'recent', '--after', number)
    assert code == 2 and json.loads(out)['error'] == 'argument'


def test_newest_first_window_closes_at_the_boundary_page(browser, data_dir):
    scenario = {s['name']: s for s in fixture('paging.json')['scenarios']}['newest-first-window-closes-at-boundary-page']
    known_tab(browser, data_dir)
    for served in scenario['pages']:
        stories = [story(r['id'], r.get('created_at'), sponsored=r.get('sponsored'), pinned=r.get('pinned'))
                   for r in served['records']]
        browser.respond('query', page(stories, served['page_info']['has_next_page'], served['page_info']['end_cursor']))
    code, out, _ = run_cli(browser, 'feed', '--sort', 'recent', '--since', '2026-09-10', '--json',
                           env={'TZ': 'Asia/Seoul'})
    result = json.loads(out)
    expected = scenario['expected']
    assert code == 0
    assert [r['id'] for r in result['results']] == expected['shown']
    assert result['stop_reason'] == 'window_reached' and result['sponsored_skipped'] == 1
    assert result['window'] == {'since': '2026-09-10', 'until': None, 'coverage': 'closed (as served)'}
    assert result['request_count'] == 2 and 'next' not in result


def test_ranked_window_is_reported_as_a_sample(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', page([story('T1', '2026-09-12T00:00:00Z'), story('T2', '2026-09-01T00:00:00Z')]))
    code, out, _ = run_cli(browser, 'feed', '--since', '2026-09-10', '--limit', '1')
    assert code == 0
    assert out.splitlines()[1] == 'window 2026-09-10.. · sample (ranked order)'


def test_sponsored_posts_are_left_out_and_counted_or_kept(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', page([story('AD', sponsored=True), story('A')], has_next=False))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 0 and out.splitlines()[0] == 'feed · sort=top · 1 shown · sponsored_skipped=1 · stopped=exhausted · requests=1/25'
    browser.respond('state', {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'runtime': True, 'resources': 0})
    browser.respond('query', page([story('AD', sponsored=True), story('A')], has_next=False))
    code, out, _ = run_cli(browser, 'feed', '--include-sponsored')
    assert '2 shown' in out.splitlines()[0] and 'sponsored' in out


def test_explicit_empty_feed_is_exit_7(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', page([], has_next=False))
    code, out, _ = run_cli(browser, 'feed')
    result = json.loads(out)
    assert code == 7 and result['error'] == 'empty' and result['stop_reason'] == 'exhausted'


def test_stale_stored_query_is_healed_by_visiting_the_screen_once(browser, data_dir):
    known_tab(browser, data_dir)
    rejected = json.dumps({'errors': [{'message': 'PersistedQueryNotFound', 'code': 1675002}]})
    browser.respond('query', query_result(rejected, source='stored', doc_id='999'))
    browser.respond('route', {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'explicit': 0, 'resources': 4,
                              'live': {'CometNewsFeedPaginationQuery': {'doc_id': '222', 'flags': {'__relay_internal__pv__Arelayprovider': False}}}})
    browser.respond('query', page([story('A')], has_next=False, source='live', doc_id='222'))
    code, out, _ = run_cli(browser, 'feed', '--json')
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == ['A']
    assert result['request_count'] == 1 + 4 + 1
    route = [c for c in browser.calls() if c['op'] == 'route'][0]['args']
    assert route['path'] == '/' and route['names'] == ['CometNewsFeedPaginationQuery']
    learned = json.loads((data_dir / 'session/default.json').read_text())['queries']['CometNewsFeedPaginationQuery']
    assert learned['doc_id'] == '222'
    # the next run sends the learned id as its fallback
    browser.respond('state', {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'runtime': True, 'resources': 0})
    browser.respond('query', page([story('B')], has_next=False))
    run_cli(browser, 'feed')
    assert [c for c in browser.calls() if c['op'] == 'query'][-1]['args']['fallback']['doc_id'] == '222'


def test_a_query_that_stays_rejected_is_exit_6(browser, data_dir):
    known_tab(browser, data_dir)
    rejected = json.dumps({'errors': [{'message': 'noncoercible_variable_value'}]})
    browser.respond('query', query_result(rejected, source='live'))
    code, out, _ = run_cli(browser, 'feed')
    result = json.loads(out)
    assert code == 6 and result['error'] == 'failed' and 'update the skill' in result['fix']
    assert not [c for c in browser.calls() if c['op'] == 'route']


def test_checkpoint_response_blocks_and_stops(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', {'status': 200, 'url': 'https://www.facebook.com/checkpoint/1/', 'body': '<html></html>',
                              'used': {'source': 'live'}, 'explicit': 1, 'resources': 1})
    code, out, _ = run_cli(browser, 'feed')
    assert code == 5 and json.loads(out)['error'] == 'blocked'
    assert 'next' not in json.loads(out)  # no continuation that would invite another request
    assert json.loads((data_dir / 'protection/blocked.json').read_text())['reason'] == 'checkpoint'
    browser.respond('state', {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'runtime': True, 'resources': 0})
    code, out, _ = run_cli(browser, 'feed')
    assert code == 5 and len([c for c in browser.calls() if c['op'] == 'query']) == 1


def test_temporary_rejection_is_retried_once_then_rate_limited(browser, data_dir):
    known_tab(browser, data_dir)
    temporary = 'for (;;);' + json.dumps({'error': 1357054})
    browser.respond('query', query_result(temporary))
    browser.respond('query', page([story('A')], has_next=False))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 0 and 'requests=2/25' in out.splitlines()[0]
    browser.respond('state', {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'runtime': True, 'resources': 0})
    browser.respond('query', query_result(temporary))
    browser.respond('query', query_result(temporary))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 5
    assert json.loads((data_dir / 'protection/blocked.json').read_text())['reason'] == 'rate_limit'


def test_budget_stop_resumes_with_more(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', page([story('A')], cursor='C1'))
    code, out, _ = run_cli(browser, 'feed', '--max-requests', '1')
    assert code == 0
    assert out.splitlines()[0] == 'feed · sort=top · 1 shown · stopped=budget · requests=1/1'
    assert out.splitlines()[-1].endswith('feed --sort top --after 1 --max-requests 1')
