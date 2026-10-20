"""post and replies through the real CLI and a scripted Aside (fixtures: thread.json; P2 R2: next batches, hidden
replies, branches read from the reply's own page)."""
import json
import re
import stat
import time

import pytest

from tests.sns.x.scenes import ACCOUNT, known_tab, queries, query_result, rerun, run, state

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
    return run(browser, 'post', *args, env=env)


def test_the_post_in_full_its_parent_and_its_first_replies_with_handles(browser):
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    code, out, err = post(browser, 'https://x.com/author_a/status/101')
    assert code == 0, (out, err)
    head = out.splitlines()[0]
    assert head.startswith('x post · sort=top · 6 shown · stopped=limit_reached · requests=1')
    assert re.search(r'\[p1\] @author_a .* · parent', out)
    assert f'text[{len(LONG)} of {len(LONG)} chars shown]' in out  # the post itself in full
    assert '[r1] @replier_b' in out and '[r2] @author_a' in out and 'reply-to=r1' in out
    assert 'reply to a post not shown' in out  # 106 answers 105, which X skipped
    assert re.search(r'url: "https://x.com/replier_b/status/102"   author: "replier_b"   replies \d+', out)
    assert re.search(r'coverage: X hid some replies as probable spam or low quality; replies \d+ reads them', out)
    assert out.splitlines()[-1].startswith('more: ') and ' replies ' in out.splitlines()[-1]
    [query] = queries(browser)
    assert query['args']['name'] == 'TweetDetail'
    assert query['args']['variables']['focalTweetId'] == '101' and query['args']['variables']['rankingMode'] == 'Relevance'
    assert query['args']['variables']['referrer'] == 'tweet'


def test_more_reads_the_next_batch_of_direct_replies(browser):
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    browser.respond('x.state', state())
    nxt = {'data': {'threaded_conversation_with_injections_v2': {'instructions': [
        {'type': 'TimelineAddToModule', 'moduleEntryId': 'conversationthread-107', 'moduleItems': [item(tweet('107', B, '101'), 'conversationthread-107')]}]}}}
    browser.respond('x.query', query_result(nxt, headers=RATE))
    code, out, _ = rerun(browser, out.splitlines()[-1])
    assert code == 0, out
    assert '[r1] @replier_b' in out and 'post 107' in out
    last = queries(browser)[-1]
    assert last['args']['variables']['cursor'] == 'NEXTCUR' and last['args']['variables']['focalTweetId'] == '101'


def test_the_hidden_replies_handle_reads_them_by_their_cursor(browser):
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    number = re.search(r'replies (\d+) reads them', out).group(1)
    browser.respond('x.state', state())
    hidden = detail([module('120', tweet('120', B, '101', text='probably spam'))])
    browser.respond('x.query', query_result(hidden, headers=RATE))
    code, out, _ = run(browser, 'replies', number)
    assert code == 0, out
    assert 'probably spam' in out and 'coverage: these are replies X hid as probable spam or low quality' in out
    assert queries(browser)[-1]['args']['variables']['cursor'] == 'HIDDENCUR'


def test_a_replys_handle_reads_its_branch_from_its_own_page(browser):
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    number = re.search(r'status/102"   author: "replier_b"   replies (\d+)', out).group(1)
    browser.respond('x.state', state())
    own = detail([single(tweet('101', reply_to='100')), single(tweet('102', B, '101')),
                  module('130', tweet('130', A, '102', text='under the reply'))])
    browser.respond('x.query', query_result(own, headers=RATE))
    code, out, _ = run(browser, 'replies', number)
    assert code == 0, out
    assert 'under the reply' in out and 'post 101' not in out  # the parents of that page are not repeated
    query = queries(browser)[-1]
    assert query['args']['variables']['focalTweetId'] == '102' and 'cursor' not in query['args']['variables']


def test_recent_order(browser):
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    code, out, _ = post(browser, '101', '--sort', 'recent')
    assert code == 0 and 'sort=recent' in out.splitlines()[0]
    assert queries(browser)[0]['args']['variables']['rankingMode'] == 'Recency'


def test_limit_keeps_the_first_threads_whole(browser):
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    code, out, _ = post(browser, '101', '--limit', '1')
    assert code == 0 and 'post 103' in out and 'post 104' not in out


