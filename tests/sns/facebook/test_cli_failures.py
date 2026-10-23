"""Failure paths through the real cli.py and a fake Aside: partial results, login, blocks, timeouts, what stops a
continuation, and arguments."""
import json
import time

from tests.sns.facebook.scenes import (ACCOUNT, GRAPHQL, graphql_body, known_tab, look, queries, query_result, run,
                                       stand_block, stand_hold, state_of, story)

FEED = ['viewer', 'news_feed']


def page(ids, has_next=True, cursor='C1'):
    return query_result(graphql_body(FEED, [story(i) for i in ids], has_next, cursor))


def failure(status=500):
    return {'status': status, 'url': GRAPHQL, 'body': 'oops', 'used': {'source': 'live'}, 'explicit': 1, 'resources': 1,
            'statuses': [status], 'unwatched': [], 'limited': False, 'user_id': ACCOUNT}


def test_a_failure_after_records_is_partial_and_keeps_them(browser):
    known_tab(browser)
    browser.respond('facebook.query', page(['A'], cursor='C1'))
    browser.respond('facebook.query', failure())
    code, out, _ = run(browser, 'feed', '--limit', '5')
    assert code == 8
    lines = out.splitlines()
    assert lines[0].startswith('facebook feed · sort=top · 1 shown · stopped=query_failure')
    assert any(line.startswith('coverage: incomplete — Facebook answered with HTTP 500') for line in lines)
    assert lines[-1].startswith('more: ')  # a failed page can be retried later from its cursor


def test_a_failure_before_any_record_is_exit_6_json(browser):
    known_tab(browser)
    browser.respond('facebook.query', failure())
    code, out, _ = run(browser, 'feed')
    result = json.loads(out)
    assert code == 6 and result['ok'] is False and result['error'] == 'failed' and result['fix']


def test_a_login_response_is_exit_4_and_stops_the_continuation(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result('for (;;);' + json.dumps({'error': 1357001})))
    code, out, _ = run(browser, 'feed')
    result = json.loads(out)
    assert code == 4 and result['error'] == 'login' and 'next' not in result


def test_a_login_wall_after_records_keeps_them_and_offers_no_continuation(browser):
    """Appendix C: a failure that stops a continuation is a login, a person block or an unavailable target; the old
    skill kept a handle after some of them. A rate limit after records is the other kind: it passes, so more: stays."""
    known_tab(browser)
    browser.respond('facebook.query', page(['A'], cursor='C1'))
    browser.respond('facebook.query', query_result('for (;;);' + json.dumps({'error': 1357001})))
    code, out, _ = run(browser, 'feed', '--limit', '5')
    assert code == 4 and 'Author A' in out and not any(line.startswith('more: ') for line in out.splitlines())
    look(browser)
    browser.respond('facebook.query', page(['B'], cursor='C2'))
    browser.respond('facebook.query', query_result('', status=429))
    code, out, _ = run(browser, 'feed', '--limit', '5')
    assert code == 0 and 'stopped=rate_limited' in out.splitlines()[0] and out.splitlines()[-1].startswith('more: ')
    assert 'limit account resets' in out.splitlines()[0]


def test_aside_timeout_is_exit_3_and_counted(browser):
    known_tab(browser)
    browser.respond('facebook.query', {'__raw_stdout': 'Error: other side closed\n', '__exit': 1})
    code, out, _ = run(browser, 'feed')
    result = json.loads(out)
    assert code == 3 and result['error'] == 'aside' and result['request_count'] == 1


def test_a_standing_checkpoint_makes_no_request_at_all(browser):
    stand_block()
    code, out, _ = run(browser, 'feed')
    assert code == 5 and [c for c in browser.calls() if c['op'] != 'account_status'] == []


def test_a_standing_hold_makes_no_request_and_names_when_it_ends(browser):
    stand_hold(900)
    code, out, _ = run(browser, 'feed')
    result = json.loads(out)
    assert code == 5 and 'rate-limited' in result['message'] and result['limit']['reset'] > time.time()
    assert [c for c in browser.calls() if c['op'] != 'account_status'] == []


def test_unreadable_protection_state_blocks_before_the_browser(browser, data_dir):
    directory = data_dir / 'facebook' / 'u0' / 'protection'
    directory.mkdir(parents=True)
    (directory / 'pace.json').write_text('{broken')
    known_tab(browser)
    code, out, _ = run(browser, 'feed')
    assert code == 5 and 'unreadable' in json.loads(out)['message']
    assert queries(browser) == []


def test_a_checkpoint_response_is_recorded_for_the_account_and_stops_everything(browser):
    known_tab(browser)
    browser.respond('facebook.query', {'status': 200, 'url': 'https://www.facebook.com/checkpoint/1/',
                                       'body': '<html></html>', 'used': {'source': 'live'}, 'explicit': 1,
                                       'resources': 1, 'statuses': [200], 'unwatched': [], 'limited': False,
                                       'user_id': ACCOUNT})
    code, out, _ = run(browser, 'feed')
    result = json.loads(out)
    assert code == 5 and result['error'] == 'blocked' and 'next' not in result
    assert state_of()['person']['reason'] == 'checkpoint' and state_of()['person']['viewer'] == ACCOUNT
    assert 'facebook.blank' in browser.ops()  # the tab is emptied so the app stops polling
    look(browser)
    code, out, _ = run(browser, 'feed')
    assert code == 5 and len(queries(browser)) == 1


def test_a_429_is_a_hold_not_a_person_block_and_it_passes_by_itself(browser):
    known_tab(browser)
    browser.respond('facebook.query', query_result('', status=429))
    code, out, _ = run(browser, 'feed')
    assert code == 5
    state = state_of()
    assert state['hold'] and not state['person'] and 1790 < state['hold']['until'] - state['hold']['at'] < 1810


def test_invalid_arguments_are_exit_2_json(browser):
    for args in (['feed', '--since', '2026-13-01'], ['feed', '--max-requests', '5'], ['feed', '--limit', '0'],
                 ['feed', '--since', '2026-09-10', '--until', '2026-09-01'], ['nope'], ['feed', '--chars', '-1']):
        code, out, _ = run(browser, *args)
        result = json.loads(out)
        assert code == 2 and result['ok'] is False and result['error'] == 'argument' and result['fix'], args
    assert [c for c in browser.calls() if c['op'] != 'account_status'] == []
