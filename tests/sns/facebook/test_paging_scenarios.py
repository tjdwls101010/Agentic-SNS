"""The pagination and date-window scenarios of fixtures/paging.json, run through the real CLI against the scripted Aside:
each scenario serves its pages in order as Facebook answers and the shown ids, the stop, the pages fetched, what a
continuation keeps, the window's coverage and the exit code are compared.

Surface per scenario: a newest-first window reads `feed --sort recent`, a ranked order `feed`, a server-filtered window
`profile <numeric id>`. Intended changes against the abstract file (S2 and the shared window unit):
- nothing reads on by itself except a window a newest-first surface can close or a server-filtered one; every scenario
  that expects a read to the end passes --limit 1000 (the file's `limit: null` means "to the natural end");
- a pinned post is judged by its date and an undated one is left out and counted, instead of passing every window;
- advertisements are left out before the page reaches the reader, so a continuation counts the ones it meets again;
- the budget stop of the file's stop_priority does not exist; the order of the stops that remain is the last test.
"""
import json
import re

import pytest

from tests.sns.facebook.data import fixture
from tests.sns.facebook.scenes import (ACCOUNT, GRAPHQL, graphql_body, known_tab, look, queries, query_result, run,
                                       story)

SCENARIOS = {s['name']: s for s in fixture('paging.json')['scenarios']}
FEED = ['viewer', 'news_feed']
TIMELINE = ['node', 'timeline_list_feed_units']
PATH = {'newest_first': FEED, 'ranked': FEED, 'server': TIMELINE}
# what changed against the file's expectation: scenario → the new `expected` keys
CHANGED = {
    'newest-first-window-closes-at-boundary-page': {'shown': ['P1', 'P4'], 'undated_left_out': 1},
    'sponsored-skipped-once': {'then_sponsored_skipped': 1},
}


def served(page, order):
    if page.get('error'):
        return {'status': 500, 'url': GRAPHQL, 'body': 'oops', 'used': {'source': 'live'}, 'explicit': 1,
                'resources': 1, 'statuses': [500], 'unwatched': [], 'limited': False, 'user_id': ACCOUNT}
    if page.get('empty'):
        return query_result(graphql_body(PATH[order], [], False, None))
    info = page.get('page_info') or {'has_next_page': False, 'end_cursor': None}
    if page.get('has_items') and not page['records']:
        body = json.dumps({'data': {'viewer': {'news_feed': {'edges': [{'node': {'something': 'else'}}],
                                                             'page_info': info}}}})
        return query_result(body)
    stories = [story(r['id'], r.get('created_at'), sponsored=r.get('sponsored'), pinned=r.get('pinned'))
               for r in page['records']]
    return query_result(graphql_body(PATH[order], stories, info['has_next_page'], info['end_cursor']))


def arguments(options, limit=...):
    order = options['order']
    args = ['profile', '1000777'] if order == 'server' else ['feed'] + (['--sort', 'recent'] if order == 'newest_first'
                                                                         else [])
    if order != 'server' and not options['skip_sponsored']:
        args.append('--include-sponsored')
    for key in ('since', 'until'):
        if options[key]:
            args += ['--' + key, options[key]]
    limit = options['limit'] if limit is ... else limit
    reads_to_the_end = limit is None and not (options['since'] and order == 'newest_first') and order != 'server'
    args += ['--limit', str(1000 if reads_to_the_end else limit)] if limit is not None or reads_to_the_end else []
    return args


def run_scenario(browser, scenario):
    options = scenario['options']
    known_tab(browser)
    for page in scenario['pages']:
        browser.respond('facebook.query', served(page, options['order']))
    code, out, _ = run(browser, *arguments(options), '--json', env={'TZ': options['tz']})
    return code, json.loads(out)


def ids(result):
    return [r['id'] for r in result['results']]


@pytest.mark.parametrize('name', [n for n, s in SCENARIOS.items()
                                  if not s['expected'].get('failure') and s['expected'].get('result') not in ('empty',)
                                  and not s['expected'].get('result') == 'partial'])