def test_a_deleted_post_is_unavailable(browser):
    tomb = {'__typename': 'TweetTombstone', 'tombstone': {'text': {'text': 'This post was deleted.'}}}
    gone = detail([{'entryId': 'tweet-101', 'content': {'itemContent': {'itemType': 'TimelineTweet',
                                                                        'tweet_results': {'result': tomb}}}}])
    known_tab(browser).respond('x.query', query_result(gone, headers=RATE))
    code, out, _ = post(browser, '101')
    assert code == 9 and json.loads(out)['error'] == 'unavailable'


def test_several_posts_in_one_request_without_replies(browser):
    batch = {'data': {'tweetResult': [{'result': tweet('201')}, {'result': {'__typename': 'TweetTombstone'}}]}}
    known_tab(browser).respond('x.query', query_result(batch, headers=RATE))
    code, out, _ = post(browser, '201', '202', '--json')
    envelope = json.loads(out)
    assert code == 0 and [r['id'] for r in envelope['results']] == ['201'] and envelope['unresolved'] == ['202']
    [query] = queries(browser)
    assert query['args']['name'] == 'TweetResultsByRestIds' and query['args']['variables']['tweetIds'] == ['201', '202']


def test_a_handle_read_as_another_x_account_is_a_changed_login_not_a_wrong_argument(browser):
    """The X account is compared outside the handle's context: exit 4 account_changed (it used to be exit 2)."""
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    browser.respond('x.state', state(user_id='1000000098'))
    code, out, _ = rerun(browser, out.splitlines()[-1])
    envelope = json.loads(out)
    assert code == 4 and envelope['error'] == 'login' and ACCOUNT in envelope['message'], out
    assert '1000000098' in envelope['message'] and 'without --after' in envelope['fix']
    assert len(queries(browser)) == 1  # nothing was requested as the wrong account


def test_a_handle_is_a_number(browser):
    code, out, _ = run(browser, 'replies', 'abc123')
    assert code == 2 and browser.calls() == []


def test_a_post_page_whose_post_cannot_be_read_is_a_shape_change(browser):
    broken = detail([{'entryId': 'tweet-101', 'content': {'itemContent': {'itemType': 'TimelineTweet',
                                                                          'tweet_results': {'result': {'__typename': 'Tweet'}}}}}])
    known_tab(browser).respond('x.query', query_result(broken, headers=RATE))
    code, out, _ = post(browser, '101')
    assert code == 6, out


def test_a_batch_of_unreadable_posts_is_a_shape_change(browser):
    batch = {'data': {'tweetResult': [{'result': {'__typename': 'Tweet'}}, {'result': {'__typename': 'Tweet'}}]}}
    known_tab(browser).respond('x.query', query_result(batch, headers=RATE))
    code, out, _ = post(browser, '201', '202')
    assert code == 6, out


def test_replies_that_cannot_be_read_are_reported_on_the_post_page(browser):
    name = 'conversationthread-110'
    broken = {'entryId': name, 'content': {'entryType': 'TimelineTimelineModule', 'items': [
        {'entryId': f'{name}-tweet-110', 'item': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {
            'result': {'__typename': 'Tweet', 'renamed': '110'}}}}}]}}
    page = detail([single(tweet('101', reply_to='100')), broken])
    known_tab(browser).respond('x.query', query_result(page, headers=RATE))
    code, out, _ = post(browser, '101')
    assert code == 0 and 'could not read' in out, out


def test_a_batch_names_what_it_could_not_read_apart_from_what_x_did_not_return(browser):
    batch = {'data': {'tweetResult': [{'result': tweet('201')}, {'result': {'__typename': 'Tweet'}}]}}
    known_tab(browser).respond('x.query', query_result(batch, headers=RATE))
    code, out, _ = post(browser, '201', '202')
    assert code == 0 and 'could not read' in out, out


def test_a_further_batch_of_replies_reports_the_replies_it_could_not_read(browser):
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    name = 'conversationthread-140'
    nxt = detail([module('141', tweet('141', B, '101')), {'entryId': name, 'content': {'entryType': 'TimelineTimelineModule', 'items': [
        {'entryId': f'{name}-tweet-140', 'item': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {
            'result': {'__typename': 'Tweet', 'renamed': '140'}}}}}]}}])
    browser.respond('x.state', state()).respond('x.query', query_result(nxt, headers=RATE))
    code, out, _ = rerun(browser, out.splitlines()[-1])
    assert code == 0 and 'post 141' in out and 'could not read' in out, out


def handle_of(line):
    """The number a printed more: line asks `replies` for."""
    return re.search(r' replies (\d+)', line).group(1)


