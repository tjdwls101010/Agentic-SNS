"""Failure paths through the real cli.py and a fake Aside: partial results, login, a vanished tab, timeouts."""
import json

from conftest import STATE_OK, graphql_body, known_tab, query_result, run_cli, story

FEED = ['viewer', 'news_feed']


def page(ids, has_next=True, cursor='C1'):
    return query_result(graphql_body(FEED, [story(i) for i in ids], has_next, cursor))


def test_a_failure_after_records_is_partial_and_keeps_them(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', page(['A'], cursor='C1'))
    browser.respond('query', {'status': 500, 'url': 'https://www.facebook.com/api/graphql/', 'body': 'oops',
                              'used': {'source': 'live'}, 'explicit': 1, 'resources': 1})
    code, out, _ = run_cli(browser, 'feed')
    assert code == 8
    lines = out.splitlines()
    assert lines[0].startswith('feed · sort=top · 1 shown · stopped=query_failure')
    assert any(line.startswith('coverage: incomplete — Facebook answered with HTTP 500') for line in lines)
    assert lines[-1].startswith('more: ')  # a failed page can be retried later from its cursor


def test_a_failure_before_any_record_is_exit_6_json(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', {'status': 500, 'url': 'https://www.facebook.com/api/graphql/', 'body': 'oops',
                              'used': {'source': 'live'}, 'explicit': 1, 'resources': 1})
    code, out, _ = run_cli(browser, 'feed')
    result = json.loads(out)
    assert code == 6 and result['ok'] is False and result['error'] == 'failed' and result['fix']


def test_a_login_response_is_exit_4(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', query_result('for (;;);' + json.dumps({'error': 1357001})))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 4 and json.loads(out)['error'] == 'login' and 'next' not in json.loads(out)


def test_a_vanished_tab_is_reopened_once(browser, data_dir):
    known_tab(browser, data_dir, 'GONE')
    browser.vanish_after_state('GONE')
    browser.respond('open', {'tab': {'id': 'NEW', 'url': 'https://www.facebook.com/'}})
    browser.respond('state', {**STATE_OK, 'resources': 20})
    browser.respond('query', page(['A'], has_next=False))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 0, out
    assert out.splitlines()[0] == 'feed · sort=top · 1 shown · stopped=exhausted · requests=1/25 · tab opened (+30 requests)'
    assert json.loads((data_dir / 'session/default.json').read_text())['tab'] == 'NEW'


def test_aside_timeout_is_exit_3_and_counted(browser, data_dir):
    known_tab(browser, data_dir)
    browser.respond('query', {'__raw_stdout': 'Error: other side closed\n', '__exit': 1})
    code, out, _ = run_cli(browser, 'feed')
    result = json.loads(out)
    assert code == 3 and result['error'] == 'aside' and result['request_count'] == 1


def test_unreadable_protection_state_blocks_before_the_browser(browser, data_dir):
    (data_dir / 'protection').mkdir(parents=True)
    (data_dir / 'protection/pace.json').write_text('{broken')
    known_tab(browser, data_dir)
    code, out, _ = run_cli(browser, 'feed')
    assert code == 5 and 'unreadable' in json.loads(out)['message']
    assert [c['op'] for c in browser.calls() if c['op'] == 'query'] == []


def test_a_blocked_account_makes_no_request_at_all(browser, data_dir):
    import time
    (data_dir / 'protection').mkdir(parents=True)
    (data_dir / 'protection/blocked.json').write_text(json.dumps({'reason': 'checkpoint', 'blocked_at': time.time(),
                                                                  'expires_at': None}))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 5 and browser.calls() == []


def test_invalid_arguments_are_exit_2_json(browser, data_dir):
    for args in (['feed', '--since', '2026-13-01'], ['feed', '--max-requests', '401'], ['feed', '--limit', '0'],
                 ['feed', '--since', '2026-09-10', '--until', '2026-09-01'], ['nope'], ['feed', '--chars', '-1']):
        code, out, _ = run_cli(browser, *args)
        result = json.loads(out)
        assert code == 2 and result['ok'] is False and result['error'] == 'argument' and result['fix'], args
    assert browser.calls() == []
