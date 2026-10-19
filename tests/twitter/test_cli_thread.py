"""post and replies through the real CLI and a scripted Aside (fixtures: thread.json; P2 R2: next batches, hidden
replies, branches read from the reply's own page)."""
import json
import re
import time

from conftest import ACCOUNT, command_of, known_tab, query_result, run_cli, state

A = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'author_a', 'name': 'A'}}
B = {'__typename': 'User', 'rest_id': '1000000002', 'core': {'screen_name': 'replier_b', 'name': 'B'}}
RATE = {'x-rate-limit-limit': '300', 'x-rate-limit-remaining': '299', 'x-rate-limit-reset': str(int(time.time()) + 900)}
LONG = 'word ' * 120


def tweet(ident, user=A, reply_to=None, text=None, **legacy):
    body = {'full_text': text or f'post {ident}', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026', **legacy}
    if reply_to:
        body['in_reply_to_status_id_str'] = reply_to
    return {'__typename': 'Tweet', 'rest_id': ident, 'core': {'user_results': {'result': user}}, 'legacy': body}


def item(node, module=None):
    entry_id = f'{module}-tweet-{node["rest_id"]}' if module else f'tweet-{node["rest_id"]}'
    return {'entryId': entry_id, 'item': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {'result': node}}}}


def detail(entries):
    return {'data': {'threaded_conversation_with_injections_v2': {'instructions': [
        {'type': 'TimelineAddEntries', 'entries': entries}]}}}


def single(node):
    return {'entryId': f'tweet-{node["rest_id"]}', 'content': {'itemContent': {'itemType': 'TimelineTweet',
                                                                              'tweet_results': {'result': node}}}}


def module(ident, *nodes):
    name = f'conversationthread-{ident}'
    return {'entryId': name, 'content': {'entryType': 'TimelineTimelineModule', 'items': [item(n, name) for n in nodes]}}


def cursor(kind, value):
    return {'entryId': f'cursor-{kind.lower()}-1', 'content': {'cursorType': kind, 'value': value}}


FIRST = detail([single(tweet('100', text='the parent')),
                single(tweet('101', reply_to='100', text=LONG, reply_count=40)),
                module('102', tweet('102', B, '101', reply_count=5), tweet('103', A, '102')),
                module('104', tweet('104', B, '101'), tweet('106', B, '105')),
                cursor('ShowMoreThreads', 'HIDDENCUR'), cursor('Bottom', 'NEXTCUR')])


def post(browser, *args, env=None):
    return run_cli(browser, 'post', *args, env=env)


def test_the_post_in_full_its_parent_and_its_first_replies_with_handles(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(FIRST, headers=RATE))
    code, out, err = post(browser, 'https://x.com/author_a/status/101')
    assert code == 0, (out, err)
    head = out.splitlines()[0]
    assert head.startswith('post · sort=top · 6 shown · stopped=limit_reached · requests=1/25')
    assert re.search(r'\[p1\] @author_a .* · parent', out)
    assert f'text[{len(LONG)} of {len(LONG)} chars shown]' in out  # the post itself in full
    assert '[r1] @replier_b' in out and '[r2] @author_a' in out and 'reply-to=r1' in out
    assert 'reply to a post not shown' in out  # 106 answers 105, which X skipped
    assert re.search(r'url: "https://x.com/replier_b/status/102"   author: "replier_b"   replies \d+', out)
    assert re.search(r'coverage: X hid some replies as probable spam or low quality; replies \d+ reads them', out)
    assert out.splitlines()[-1].startswith('more: ') and ' replies ' in out.splitlines()[-1]
    [query] = [c for c in browser.calls() if c['op'] == 'query']
    assert query['args']['name'] == 'TweetDetail'
    assert query['args']['variables']['focalTweetId'] == '101' and query['args']['variables']['rankingMode'] == 'Relevance'
    assert query['args']['variables']['referrer'] == 'tweet'


