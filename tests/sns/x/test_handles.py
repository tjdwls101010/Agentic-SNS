"""The numbers X's commands print (`--after N`, `replies N`) end to end through the real CLI and a scripted Aside. The
handle store itself — the counter that starts at 1000 and never goes back, expiry, older versions, malformed numbers,
0600/0700 files, pruning — is the core's: tests/sns/core/test_handles.py (test_the_first_handle_is_1000_and_numbers_only_
grow, test_a_handle_gives_back_its_state_and_the_account_it_was_read_with, test_a_handle_of_another_platform_or_command_
names_where_it_belongs, test_an_expired_missing_or_older_handle_is_an_argument_error, test_saving_prunes_handles_past_
their_ttl_but_keeps_the_counter, test_handle_files_are_private). What stays here is what is X's: which context a handle
of X is bound to (command, target, the tab/feed/sort, the window), the X account it was read as (a changed login is exit
4), the Aside account, and the handles one `post` saves for `replies`."""
import json
import re
import time

import pytest

from tests.sns.x.scenes import ACCOUNT, known_tab, opening, queries, query_result, rerun, run, state

RATE = {'x-rate-limit-limit': '500', 'x-rate-limit-remaining': '499', 'x-rate-limit-reset': str(int(time.time()) + 900)}
AUTHOR = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'author_a', 'name': 'A'}}


def tweet(ident, parent=None, **legacy):
    body = {'full_text': f'post {ident}', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026', **legacy}
    if parent:
        body['in_reply_to_status_id_str'] = parent
    return {'__typename': 'Tweet', 'rest_id': ident, 'core': {'user_results': {'result': AUTHOR}}, 'legacy': body}


def entry(node):
    return {'entryId': f'tweet-{node["rest_id"]}', 'content': {'itemContent': {
        'itemType': 'TimelineTweet', 'tweet_results': {'result': node}}}}


def cursor(kind, value):
    return {'entryId': f'cursor-{kind.lower()}-1', 'content': {'cursorType': kind, 'value': value}}


def feed_page(ident, bottom='CUR1'):
    entries = [entry(tweet(ident))] + ([cursor('Bottom', bottom)] if bottom else [])
    return query_result({'data': {'home': {'home_timeline_urt': {'instructions': [
        {'type': 'TimelineAddEntries', 'entries': entries}]}}}}, headers=RATE)


def conversation(*extra):
    """A post page: the post 101 itself, one reply thread with a reply of its own to open, the hidden and next cursors."""
    thread = {'entryId': 'conversationthread-102', 'content': {'entryType': 'TimelineTimelineModule', 'items': [
        {'entryId': 'conversationthread-102-tweet-102', 'item': {'itemContent': {
            'itemType': 'TimelineTweet', 'tweet_results': {'result': tweet('102', '101', reply_count=4)}}}}]}}
    entries = [entry(tweet('101')), thread, cursor('ShowMoreThreads', 'HIDDENCUR'), cursor('Bottom', 'NEXTCUR'), *extra]
    return query_result({'data': {'threaded_conversation_with_injections_v2': {'instructions': [
        {'type': 'TimelineAddEntries', 'entries': entries}]}}}, headers=RATE)


def feed_handle(browser, *args):
    """Read one feed page and the number its more: line prints."""
    browser.respond('x.query', feed_page('1850000000000000001'))
    code, out, _ = run(browser, 'feed', '--limit', '1', *args)
    assert code == 0, out
    return re.search(r'--after (\d+)', out.splitlines()[-1]).group(1), out


def test_one_post_read_saves_a_handle_for_each_batch_and_branch_and_the_numbers_only_grow(browser):
    """post saves several handles while it reads (the next direct replies, the replies X hid, the branch of a reply)
    through the connection; all belong to `replies`, none is reused."""
    known_tab(browser).respond('x.query', conversation())
    code, out, _ = run(browser, 'post', '101')
    assert code == 0, out
    branch = int(re.search(r'status/102"   author: "author_a"   replies (\d+)', out).group(1))
    hidden = int(re.search(r'replies (\d+) reads them', out).group(1))
    following = int(re.search(r' replies (\d+)', out.splitlines()[-1]).group(1))
    assert len({branch, hidden, following}) == 3 and min(branch, hidden, following) >= 1000
    assert sorted([branch, hidden, following]) == [branch, hidden, following]  # saved in the order they were found


@pytest.mark.parametrize('command', [('feed',), ('profile', '@author_a'), ('search', 'ai'), ('replies',)])
def test_a_handle_that_is_not_a_number_is_exit_2_before_the_browser_is_touched(browser, command):
    """The previous twitter skill's handles were six letters or digits (abc123); they are not numbers here."""
    code, out, _ = run(browser, *command, *(['--after'] if command[0] != 'replies' else []), 'abc123')
    assert code == 2 and json.loads(out)['error'] == 'argument' and browser.calls() == []


def test_a_handle_is_bound_to_the_command_the_feed_the_target_and_the_window_it_continues(browser):
    known_tab(browser)
    number, out = feed_handle(browser, '--since', '2026-10-01')
    assert '--since 2026-10-01' in out.splitlines()[-1]  # the window travels in the more: line
    for args in (('feed', '--feed', 'following', '--since', '2026-10-01'),   # another feed
                 ('feed', '--since', '2026-10-02'),                          # another window
                 ('feed',),                                                  # no window
                 ('profile', '@author_a', '--since', '2026-10-01'),          # another command
                 ('replies', number)):                                       # another command's handle as a replies one
        browser.respond('x.state', state())
        code, out, _ = run(browser, *args, *(() if args[0] == 'replies' else ('--after', number)))
        envelope = json.loads(out)
        assert code == 2 and envelope['error'] == 'argument' and 'x feed' in envelope['message'], (args, out)
    assert queries(browser)[-1]['args']['name'] == 'HomeTimeline' and len(queries(browser)) == 1  # nothing was requested


def test_a_handle_read_as_one_x_account_is_a_changed_login_under_another_and_survives_it(browser):
    """account-changed-in-browser: exit 4 (not 2, as the account is no part of the handle's query), the handle is not
    deleted, and the same number works again once the browser shows the account it was read as."""
    known_tab(browser)
    number, out = feed_handle(browser)
    more = out.splitlines()[-1]
    browser.respond('x.state', state(user_id='1000000098'))
    code, text, _ = rerun(browser, more)
    envelope = json.loads(text)
    assert code == 4 and envelope['error'] == 'login' and ACCOUNT in envelope['message'], text
    browser.respond('x.state', state()).respond('x.query', feed_page('1850000000000000002', bottom=None))
    code, text, _ = rerun(browser, more)
    assert code == 0 and '1850000000000000002' in text, text


def test_a_handle_is_bound_to_the_aside_account_that_read_it(browser):
    known_tab(browser)
    number, out = feed_handle(browser)
    opening(browser)  # another Aside account has its own session: its tab is opened first
    code, text, _ = run(browser, 'feed', '--after', number, env={'SNS_ASIDE_ACCOUNT': 'u1'})
    assert code == 2 and 'another target, order or account' in json.loads(text)['message'], text


def test_a_number_nobody_saved_is_exit_2_naming_what_to_rerun(browser):
    known_tab(browser)
    code, out, _ = run(browser, 'feed', '--after', '99999')
    envelope = json.loads(out)
    assert code == 2 and envelope['error'] == 'argument' and 'without --after' in envelope['fix'], out
