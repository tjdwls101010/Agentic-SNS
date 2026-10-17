"""quotes and reposts through the real CLI and a scripted Aside.

The response shape is the one observed 2026-10-17 from the post activity tab query (all content here is synthetic):
data.feedback_hub_tab_items.edges[].node {actor {strong_id__}, extra {icon_name, content, context, title},
destination, timestamp, pk}, an empty cursor per edge and no next page, beside data.feedback_hub {num_activity,
post {strong_id__: "<post id>_<author id>"}}. title names the account as {username|color|1|user?id=<id>|verified|none};
context is its display name; a quote's destination is media?id=<quote id>_<author id>&shortcode=<code>.
"""
import json

from conftest import known_tab, query_result, run_cli

URL = 'https://www.threads.com/@example.author/post/DThr_201'
POST_ID = '14535981231413'


def item(tab, pk, username, user_id, *, text='', verified=False, at=1791428400.0):
    destination = (f'media?id={pk}_{user_id}&shortcode=Cq{pk[-3:]}' if tab == 'quote' else f'user?id={user_id}')
    return {'node': {'actor': {'strong_id__': user_id},
                     'extra': {'icon_name': tab, 'content': text, 'context': username.title(),
                               'title': f'{{{username}|000000|1|user?id={user_id}|{"verified" if verified else "none"}}}'},
                     'destination': destination, 'timestamp': at, 'pk': pk, '__typename': 'XDTFeedbackHubItem'},
            'cursor': ''}


def activity(items, total, about=POST_ID):
    return {'data': {'feedback_hub_tab_items': {'edges': items, 'page_info': {'end_cursor': None, 'has_next_page': False}},
                     'feedback_hub': {'num_activity': total, 'post': {'strong_id__': f'{about}_1000000001'}}},
            'errors': [{'message': 'execution error', 'severity': 'CRITICAL'}]}


def test_quotes_reads_the_posts_quoting_this_one_in_one_request(browser, data_dir):
    body = activity([item('quote', '3000000000000000301', 'someone.else', '1000000002', text='Quoting this\nwith care',
                          verified=True),
                     item('quote', '3000000000000000302', 'third.person', '1000000003', text='Me too')], 5)
    known_tab(browser, data_dir).respond('query', query_result(body))
    code, out, _ = run_cli(browser, 'quotes', URL, '--json')
    result = json.loads(out)
    assert code == 0, result
    call = next(c['args'] for c in browser.calls() if c['op'] == 'query')
    assert call['name'] == 'BarcelonaFeedbackHubTabQuery'
    assert call['variables'] == {**call['variables'], 'post_id': POST_ID, 'tab_type': 'quote', 'sort_type': 'default'}
    first = result['results'][0]
    assert first['id'] == '3000000000000000301' and first['text'] == 'Quoting this\nwith care'
    assert first['url'] == 'https://www.threads.com/@someone.else/post/Cq301'
    assert first['author'] == {**first['author'], 'id': '1000000002', 'username': 'someone.else',
                               'full_name': 'Someone.Else', 'is_verified': True}
    assert first['created_at'] == '2026-10-08T03:00:00Z' and first['role'] == 'quote'
    # two of the five quotes Threads reports came, with no way to ask for more
    assert result['stop_reason'] == 'server_capped' and result['reported_total'] == 5
    assert result['request_count'] == 1


def test_reposts_lists_the_accounts_with_when_they_reposted(browser, data_dir):
    body = activity([item('repost', '3000000000000000311', 'someone.else', '1000000002', at=1791432000.0)], 1)
    known_tab(browser, data_dir).respond('query', query_result(body))
    code, out, _ = run_cli(browser, 'reposts', URL)
    assert code == 0, out
    call = next(c['args'] for c in browser.calls() if c['op'] == 'query')
    assert call['variables']['tab_type'] == 'repost'
    lines = out.splitlines()
    assert lines[0].startswith('reposts · 1 shown · stopped=exhausted · requests=1/25')
    assert any(line.startswith('[a1] @someone.else (Someone.Else)') and 'reposted 2026-10-08' in line for line in lines)
    assert 'url: "https://www.threads.com/@someone.else"' in out


def test_an_answer_about_another_post_or_of_another_kind_is_refused(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(activity([], 0, about='999')))
    code, out, _ = run_cli(browser, 'quotes', URL)
    assert code == 6 and 'about another post' in json.loads(out)['message']
    browser.respond('state', {'location': 'https://www.threads.com/search', 'user_id': '1000000009', 'runtime': True,
                              'resources': 0, 'statuses': [], 'signals': []})
    browser.respond('query', query_result(activity([item('like', '3000000000000000321', 'someone.else', '1000000002')], 1)))
    code, out, _ = run_cli(browser, 'reposts', URL)
    assert code == 6 and 'other than reposts' in json.loads(out)['message']


def test_no_quotes_is_an_explicit_empty_answer(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(activity([], 0)))
    code, out, _ = run_cli(browser, 'quotes', URL, '--json')
    assert code == 7 and json.loads(out)['results'] == []
