"""feed through the real CLI and a scripted Aside: pages, units, windows (fixtures/paging.json), handles, output."""
import json
from datetime import datetime

import pytest

from conftest import command_of, fixture, known_tab, query_result, run_cli

PAGING = fixture('paging.json')
AUTHOR = {'pk': '1000000001', 'username': 'example.author'}


def pk(identity):
    return str(3000000000000000000 + sum(ord(c) * 131 ** i for i, c in enumerate(identity)) % 10 ** 15)


def post(identity, created_at=None, pinned=False, unavailable=False, author=AUTHOR, **info):
    if unavailable:
        return {'pk': pk(identity), 'is_post_unavailable': True}
    raw = {'pk': pk(identity), 'code': 'C' + identity.replace('-', ''), 'user': author, 'caption': {'text': 'post ' + identity},
           'text_post_app_info': dict(info)}
    if created_at:
        raw['taken_at'] = int(datetime.fromisoformat(created_at.replace('Z', '+00:00')).timestamp())
    if pinned:
        raw['text_post_app_info']['pinned_post_info'] = {'is_pinned_to_profile': True}
    return raw


def feed_body(groups, has_next, cursor):
    edges = [{'node': {'text_post_app_thread': {'thread_items': [{'post': item} for item in group]}}} for group in groups]
    return {'data': {'feedData': {'edges': edges, 'page_info': {'has_next_page': has_next, 'end_cursor': cursor}}}}


def scripted(browser, data_dir, pages):
    known_tab(browser, data_dir)
    for page in pages:
        if 'error' in page:
            kind = page['error']
            if kind == 'failed':
                browser.respond('query', query_result('oops', status=500))
            elif kind == 'shape_changed':
                browser.respond('query', query_result({'data': {'feedData': None}}))
            elif kind == 'checkpoint':
                browser.respond('query', query_result({'errors': [{'code': 368, 'message': 'blocked'}]}))
            elif kind == 'login':
                browser.respond('query', query_result({'errors': [{'message': 'login_required'}]}))
            continue
        groups = [[post(r['id'], r.get('created_at'), r.get('pinned'), r.get('unavailable')) for r in group]
                  for group in page['groups']]
        browser.respond('query', query_result(feed_body(groups, page['has_next'], page['cursor'])))
    return browser


FEED_SCENARIOS = [s for s in PAGING['scenarios'] if s['options'].get('chronological') or 'chronological' not in
                  s['options'] and not s['options'].get('policy') and 'start' not in s]


@pytest.mark.parametrize('scenario', FEED_SCENARIOS, ids=lambda s: s['name'])
def test_paging_and_window_scenarios(browser, data_dir, scenario):
    options, expected = scenario['options'], scenario['expected']
    pages = list(scenario['pages'])
    args = ['feed', '--json']
    if options.get('chronological'):
        args += ['--feed', 'following']
    for key in ('since', 'until', 'limit'):
        if options.get(key):
            args += ['--' + key, str(options[key])]
    if options.get('limit') is None and not options.get('since') and not options.get('until'):
        args += ['--limit', '1000']
    budget_stop = any(p.get('error') == 'budget' for p in pages)
    if budget_stop:
        args += ['--max-requests', str(pages.index(next(p for p in pages if p.get('error') == 'budget')))]
        pages = [p for p in pages if p.get('error') != 'budget']
    scripted(browser, data_dir, pages)
    code, out, err = run_cli(browser, *args, env={'TZ': options.get('tz', 'UTC')})
    result = json.loads(out)
    names = {pk(r['id']): r['id'] for p in scenario['pages'] for g in p.get('groups', []) for r in g}
    assert [names[r['id']] for r in result['results']] == expected['shown'], err
    assert result['stop_reason'] == expected['stop_reason']
    assert code == expected['code']
    if 'pages_fetched' in expected:
        assert browser.ops().count('query') == expected['pages_fetched']
    if 'window' in expected:
        assert result['window']['coverage'].startswith('closed') is expected['window']['complete']
        undated = expected['window']['undated']
        assert any(f'{undated} undated' in note for note in result.get('coverage', [])) is (undated > 0)
    if expected.get('continues') or expected.get('pending'):
        assert result.get('next')