def batch(*nodes, bottom=None, ident='107'):
    entries = [module(f'{ident}{i}', n) for i, n in enumerate(nodes)]
    return detail(entries + ([cursor('Bottom', bottom)] if bottom else []))


def test_a_replies_handle_belongs_to_the_replies_command_and_names_it_elsewhere(browser):
    """post saves its handles for `replies` (through the connection): another command refuses them naming it (exit 2), a
    handle of another command is refused by `replies` the same way."""
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    number = handle_of(out.splitlines()[-1])
    browser.respond('x.state', state())
    code, text, _ = run(browser, 'feed', '--after', number)
    assert code == 2 and 'x replies' in json.loads(text)['message'], text
    feed_page = {'data': {'home': {'home_timeline_urt': {'instructions': [{'type': 'TimelineAddEntries', 'entries': [
        single(tweet('300')), cursor('Bottom', 'FEEDCUR')]}]}}}}
    browser.respond('x.state', state()).respond('x.query', query_result(feed_page, headers=RATE))
    code, text, _ = run(browser, 'feed')
    feed_handle = re.search(r'--after (\d+)', text.splitlines()[-1]).group(1)
    browser.respond('x.state', state())
    code, text, _ = run(browser, 'replies', feed_handle)
    assert code == 2 and 'x feed' in json.loads(text)['message'], text


def test_a_replies_handle_of_the_other_command_word_is_a_number_checked_before_the_browser(browser):
    code, out, _ = run(browser, 'replies', '../x')
    assert code == 2 and browser.calls() == [] and 'number' in json.loads(out)['message']


def test_replies_stopped_by_the_time_limit_after_records_resumes_from_its_own_handle(browser):
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    number = handle_of(out.splitlines()[-1])
    browser.respond('x.state', state())
    # the batch takes 3 of the 6 seconds: the next request no longer fits (pacing and a call's least time) -> time limit
    browser.respond('x.query', {'__sleep': 3, **query_result(batch(tweet('107', B, '101'), bottom='CUR3'), headers=RATE)})
    code, out, _ = run(browser, 'replies', number, '--limit', '40', env={'SNS_DEADLINE_SECONDS': '6'})
    assert code == 0, out
    assert 'stopped=time_limit' in out.splitlines()[0] and 'post 107' in out
    last = out.splitlines()[-1]
    assert last.startswith('more: ') and ' replies ' in last and handle_of(last) != number  # its own, newer handle
    browser.respond('x.state', state())
    browser.respond('x.query', query_result(batch(tweet('109', B, '101'), ident='109'), headers=RATE))
    code, out, _ = rerun(browser, last)
    assert code == 0 and 'post 109' in out and 'more:' not in out, out
    assert queries(browser)[-1]['args']['variables']['cursor'] == 'CUR3'


def test_replies_out_collects_the_batches_and_resumes_after_a_time_limit_stop(browser, tmp_path):
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    number = handle_of(out.splitlines()[-1])
    saved = tmp_path / 'replies.ndjson'
    browser.respond('x.state', state())
    # the batch takes 3 of the 6 seconds: the next request no longer fits (pacing and a call's least time) -> time limit
    browser.respond('x.query', {'__sleep': 3, **query_result(batch(tweet('107', B, '101'), bottom='CUR3'), headers=RATE)})
    code, out, _ = run(browser, 'replies', number, '--out', str(saved), env={'SNS_DEADLINE_SECONDS': '6'})
    assert code == 0 and '1 saved to' in out and 'stopped=time_limit' in out, out
    resume = next(part for part in out.split(' · ') if part.startswith('resume: '))
    browser.respond('x.state', state())
    browser.respond('x.query', query_result(batch(tweet('108', B, '101'), ident='108'), headers=RATE))
    code, out, _ = rerun(browser, resume)
    assert code == 0 and '2 saved to' in out and 'stopped=exhausted' in out, out
    records = [json.loads(line) for line in saved.read_text().splitlines()]
    assert [r['id'] for r in records if 'id' in r] == ['107', '108']
    assert all(r['role'] == 'reply' and r['parent_id'] == '101' for r in records if 'id' in r)  # flat records
    x_ops = [op for op in browser.ops() if op.startswith(('x.', 'load:x.', 'opener'))]
    code, out, _ = run(browser, 'replies', number, '--out', str(saved))
    assert code == 0 and 'already complete' in out
    assert [op for op in browser.ops() if op.startswith(('x.', 'load:x.', 'opener'))] == x_ops  # nothing read again


