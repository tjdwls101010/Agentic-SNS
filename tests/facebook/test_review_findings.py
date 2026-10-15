"""Reproductions of the independent review of the shared contracts (P3), kept as regression tests."""
import json

from conftest import STATE_OK, graphql_body, known_tab, query_result, run_cli, story

FEED = ['viewer', 'news_feed']


def page(ids, has_next=True, cursor='C1'):
    return query_result(graphql_body(FEED, [story(i) for i in ids], has_next, cursor))


def test_1_a_tab_reopened_under_another_account_stops_the_command(browser, data_dir):
    known_tab(browser, data_dir, 'GONE')
    browser.vanish_after_state('GONE')
    browser.respond('open', {'tab': {'id': 'NEW', 'url': 'https://www.facebook.com/'}})
    browser.respond('state', {**STATE_OK, 'user_id': '222', 'resources': 20})
    code, out, _ = run_cli(browser, 'feed')
    result = json.loads(out)
    assert code == 4 and 'different Facebook account' in result['message']
    assert not [c for c in browser.calls() if c['op'] == 'query' and c['tab'] == 'NEW']
    assert not (data_dir / 'handles').exists() or not list((data_dir / 'handles').glob('*.json'))


def test_3_routing_needs_room_in_the_budget_first(browser, data_dir):
    known_tab(browser, data_dir)
    rejected = json.dumps({'errors': [{'message': 'PersistedQueryNotFound'}]})
    browser.respond('query', query_result(rejected, source='stored'))
    code, out, _ = run_cli(browser, 'feed', '--max-requests', '2', '--json')
    result = json.loads(out)
    assert not [c for c in browser.calls() if c['op'] == 'route']
    assert result['request_count'] <= 2 and result['stop_reason'] == 'budget'


def test_3_a_rate_limit_seen_among_the_pages_own_requests_blocks(browser, data_dir):
    known_tab(browser, data_dir)
    rejected = json.dumps({'errors': [{'message': 'PersistedQueryNotFound'}]})
    browser.respond('query', query_result(rejected, source='stored'))
    browser.respond('route', {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'explicit': 0,
                              'resources': 3, 'statuses': [200, 429, 200], 'live': {}})
    code, out, _ = run_cli(browser, 'feed', '--json')
    assert code == 5 and json.loads(out)['error'] == 'blocked'
    assert json.loads((data_dir / 'protection/blocked.json').read_text())['reason'] == 'rate_limit'


def test_3_a_rate_limit_status_beside_a_query_blocks(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', {**page(['A']), 'statuses': [200, 429]})
    code, out, _ = run_cli(browser, 'feed', '--json')
    assert code == 5 and json.loads((data_dir / 'protection/blocked.json').read_text())['reason'] == 'rate_limit'


def test_5_requests_made_before_a_startup_failure_are_still_reported(browser, data_dir):
    browser.respond('open', {'tab': {'id': 'T9', 'url': 'https://www.facebook.com/checkpoint/1/'}})
    browser.respond('state', {**STATE_OK, 'location': 'https://www.facebook.com/checkpoint/1/', 'user_id': None,
                              'resources': 20})
    code, out, _ = run_cli(browser, 'feed')
    result = json.loads(out)
    assert code == 5 and result['request_count'] == 30 and result['tab_opened_requests'] == 30  # its reservation


def test_6_a_route_that_times_out_stays_counted_at_its_reservation(browser, data_dir):
    known_tab(browser, data_dir)
    rejected = json.dumps({'errors': [{'message': 'PersistedQueryNotFound'}]})
    browser.respond('query', query_result(rejected, source='stored'))
    browser.respond('route', {'__raw_stdout': 'Error: other side closed\n', '__exit': 1})
    code, out, _ = run_cli(browser, 'feed', '--json')
    result = json.loads(out)
    assert code == 3 and result['request_count'] >= 1 + 10


def test_8_a_blocked_collection_does_not_offer_to_resume(browser, data_dir, tmp_path):
    known_tab(browser, data_dir)
    browser.respond('query', page(['A'], cursor='C1'))
    browser.respond('query', {'status': 429, 'url': 'https://www.facebook.com/api/graphql/', 'body': '',
                              'used': {'source': 'live'}, 'explicit': 1, 'resources': 1})
    code, out, _ = run_cli(browser, 'feed', '--out', str(tmp_path / 'f.ndjson'), '--json')
    result = json.loads(out)
    assert code == 5 and 'next' not in result


def test_10_a_complete_collection_touches_no_browser(browser, data_dir, tmp_path):
    out_file = tmp_path / 'f.ndjson'
    known_tab(browser, data_dir)
    browser.respond('query', page(['A'], has_next=False))
    run_cli(browser, 'feed', '--out', str(out_file))
    (data_dir / 'session/default.json').unlink()  # the dedicated tab is no longer known
    calls = len(browser.calls())
    code, out, _ = run_cli(browser, 'feed', '--out', str(out_file), '--json')
    result = json.loads(out)
    assert code == 0 and result['already_complete'] is True and result['request_count'] == 0
    assert len(browser.calls()) == calls


def test_10_a_foreign_collection_is_refused_before_the_browser(browser, data_dir, tmp_path):
    out_file = tmp_path / 'f.ndjson'
    known_tab(browser, data_dir)
    browser.respond('query', page(['A'], has_next=False))
    run_cli(browser, 'feed', '--out', str(out_file))
    calls = len(browser.calls())
    code, out, _ = run_cli(browser, 'feed', '--sort', 'recent', '--out', str(out_file))
    assert code == 2 and len(browser.calls()) == calls


# --- second review of the repairs ---

def test_r2_1_a_checkpoint_outranks_a_background_rate_limit(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', {'status': 200, 'url': 'https://www.facebook.com/api/graphql/',
                              'body': json.dumps({'checkpoint_url': 'https://www.facebook.com/checkpoint/1/'}),
                              'used': {'source': 'live'}, 'explicit': 1, 'resources': 2, 'statuses': [200, 429]})
    code, out, _ = run_cli(browser, 'feed')
    record = json.loads((data_dir / 'protection/blocked.json').read_text())
    assert code == 5 and record['reason'] == 'checkpoint' and record['expires_at'] is None


