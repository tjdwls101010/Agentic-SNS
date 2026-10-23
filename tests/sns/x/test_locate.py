"""web.locate: which links X claims and the command that opens them (pure text, no request), so the shared pipeline can
name the right platform for a link given to another one; and what `x` does with a link of its own or a foreign one."""
import json

import pytest

from sns.x import web
from tests.sns.x.scenes import known_tab, queries, query_result, run

POST = 'https://x.com/example_user/status/1850000000000000001'
AUTHOR = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'example_user', 'name': 'E'}}


@pytest.mark.parametrize('url, command', [
    (POST, 'post'),
    ('https://twitter.com/Example_User/status/1850000000000000001?s=46', 'post'),
    ('https://mobile.twitter.com/example_user/status/1850000000000000001/photo/1', 'post'),
    ('x.com/i/web/status/1850000000000000004', 'post'),
    ('https://x.com/i/lists/1500000000000000001', 'list'),
    ('https://x.com/i/communities/1600000000000000001', 'community'),
    ('https://x.com/i/spaces/1AbCdEfGhIjKl', 'about'),
    ('https://x.com/example_user', 'profile'),
    ('https://www.x.com/example_user/with_replies', 'profile'),
    ('twitter.com/example_user', 'profile'),
], ids=lambda value: value[-24:])
def test_an_x_link_is_claimed_with_the_command_that_opens_it(url, command):
    assert web.locate(url) == (command, url)


@pytest.mark.parametrize('url', [
    'https://example.com/example_user/status/1850000000000000001',   # another site
    'https://threads.com/@example_user/post/ABC',
    'https://www.reddit.com/r/python/comments/abc/title/',
    'https://x.com.evil.example/example_user',                        # a lookalike host
    'https://x.com/home', 'https://x.com/i/flow/login', 'https://x.com/search?q=a',   # X's own pages, no reader
    '@example_user', 'example_user', '1850000000000000001', '', '   ', 'https://[broken',
])
def test_what_is_not_an_x_reading_target_is_not_claimed(url):
    assert web.locate(url) is None


def test_an_x_link_given_to_post_is_accepted(browser):
    focal = {'__typename': 'Tweet', 'rest_id': '1850000000000000001', 'core': {'user_results': {'result': AUTHOR}},
             'legacy': {'full_text': 'the post', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026'}}
    known_tab(browser).respond('x.query', query_result({'data': {'threaded_conversation_with_injections_v2': {
        'instructions': [{'type': 'TimelineAddEntries', 'entries': [{
            'entryId': 'tweet-1850000000000000001', 'content': {'itemContent': {
                'itemType': 'TimelineTweet', 'tweet_results': {'result': focal}}}}]}]}}}))
    code, out, _ = run(browser, 'post', POST, '--json')
    assert code == 0, out
    [call] = queries(browser)
    assert call['args']['name'] == 'TweetDetail' and call['args']['variables']['focalTweetId'] == '1850000000000000001'


def test_a_link_to_another_site_is_Xs_own_argument_error_not_a_request(browser):
    code, out, _ = run(browser, 'post', 'https://example.com/example_user/status/1850000000000000001')
    envelope = json.loads(out)
    assert code == 2 and envelope['error'] == 'argument' and 'x.com or twitter.com' in envelope['message']
    assert browser.calls() == []