def test_replies_out_stopped_by_the_operations_limit_is_resumable_but_not_before_the_reset(browser, tmp_path):
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    number = handle_of(out.splitlines()[-1])
    saved = tmp_path / 'replies.ndjson'
    browser.respond('x.state', state())
    browser.respond('x.query', query_result(batch(tweet('107', B, '101'), bottom='CUR3'), headers=RATE))
    browser.respond('x.query', query_result('{"errors":[{"code":88}]}', status=429, headers={
        'x-rate-limit-limit': '300', 'x-rate-limit-remaining': '0', 'x-rate-limit-reset': str(int(time.time()) + 600)}))
    code, out, _ = run(browser, 'replies', number, '--out', str(saved))
    assert code == 0 and '1 saved to' in out and 'stopped=rate_limited' in out and 'resume: ' in out, out
    sent = len(queries(browser))
    browser.respond('x.state', state())
    code, out, _ = rerun(browser, next(part for part in out.split(' · ') if part.startswith('resume: ')))
    assert code == 0 and '1 saved to' in out and 'stopped=rate_limited' in out, out  # still inside X's window
    assert len(queries(browser)) == sent


# --- review findings: what a continuation may be built after, and what a branch continues from ------------------------

def read_first_post(browser):
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    _, out, _ = post(browser, '101')
    return out


STOPS = [pytest.param(403, '<!doctype html><html class="cf"></html>', 5, id='challenge'),
         pytest.param(401, '{"errors":[{"code":32}]}', 4, id='logout')]


@pytest.mark.parametrize('status, body, expected', STOPS)
def test_a_replies_read_stopped_by_a_block_or_a_logout_offers_no_next_handle(browser, status, body, expected):
    out = read_first_post(browser)
    number = re.search(r'replies (\d+) reads them', out).group(1)
    browser.respond('x.state', state()).respond('x.query', query_result(body, status=status))
    code, text, _ = run(browser, 'replies', number, '--json')
    envelope = json.loads(text)
    assert code == expected and 'next' not in envelope, text


def test_a_replies_read_of_a_deleted_post_is_exit_9_and_offers_no_next_handle(browser):
    out = read_first_post(browser)
    number = re.search(r'replies (\d+) reads them', out).group(1)
    gone = detail([{'entryId': 'tweet-101', 'content': {'itemContent': {'itemType': 'TimelineTweet', 'tweet_results': {
        'result': {'__typename': 'TweetTombstone'}}}}}])
    browser.respond('x.state', state()).respond('x.query', query_result(gone, headers=RATE))
    code, text, _ = run(browser, 'replies', number, '--json')
    assert code == 9 and 'next' not in json.loads(text), text


def test_a_branch_read_in_several_batches_continues_from_the_cursor_the_last_one_saved(browser):
    out = read_first_post(browser)
    number = re.search(r'status/102"   author: "replier_b"   replies (\d+)', out).group(1)
    first = detail([single(tweet('101', reply_to='100')), single(tweet('102', B, '101')),
                    module('130', tweet('130', A, '102', text='first batch')), cursor('Bottom', 'BRANCHCUR')])
    browser.respond('x.state', state()).respond('x.query', query_result(first, headers=RATE))
    code, out, _ = run(browser, 'replies', number)
    assert code == 0 and 'first batch' in out and out.splitlines()[-1].startswith('more: '), out
    second = detail([module('131', tweet('131', A, '102', text='second batch'))])
    browser.respond('x.state', state()).respond('x.query', query_result(second, headers=RATE))
    code, out, _ = rerun(browser, out.splitlines()[-1])
    assert code == 0 and 'second batch' in out, out
    last = queries(browser)[-1]['args']['variables']
    assert last['focalTweetId'] == '102' and last['cursor'] == 'BRANCHCUR'


def test_a_post_whose_handles_cannot_be_saved_keeps_what_it_read_as_a_partial_result(browser, data_dir):
    known_tab(browser).respond('x.query', query_result(FIRST, headers=RATE))
    handles = data_dir / 'handles'
    handles.mkdir(parents=True)
    handles.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        code, out, _ = post(browser, '101')
    finally:
        handles.chmod(0o700)
    assert code == 8 and 'the parent' in out and '[r1] @replier_b' in out, out
    assert not [line for line in out.splitlines() if line.startswith('more: ')]