def test_foryou_never_closes_a_window(browser, data_dir):
    pages = [{'groups': [[{'id': 'A', 'created_at': '2026-09-01T00:00:00Z'}]], 'has_next': False, 'cursor': None}]
    scripted(browser, data_dir, pages)
    code, out, _ = run_cli(browser, 'feed', '--since', '2026-10-01', '--json')
    assert json.loads(out)['window']['coverage'] == 'sample (not in date order)' and code == 7


def test_one_page_by_default_and_more_continues_from_the_kept_tail(browser, data_dir):
    page1 = feed_body([[post('A', '2026-10-08T03:00:00Z')], [post('B', '2026-10-07T03:00:00Z')]], True, 'CUR1')
    page2 = feed_body([[post('B', '2026-10-07T03:00:00Z')], [post('C', '2026-10-06T03:00:00Z')]], False, None)
    known_tab(browser, data_dir).respond('query', query_result(page1))
    code, out, _ = run_cli(browser, 'feed', '--limit', '1')
    assert code == 0 and '[p1]' in out and 'more: ' in out
    assert browser.ops().count('query') == 1
    more = out.split('more: ', 1)[1].strip()
    browser.respond('state', {'location': 'https://www.threads.com/search', 'user_id': '1000000009', 'runtime': True,
                              'resources': 0, 'statuses': [], 'signals': []})
    browser.respond('query', query_result(page2))
    code, out, _ = run_cli(browser, *command_of('more: ' + more))
    assert code == 0
    shown = [line for line in out.splitlines() if line.startswith('[p')]
    assert len(shown) == 1 and browser.ops().count('query') == 1  # B came from the kept tail: no request
    variables = [c['args']['variables'] for c in browser.calls() if c['op'] == 'query']
    assert variables[0]['variant'] == 'for_you'


def test_a_unit_shows_a_reply_and_a_continuation_together(browser, data_dir):
    other = {'pk': '1000000002', 'username': 'someone.else'}
    first, reply = post('Q', '2026-10-08T03:00:00Z'), post('R', '2026-10-08T04:00:00Z', author=other)
    reply['text_post_app_info'].update(is_reply=True, reply_to_id=first['pk'])
    cont = post('S', '2026-10-08T05:00:00Z')
    cont['text_post_app_info'].update(is_reply=True, reply_to_id=reply['pk'])
    known_tab(browser, data_dir).respond('query', query_result(feed_body([[first, reply, cont]], False, None)))
    code, out, _ = run_cli(browser, 'feed')
    assert code == 0
    lines = [line for line in out.splitlines() if line.lstrip().startswith('[p')]
    assert 'reply-to=p1' in lines[1] and 'reply-to=p2' in lines[2]  # S answers R, a different author
    assert lines[1].startswith('  [p2]')


def test_the_header_names_feed_cost_and_the_text_preview(browser, data_dir):
    text = 'x' * 300
    raw = post('A', '2026-10-08T03:00:00Z')
    raw['caption'] = {'text': text}
    known_tab(browser, data_dir, resources=3).respond('query', query_result(feed_body([[raw]], True, 'CUR1'), resources=2))
    code, out, _ = run_cli(browser, 'feed', '--feed', 'following')
    header = out.splitlines()[0]
    assert header.startswith('feed · feed=following · 1 shown · stopped=limit_reached · requests=2/25')
    assert 'unwatched=3' in header
    assert 'text[180 of 300 chars shown]' in out and 'url: "https://www.threads.com/@example.author/post/CA"' in out


def test_json_keeps_whole_texts_and_variables_follow_the_feed(browser, data_dir):
    raw = post('A', '2026-10-08T03:00:00Z')
    raw['caption'] = {'text': 'y' * 500}
    known_tab(browser, data_dir).respond('query', query_result(feed_body([[raw]], False, None)))
    code, out, _ = run_cli(browser, 'feed', '--feed', 'following', '--json')
    result = json.loads(out)
    assert code == 0 and result['results'][0]['text'] == 'y' * 500 and result['feed'] == 'following'
    [call] = [c for c in browser.calls() if c['op'] == 'query']
    assert call['args']['name'] == 'BarcelonaFeedDirectQuery'
    assert call['args']['variables']['variant'] == 'following'
    assert call['args']['variables']['data']['pagination_source'] == 'text_post_feed_following'