def test_the_scenario_reads_what_it_says(browser, name):
    scenario = SCENARIOS[name]
    expected = {**scenario['expected'], **CHANGED.get(name, {})}
    code, result = run_scenario(browser, scenario)
    assert code == 0, result
    assert ids(result) == expected['shown']
    assert result['stop_reason'] == expected['stop_reason']
    assert len(queries(browser)) == expected['pages_fetched']
    if 'coverage' in expected:
        expected_label = expected['coverage'].replace('sample (ranked order)', 'sample (not in date order)')
        assert result['window']['coverage'] == expected_label
    assert ('next' in result) is expected['continues']
    if expected.get('undated_left_out'):
        assert f'{expected["undated_left_out"]} undated record left out: no date places it in the window' \
            in result['coverage']
    if expected.get('sponsored_skipped'):
        assert f'{expected["sponsored_skipped"]} sponsored posts (ads) left out' in result['coverage']


@pytest.mark.parametrize('name', [n for n, s in SCENARIOS.items() if 'then' in s])
def test_the_continuation_shows_the_kept_tail_first_and_asks_for_no_page_it_has_not_got_to(browser, name):
    scenario = SCENARIOS[name]
    code, first = run_scenario(browser, scenario)
    then = scenario['then']
    options = scenario['options']
    look(browser)
    for page in then['pages']:
        browser.respond('facebook.query', served(page, options['order']))
    queried = len(queries(browser))
    number = re.search(r'--after (\d+)', first['next']).group(1)
    args = arguments(options, limit=then['continue_with']['limit'])
    code, out, _ = run(browser, *args, '--after', number, '--json', env={'TZ': options['tz']})
    result = json.loads(out)
    expected = {**then['expected'], **CHANGED.get(name, {})}
    assert ids(result) == expected['shown'] and result['stop_reason'] == expected['stop_reason']
    assert len(queries(browser)) - queried == expected['pages_fetched']
    assert ('next' in result) is expected['continues']
    if 'then_sponsored_skipped' in expected:
        assert f'{expected["then_sponsored_skipped"]} sponsored posts (ads) left out' in result['coverage']


def test_an_explicitly_empty_first_page_is_an_empty_result(browser):
    scenario = SCENARIOS['explicit-empty-first-page']
    code, result = run_scenario(browser, scenario)
    assert code == 7 and result['error'] == 'empty' and ids(result) == []


def test_a_connection_whose_items_cannot_be_read_is_a_changed_answer(browser):
    scenario = SCENARIOS['readable-zero-from-nonempty-connection']
    code, result = run_scenario(browser, scenario)
    assert code == 6 and result['error'] == 'failed' and result['stop_reason'] == 'query_failure'


@pytest.mark.parametrize('name', ['items-without-page-info', 'repeated-cursor'])
def test_damaged_pagination_keeps_what_was_read_and_ends_the_read(browser, name):
    scenario = SCENARIOS[name]
    code, result = run_scenario(browser, scenario)
    assert code == 8 and result['error'] == 'partial' and ids(result) == scenario['expected']['shown']
    assert len(queries(browser)) == scenario['expected']['pages_fetched']


def test_a_failure_after_earlier_pages_keeps_them_and_the_window_is_open(browser):
    scenario = SCENARIOS['failure-keeps-earlier-records']
    code, result = run_scenario(browser, scenario)
    assert code == 8 and ids(result) == ['A'] and result['window']['coverage'].startswith('open — ')


def test_a_checkpoint_on_the_page_of_a_login_wall_is_the_block(browser):
    """stop_priority of the file, minus the budget that no longer exists: block, then login, then a plain failure."""
    assert fixture('paging.json')['stop_priority']['order'] == ['blocked', 'login', 'failed', 'budget']
    known_tab(browser)
    browser.respond('facebook.query', query_result(json.dumps(
        {'error': 1357001, 'checkpoint_url': 'https://www.facebook.com/checkpoint/1/'})))
    code, out, _ = run(browser, 'feed')
    assert code == 5 and json.loads(out)['error'] == 'blocked'


def test_a_login_wall_outranks_a_failed_status(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result('for (;;);' + json.dumps({'error': 1357001}), status=500))
    code, out, _ = run(browser, 'feed')
    assert code == 4 and json.loads(out)['error'] == 'login'
