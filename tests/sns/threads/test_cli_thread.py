"""post and replies through the real CLI and a scripted Aside (fixtures/records_thread.json for the post page)."""
import copy
import json

from tests.sns.threads.data import fixture
from tests.sns.threads.scenes import known_tab, query_result, rerun, run, state

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


def scripted_post(browser, **kwargs):
    known_tab(browser)
    for body in post_page(**kwargs):
        browser.respond('threads.query', query_result(body))
    return browser


def test_post_reads_three_queries_by_the_id_its_shortcode_encodes(browser):
    scripted_post(browser)
    code, out, _ = run(browser, 'post', URL, '--json')
    result = json.loads(out)
    assert code == 0, result
    calls = [c['args'] for c in browser.calls() if c['op'] == 'threads.query']
    assert [c['name'] for c in calls] == ['BarcelonaPostPageTargetQuery', 'BarcelonaPostPageUpwardQuery',
                                         'BarcelonaPostPageDownwardQuery']
    assert {c['variables']['postID'] for c in calls} == {CASE['post_id']}
    assert calls[2]['variables']['sortOrder'] == 'TOP'
    assert [r['role'] for r in result['results']][:2] == ['parent', 'post']
    assert result['replies'] == CASE['expected']['coverage']
    assert result['request_count'] == 3


def test_post_text_shows_the_post_in_full_and_the_reply_tree(browser):
    scripted_post(browser)
    code, out, _ = run(browser, 'post', URL, '--chars', '3')
    assert code == 0
    lines = out.splitlines()
    assert lines[0].startswith('threads post · sort=top · 8 shown · stopped=limit_reached · requests=3')
    assert lines[1].startswith('replies: 2 of 5 direct received · ≈1 never received (estimate)')
    assert 'text[8 of 8 chars shown]: "The post"' in out  # the opened post is never clipped
    assert 'text[3 of 10 chars shown]: "The…"' in out      # its parent is
    assert any('reply-to=r1' in line and line.startswith('  [r2]') for line in lines)
    assert any('continuation of r4' in line for line in lines)
    assert 'more: ' in out and out.count('   replies ') == 1


def test_more_reads_the_next_batch_of_direct_replies(browser):
    scripted_post(browser)
    code, out, _ = run(browser, 'post', URL)
    more = next(line for line in out.splitlines() if line.startswith('more: '))
    batch = {'data': {'media': {'text_post_app_info': {'direct_replies': {'edges': [
        {'node': {'posts': {'edges': [{'node': {'pk': '3000000000000000271', 'code': 'Cr271', 'caption': {'text': 'late'},
                                                'user': THREAD['users']['C'],
                                                'text_post_app_info': {'is_reply': True}}}]}}}],
        'page_info': {'has_next_page': False, 'end_cursor': None}}}}}}
    browser.respond('threads.state', state()).respond('threads.query', query_result(batch))
    code, out, _ = rerun(browser, more, '--json')
    result = json.loads(out)
    assert code == 0, result
    call = [c['args'] for c in browser.calls() if c['op'] == 'threads.query'][-1]
    assert call['name'] == 'BarcelonaPostPageDirectRepliesRefetchQuery'
    assert call['variables']['after'] == 'REPCUR1' and call['variables']['postID'] == CASE['post_id']
    assert [r['id'] for r in result['results']] == ['3000000000000000271']
    assert 'next' not in result and result['coverage'][0].startswith('Threads reports 5 direct replies')


def branch_batch(reply_id, pk, text, cursor):
    """The replies response about one reply, as its own post page returns it."""
    return {'data': {'media': {'pk': reply_id, 'text_post_app_info': {'direct_replies': {'edges': [
        {'node': {'posts': {'edges': [{'node': {'pk': pk, 'code': 'Cr' + pk[-3:], 'caption': {'text': text},
                                                'user': THREAD['users']['A'],
                                                'text_post_app_info': {'is_reply': True, 'reply_level': 2}}}]}}}],
        'page_info': {'has_next_page': bool(cursor), 'end_cursor': cursor}}}}}}


def test_a_branch_handle_reads_all_the_replies_under_one_reply_from_its_own_page(browser):
    scripted_post(browser)
    code, out, _ = run(browser, 'post', URL, '--json')
    reply = next(r for r in json.loads(out)['results'] if r.get('replies_handle'))
    browser.respond('threads.state', state()).respond('threads.query', query_result(branch_batch(reply['id'], '3000000000000000281',
                                                                               'deeper', 'BR2')))
    code, out, _ = run(browser, 'replies', str(reply['replies_handle']), '--json')
    result = json.loads(out)
    assert code == 0, result
    call = [c['args'] for c in browser.calls() if c['op'] == 'threads.query'][-1]
    # the reply's own page lists every reply under it, where the thread view's inline expansion shows a few
    assert call['name'] == 'BarcelonaPostPageDownwardQuery'
    assert call['variables']['postID'] == reply['id'] and call['variables']['sortOrder'] == 'TOP'
    under = result['results'][0]
    assert under['relation'] == {'kind': 'reply', 'to': reply['id']} and under['depth'] == 1
    assert result['thread']['under'] == reply['id'] and result.get('next')
    browser.respond('threads.state', state()).respond('threads.query', query_result(branch_batch(reply['id'], '3000000000000000282',
                                                                               'deepest', None)))
    code, out, _ = rerun(browser, 'more: ' + result['next'], '--json')
    result = json.loads(out)
    assert code == 0, result
    call = [c['args'] for c in browser.calls() if c['op'] == 'threads.query'][-1]
    assert call['name'] == 'BarcelonaPostPageDirectRepliesRefetchQuery'
    assert call['variables']['postID'] == reply['id'] and call['variables']['after'] == 'BR2'
    assert [r['id'] for r in result['results']] == ['3000000000000000282'] and 'next' not in result