def test_more_reads_the_next_batch_of_direct_replies(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    more = command_of(out.splitlines()[-1])
    browser.respond('state', state())
    nxt = {'data': {'threaded_conversation_with_injections_v2': {'instructions': [
        {'type': 'TimelineAddToModule', 'moduleEntryId': 'conversationthread-107', 'moduleItems': [item(tweet('107', B, '101'), 'conversationthread-107')]}]}}}
    browser.respond('query', query_result(nxt, headers=RATE))
    code, out, _ = run_cli(browser, *more)
    assert code == 0, out
    assert '[r1] @replier_b' in out and 'post 107' in out
    last = [c for c in browser.calls() if c['op'] == 'query'][-1]
    assert last['args']['variables']['cursor'] == 'NEXTCUR' and last['args']['variables']['focalTweetId'] == '101'


def test_the_hidden_replies_handle_reads_them_by_their_cursor(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    number = re.search(r'replies (\d+) reads them', out).group(1)
    browser.respond('state', state())
    hidden = detail([module('120', tweet('120', B, '101', text='probably spam'))])
    browser.respond('query', query_result(hidden, headers=RATE))
    code, out, _ = run_cli(browser, 'replies', number)
    assert code == 0, out
    assert 'probably spam' in out and 'coverage: these are replies X hid as probable spam or low quality' in out
    assert [c for c in browser.calls() if c['op'] == 'query'][-1]['args']['variables']['cursor'] == 'HIDDENCUR'


def test_a_replys_handle_reads_its_branch_from_its_own_page(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    number = re.search(r'status/102"   author: "replier_b"   replies (\d+)', out).group(1)
    browser.respond('state', state())
    own = detail([single(tweet('101', reply_to='100')), single(tweet('102', B, '101')),
                  module('130', tweet('130', A, '102', text='under the reply'))])
    browser.respond('query', query_result(own, headers=RATE))
    code, out, _ = run_cli(browser, 'replies', number)
    assert code == 0, out
    assert 'under the reply' in out and 'post 101' not in out  # the parents of that page are not repeated
    query = [c for c in browser.calls() if c['op'] == 'query'][-1]
    assert query['args']['variables']['focalTweetId'] == '102' and 'cursor' not in query['args']['variables']


def test_recent_order(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(FIRST, headers=RATE))
    code, out, _ = post(browser, '101', '--sort', 'recent')
    assert code == 0 and 'sort=recent' in out.splitlines()[0]
    assert [c for c in browser.calls() if c['op'] == 'query'][0]['args']['variables']['rankingMode'] == 'Recency'


def test_limit_keeps_the_first_threads_whole(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(FIRST, headers=RATE))
    code, out, _ = post(browser, '101', '--limit', '1')
    assert code == 0 and 'post 103' in out and 'post 104' not in out


def test_a_deleted_post_is_unavailable(browser, data_dir):
    tomb = {'__typename': 'TweetTombstone', 'tombstone': {'text': {'text': 'This post was deleted.'}}}
    gone = detail([{'entryId': 'tweet-101', 'content': {'itemContent': {'itemType': 'TimelineTweet',
                                                                        'tweet_results': {'result': tomb}}}}])
    known_tab(browser, data_dir).respond('query', query_result(gone, headers=RATE))
    code, out, _ = post(browser, '101')
    assert code == 9 and json.loads(out)['error'] == 'unavailable'


def test_several_posts_in_one_request_without_replies(browser, data_dir):
    batch = {'data': {'tweetResult': [{'result': tweet('201')}, {'result': {'__typename': 'TweetTombstone'}}]}}
    known_tab(browser, data_dir).respond('query', query_result(batch, headers=RATE))
    code, out, _ = post(browser, '201', '202', '--json')
    envelope = json.loads(out)
    assert code == 0 and [r['id'] for r in envelope['results']] == ['201'] and envelope['unresolved'] == ['202']
    [query] = [c for c in browser.calls() if c['op'] == 'query']
    assert query['args']['name'] == 'TweetResultsByRestIds' and query['args']['variables']['tweetIds'] == ['201', '202']


def test_a_handle_from_another_x_account_is_refused(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    more = command_of(out.splitlines()[-1])
    browser.respond('state', state(user_id='1000000098'))
    code, out, _ = run_cli(browser, *more)
    assert code == 2 and 'another' in json.loads(out)['message']
    assert ACCOUNT != '1000000098'


def test_a_handle_is_a_number(browser, data_dir):
    code, out, _ = run_cli(browser, 'replies', 'abc123')
    assert code == 2 and browser.calls() == []


def test_a_post_page_whose_post_cannot_be_read_is_a_shape_change(browser, data_dir):
    broken = detail([{'entryId': 'tweet-101', 'content': {'itemContent': {'itemType': 'TimelineTweet',
                                                                          'tweet_results': {'result': {'__typename': 'Tweet'}}}}}])
    known_tab(browser, data_dir).respond('query', query_result(broken, headers=RATE))
    code, out, _ = post(browser, '101')
    assert code == 6, out


def test_a_batch_of_unreadable_posts_is_a_shape_change(browser, data_dir):
    batch = {'data': {'tweetResult': [{'result': {'__typename': 'Tweet'}}, {'result': {'__typename': 'Tweet'}}]}}
    known_tab(browser, data_dir).respond('query', query_result(batch, headers=RATE))
    code, out, _ = post(browser, '201', '202')
    assert code == 6, out


def test_replies_that_cannot_be_read_are_reported_on_the_post_page(browser, data_dir):
    name = 'conversationthread-110'
    broken = {'entryId': name, 'content': {'entryType': 'TimelineTimelineModule', 'items': [
        {'entryId': f'{name}-tweet-110', 'item': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {
            'result': {'__typename': 'Tweet', 'renamed': '110'}}}}}]}}
    page = detail([single(tweet('101', reply_to='100')), broken])
    known_tab(browser, data_dir).respond('query', query_result(page, headers=RATE))
    code, out, _ = post(browser, '101')
    assert code == 0 and 'could not read' in out, out


def test_a_batch_names_what_it_could_not_read_apart_from_what_x_did_not_return(browser, data_dir):
    batch = {'data': {'tweetResult': [{'result': tweet('201')}, {'result': {'__typename': 'Tweet'}}]}}
    known_tab(browser, data_dir).respond('query', query_result(batch, headers=RATE))
    code, out, _ = post(browser, '201', '202')
    assert code == 0 and 'could not read' in out, out


def test_a_further_batch_of_replies_reports_the_replies_it_could_not_read(browser, data_dir):
    known_tab(browser, data_dir).respond('query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    more = command_of(out.splitlines()[-1])
    name = 'conversationthread-140'
    nxt = detail([module('141', tweet('141', B, '101')), {'entryId': name, 'content': {'entryType': 'TimelineTimelineModule', 'items': [
        {'entryId': f'{name}-tweet-140', 'item': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {
            'result': {'__typename': 'Tweet', 'renamed': '140'}}}}}]}}])
    browser.respond('state', state()).respond('query', query_result(nxt, headers=RATE))
    code, out, _ = run_cli(browser, *more)
    assert code == 0 and 'post 141' in out and 'could not read' in out, out