def test_r2_2_a_rate_limit_beside_a_failed_request_still_blocks(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', {'network_error': 'aborted', 'used': {'source': 'live'}, 'explicit': 1, 'resources': 2,
                              'statuses': [429, 0]})
    code, out, _ = run_cli(browser, 'feed')
    assert code == 5 and 'next' not in json.loads(out)
    assert json.loads((data_dir / 'protection/blocked.json').read_text())['reason'] == 'rate_limit'


def test_r2_2_a_rate_limit_seen_while_no_command_ran_blocks_at_the_next_start(browser, data_dir):
    browser.tab('T1')
    (data_dir / 'session').mkdir(parents=True, exist_ok=True)
    (data_dir / 'session/default.json').write_text(json.dumps({'tab': 'T1', 'queries': {}}))
    browser.respond('state', {**STATE_OK, 'statuses': [200, 429]})
    code, out, _ = run_cli(browser, 'feed')
    assert code == 5 and not [c for c in browser.calls() if c['op'] == 'query']
    assert json.loads((data_dir / 'protection/blocked.json').read_text())['reason'] == 'rate_limit'


def test_r2_4_a_screen_that_loads_more_than_reserved_is_charged_in_full(browser, data_dir):
    known_tab(browser, data_dir)
    rejected = json.dumps({'errors': [{'message': 'PersistedQueryNotFound'}]})
    browser.respond('query', query_result(rejected, source='stored'))
    browser.respond('route', {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'explicit': 0,
                              'resources': 12, 'statuses': [200] * 12,
                              'live': {'CometNewsFeedPaginationQuery': {'doc_id': '222', 'flags': {}}}})
    code, out, _ = run_cli(browser, 'feed', '--max-requests', '11', '--json')
    result = json.loads(out)
    assert result['request_count'] == 13 and result['stop_reason'] == 'budget'  # truthful, and nothing more is sent
    assert len([c for c in browser.calls() if c['op'] == 'query']) == 1


def test_r2_5_a_header_without_context_is_refused_not_crashed(browser, data_dir, tmp_path):
    out_file = tmp_path / 'f.ndjson'
    out_file.write_text('{"kind":"header","format":3}\n')
    code, out, _ = run_cli(browser, 'feed', '--out', str(out_file))
    assert code == 2 and json.loads(out)['error'] == 'argument' and browser.calls() == []


# --- third review: accounting at reservation and lifecycle boundaries ---

def test_r3_3_late_route_requests_are_counted_against_its_reservation(browser, data_dir):
    known_tab(browser, data_dir)
    rejected = json.dumps({'errors': [{'message': 'PersistedQueryNotFound'}]})
    browser.respond('query', query_result(rejected, source='stored'))
    browser.respond('route', {'location': 'https://www.facebook.com/', 'user_id': '1000123', 'explicit': 0,
                              'resources': 5, 'statuses': [200] * 5,
                              'live': {'CometNewsFeedPaginationQuery': {'doc_id': '222', 'flags': {}}}})
    # the next query's ledger delta carries the route's five late requests and its own one
    browser.respond('query', {**page(['A'], has_next=False), 'resources': 6, 'statuses': [200] * 6})
    code, out, _ = run_cli(browser, 'feed', '--json')
    assert code == 0 and json.loads(out)['request_count'] == 1 + 10 + 1


def test_r3_4_late_opening_requests_stay_outside_the_budget(browser, data_dir):
    browser.respond('open', {'tab': {'id': 'T9', 'url': 'https://www.facebook.com/'}})
    browser.respond('state', {**STATE_OK, 'resources': 1, 'statuses': [200]})
    browser.respond('query', {**page(['A'], has_next=False), 'resources': 2, 'statuses': [200, 200]})
    code, out, _ = run_cli(browser, 'feed', '--max-requests', '1', '--json')
    result = json.loads(out)
    assert code == 0 and result['results'] and result['tab_opened_requests'] == 30
    assert result['request_count'] - result['tab_opened_requests'] == 1


def test_r3_2_a_known_rate_limit_is_not_followed_by_a_request(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', {'stopped': 'rate_limit', 'statuses': [429], 'unwatched': [], 'explicit': 0, 'resources': 1})
    code, out, _ = run_cli(browser, 'feed')
    assert code == 5 and json.loads((data_dir / 'protection/blocked.json').read_text())['reason'] == 'rate_limit'