def test_recent_sort_asks_threads_for_newest_first(browser):
    scripted_post(browser, next_cursor=None)
    code, out, _ = run(browser, 'post', URL, '--sort', 'recent', '--json')
    assert code == 0
    assert [c['args'] for c in browser.calls() if c['op'] == 'threads.query'][2]['variables']['sortOrder'] == 'RECENT'
    assert 'next' not in json.loads(out)


def test_a_deleted_post_is_unavailable(browser):
    known_tab(browser).respond('threads.query', query_result({'data': {'media': None}}))
    code, out, _ = run(browser, 'post', URL)
    assert code == 9 and json.loads(out)['error'] == 'unavailable'


def test_a_tombstone_post_is_unavailable(browser):
    known_tab(browser)
    pages = post_page()
    pages[0]['data']['media']['is_post_unavailable'] = True
    for body in pages:
        browser.respond('threads.query', query_result(body))
    code, out, _ = run(browser, 'post', URL)
    assert code == 9


def test_a_bad_or_foreign_handle_is_an_argument_error(browser):
    known_tab(browser)
    code, out, _ = run(browser, 'replies', 'x7')
    assert code == 2
    code, out, _ = run(browser, 'replies', '99')
    assert code == 2 and 'does not exist' in json.loads(out)['message']


def test_a_null_reply_in_a_batch_is_marked_unavailable_not_a_crash(browser):
    scripted_post(browser)
    code, out, _ = run(browser, 'post', URL, '--json')
    reply = next(r for r in json.loads(out)['results'] if r.get('replies_handle'))
    batch = branch_batch(reply['id'], '3000000000000000283', 'readable', None)
    edges = batch['data']['media']['text_post_app_info']['direct_replies']['edges']
    edges.insert(0, {'node': {'posts': {'edges': [{'node': None}]}}})
    browser.respond('threads.state', state()).respond('threads.query', query_result(batch))
    code, out, _ = run(browser, 'replies', str(reply['replies_handle']), '--json')
    result = json.loads(out)
    assert code == 0, result
    assert [r.get('unavailable') for r in result['results']] == [True, False]
    assert result['results'][1]['id'] == '3000000000000000283'


def test_replies_collect_into_a_file_batch_by_batch_and_the_file_completes(browser, tmp_path):
    scripted_post(browser)
    code, out, _ = run(browser, 'post', URL)
    more = next(line for line in out.splitlines() if line.startswith('more: '))
    batch = {'data': {'media': {'text_post_app_info': {'direct_replies': {'edges': [
        {'node': {'posts': {'edges': [{'node': {'pk': '3000000000000000271', 'code': 'Cr271', 'caption': {'text': 'late'},
                                                'user': THREAD['users']['C'], 'text_post_app_info': {'is_reply': True}}}]}}}],
        'page_info': {'has_next_page': False, 'end_cursor': None}}}}}}
    handle = more.split(' replies ')[1].split()[0]
    target = tmp_path / 'replies.ndjson'
    browser.respond('threads.state', state()).respond('threads.query', query_result(batch))
    code, text, _ = run(browser, 'replies', handle, '--out', str(target))
    assert code == 0 and '1 saved' in text and 'stopped=exhausted' in text, text
    saved = [json.loads(line) for line in target.read_text().splitlines()]
    assert [r['id'] for r in saved if r.get('kind') == 'post'] == ['3000000000000000271']
    queries_before = browser.ops().count('threads.query')
    code, text, _ = run(browser, 'replies', handle, '--out', str(target))
    assert code == 0 and 'already complete' in text and browser.ops().count('threads.query') == queries_before


def test_a_handle_of_another_command_is_refused_naming_where_it_belongs(browser):
    """A handle belongs to the command that saved it: a feed handle given to replies is refused, nothing is requested."""
    from tests.sns.threads.scenes import feed_body, post
    known_tab(browser).respond('threads.query', query_result(feed_body([[post('A', '2026-10-08T03:00:00Z')],
                                                                         [post('B', '2026-10-07T03:00:00Z')]], True, 'C1')))
    code, out, _ = run(browser, 'feed', '--limit', '1')
    handle = next(line for line in out.splitlines() if line.startswith('more: ')).split('--after ')[1].split()[0]
    queries_before = browser.ops().count('threads.query')
    browser.respond('threads.state', state())
    code, out, _ = run(browser, 'replies', handle)
    assert code == 2 and 'feed' in json.loads(out)['message'], out
    assert browser.ops().count('threads.query') == queries_before
