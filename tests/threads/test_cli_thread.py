"""post and replies through the real CLI and a scripted Aside (fixtures/records_thread.json for the post page)."""
import copy
import json

from conftest import command_of, fixture, known_tab, query_result, run_cli, state

THREAD = fixture('records_thread.json')
CASE = next(c for c in THREAD['cases'] if c['name'] == 'post-parents-replies-coverage')
URL = 'https://www.threads.com/@example.author/post/DThr_201'


def expand(value, users=THREAD['users']):
    if isinstance(value, dict):
        if '$user' in value:
            return {**users[value['$user']], **{k: expand(v) for k, v in value.items() if k != '$user'}}
        return {k: expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v) for v in value]
    return value


def post_page(next_cursor='REPCUR1', branch_cursor='SUBCUR1'):
    target, parents, replies = (copy.deepcopy(r) for r in expand(CASE['responses']))
    direct = replies['media']['text_post_app_info']['direct_replies']
    direct['page_info'] = {'has_next_page': bool(next_cursor), 'end_cursor': next_cursor}
    direct['edges'][1]['node']['posts']['page_info'] = {'has_next_page': True, 'end_cursor': branch_cursor}
    return [{'data': target}, {'data': parents}, {'data': replies}]


def scripted_post(browser, data_dir, **kwargs):
    known_tab(browser, data_dir)
    for body in post_page(**kwargs):
        browser.respond('query', query_result(body))
    return browser


def test_post_reads_three_queries_by_the_id_its_shortcode_encodes(browser, data_dir):
    scripted_post(browser, data_dir)
    code, out, _ = run_cli(browser, 'post', URL, '--json')
    result = json.loads(out)
    assert code == 0, result
    calls = [c['args'] for c in browser.calls() if c['op'] == 'query']
    assert [c['name'] for c in calls] == ['BarcelonaPostPageTargetQuery', 'BarcelonaPostPageUpwardQuery',
                                         'BarcelonaPostPageDownwardQuery']
    assert {c['variables']['postID'] for c in calls} == {CASE['post_id']}
    assert calls[2]['variables']['sortOrder'] == 'TOP'
    assert [r['role'] for r in result['results']][:2] == ['parent', 'post']
    assert result['replies'] == CASE['expected']['coverage']
    assert result['request_count'] == 3


def test_post_text_shows_the_post_in_full_and_the_reply_tree(browser, data_dir):
    scripted_post(browser, data_dir)
    code, out, _ = run_cli(browser, 'post', URL, '--chars', '3')
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith('post · sort=top · 8 shown · stopped=limit_reached · requests=3/25')
    assert lines[1].startswith('replies: 2 of 5 direct received · ≈1 never received (estimate)')
    assert 'text[8 of 8 chars shown]: "The post"' in out  # the opened post is never clipped
    assert 'text[3 of 10 chars shown]: "The…"' in out      # its parent is
    assert any('reply-to=r1' in line and line.startswith('  [r2]') for line in lines)
    assert any('continuation of r4' in line for line in lines)
    assert 'more: ' in out and out.count('   replies ') == 1


def test_more_reads_the_next_batch_of_direct_replies(browser, data_dir):
    scripted_post(browser, data_dir)
    code, out, _ = run_cli(browser, 'post', URL)
    more = next(line for line in out.splitlines() if line.startswith('more: '))
    batch = {'data': {'media': {'text_post_app_info': {'direct_replies': {'edges': [
        {'node': {'posts': {'edges': [{'node': {'pk': '3000000000000000271', 'code': 'Cr271', 'caption': {'text': 'late'},
                                                'user': THREAD['users']['C'],
                                                'text_post_app_info': {'is_reply': True}}}]}}}],
        'page_info': {'has_next_page': False, 'end_cursor': None}}}}}}
    browser.respond('state', state()).respond('query', query_result(batch))
    code, out, _ = run_cli(browser, *command_of(more), '--json')
    result = json.loads(out)
    assert code == 0, result
    call = [c['args'] for c in browser.calls() if c['op'] == 'query'][-1]
    assert call['name'] == 'BarcelonaPostPageDirectRepliesRefetchQuery'
    assert call['variables']['after'] == 'REPCUR1' and call['variables']['postID'] == CASE['post_id']
    assert [r['id'] for r in result['results']] == ['3000000000000000271']
    assert 'next' not in result and result['coverage'][0].startswith('Threads reports 5 direct replies')


def test_a_branch_handle_opens_the_replies_under_one_reply(browser, data_dir):
    scripted_post(browser, data_dir)
    code, out, _ = run_cli(browser, 'post', URL, '--json')
    reply = next(r for r in json.loads(out)['results'] if r.get('replies_handle'))
    under = {'data': {'media': {'text_post_app_info': {'inline_expansion': {'posts': {'edges': [
        {'node': {'pk': '3000000000000000281', 'code': 'Cr281', 'caption': {'text': 'deeper'}, 'user': THREAD['users']['A'],
                  'text_post_app_info': {'is_reply': True, 'reply_to_id': reply['id']}}}],
        'page_info': {'has_next_page': False, 'end_cursor': None}}}}}}}
    browser.respond('state', state()).respond('query', query_result(under))
    code, out, _ = run_cli(browser, 'replies', str(reply['replies_handle']))
    assert code == 0, out
    call = [c['args'] for c in browser.calls() if c['op'] == 'query'][-1]
    assert call['name'] == 'BarcelonaPostPageThreadViewSectionInlineExpansionQuery'
    assert call['variables'] == {**call['variables'], 'postID': reply['id'], 'permalinkPostID': CASE['post_id'],
                                 'after': 'SUBCUR1'}
    assert 'deeper' in out and 'reply-to=' in out


def test_recent_sort_asks_threads_for_newest_first(browser, data_dir):
    scripted_post(browser, data_dir, next_cursor=None)
    code, out, _ = run_cli(browser, 'post', URL, '--sort', 'recent', '--json')
    assert code == 0
    assert [c['args'] for c in browser.calls() if c['op'] == 'query'][2]['variables']['sortOrder'] == 'RECENT'
    assert 'next' not in json.loads(out)


def test_a_deleted_post_is_unavailable(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result({'data': {'media': None}}))
    code, out, _ = run_cli(browser, 'post', URL)
    assert code == 9 and json.loads(out)['error'] == 'unavailable'


def test_a_tombstone_post_is_unavailable(browser, data_dir):
    known_tab(browser, data_dir)
    pages = post_page()
    pages[0]['data']['media']['is_post_unavailable'] = True
    for body in pages:
        browser.respond('query', query_result(body))
    code, out, _ = run_cli(browser, 'post', URL)
    assert code == 9


def test_a_bad_or_foreign_handle_is_an_argument_error(browser, data_dir):
    known_tab(browser, data_dir)
    code, out, _ = run_cli(browser, 'replies', 'x7')
    assert code == 2
    code, out, _ = run_cli(browser, 'replies', '99')
    assert code == 2 and 'does not exist' in json.loads(out)['message']
