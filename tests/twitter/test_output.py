"""What the model reads: dense text rendering and the schema of emitted records."""
from .fake_data import tweet, user, wrap
from .helpers import invoke, script, text


def test_text_expands_links_drops_media_links_and_marks_line_breaks(fake_env):
    node = tweet('200')
    node['legacy'].update(full_text='One  https://t.co/link\nTwo https://t.co/photo', entities={
        'urls': [{'url': 'https://t.co/link', 'expanded_url': 'https://example.com/article'}],
        'media': [{'url': 'https://t.co/photo'}]})
    script(fake_env, {'op': 'HomeTimeline', 'body': wrap('HomeTimeline', [{'type': 'TimelineAddEntries', 'entries': [
        {'entryId': 'tweet-200', 'content': {'itemContent': {'tweet_results': {'result': node}}}}]}])})
    code, output = text(['home', '--limit', '1'], fake_env)
    assert code == 0 and '"One https://example.com/article ⏎ Two"' in output


def test_large_counts_are_abbreviated(fake_env):
    node = user()
    node['relationship_counts'] = {'followers': 1200000, 'following': 40}
    script(fake_env, {'op': 'UserByScreenName', 'body': wrap('UserByScreenName', node)})
    code, output = text(['about', '@example'], fake_env)
    assert code == 0 and 'followers 1.2M' in output


def test_focal_is_full_quote_is_a_next_hop_and_partial_failure_is_reported(fake_env):
    focal = tweet('1')
    focal['legacy'].update(full_text='A long focal body', quoted_status_id_str='2', reply_count=9, entities={})
    focal = {'__typename': 'TweetWithVisibilityResults', 'tweet': focal,
             'limitedActionResults': {'limited_actions': [{'action': 'Reply'}]}}
    more = [{'type': 'TimelineAddToModule', 'moduleEntryId': 'conversationthread-' + m, 'moduleItems': [
        {'entryId': 'more-' + m, 'item': {'itemContent': {'cursorType': 'ShowMoreThreads', 'value': m}}}]} for m in 'ab']
    entries = [{'entryId': 'tweet-1', 'content': {'itemContent': {'tweet_results': {'result': focal}}}},
               {'entryId': 'cursor-bottom', 'content': {'cursorType': 'Bottom', 'value': 'next'}}]
    script(fake_env, {'op': 'TweetDetail', 'body': wrap('TweetDetail', [{'type': 'TimelineAddEntries', 'entries': entries},
                                                                         *more])},
           {'op': 'TweetDetail', 'status': 429, 'body': {}, 'ratelimit': {'limit': 150, 'remaining': 0, 'reset': 1}})
    code, output = text(['post', '1', '--chars', '3', '--limit', '5'], fake_env)
    assert code == 8
    assert 'text[full]: "A long focal body"' in output
    assert 'https://x.com/i/web/status/2 (open with post)' in output and '[limited: replies]' in output
    assert '0 direct shown of 9 reported' in output and 'hidden branches 2' in output
    assert output.rstrip('\n').splitlines()[-1].startswith('stopped: rate_limit · Wait until')


def test_schema_describes_exactly_the_emitted_post_fields(fake_env):
    code, schema = invoke(['schema'], fake_env)
    code, doc = invoke(['home', '--limit', '1'], fake_env)
    post = schema['results'][0]['Tweet']
    assert set(post['properties']) == set(doc['results'][0])
    assert 'reposter' in post['properties']['author']['description']


def test_schema_types_are_machine_readable_with_nullable_and_nested_records(fake_env):
    code, doc = invoke(['schema'], fake_env)
    post = doc['schema']['$defs']['Tweet']['properties']
    assert post['text']['type'] == 'string'
    assert post['author']['anyOf'] == [{'$ref': '#/$defs/User'}, {'type': 'null'}]
    assert post['media']['items'] == {'$ref': '#/$defs/Media'}
