"""What the model reads: dense text rendering and the schema of emitted records."""
import json
import re

from .fake_data import tweet, user, wrap
from .helpers import home, invoke, script, text


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
    assert output.rstrip('\n').splitlines()[-1].startswith('stopped: rate_limit: X operation rate limit reached. · fix: Wait until')


TOPICS = ['tweet', 'user', 'media', 'list', 'community', 'trend', 'envelope', 'export']
DYNAMIC = ['role', 'depth', 'module', 'index_in_module', 'community_url']


def test_schema_without_a_topic_is_a_short_table_of_contents(fake_env):
    code, output = text(['schema'], fake_env)
    assert code == 0 and len(output.encode()) <= 1024 and 'schema <topic>' in output
    assert all(re.search(rf'(?m)^{topic}\b', output) for topic in TOPICS)
    code, doc = invoke(['schema'], fake_env)
    assert sorted(doc['topics']) == sorted(TOPICS) and 'results' not in doc


def test_tweet_topic_lists_emitted_and_dynamic_fields_once(fake_env):
    code, doc = invoke(['schema', 'tweet'], fake_env)
    code, listing = invoke(['home', '--limit', '1'], fake_env)
    post = doc['$defs']['Tweet']['properties']
    assert set(post) == set(listing['results'][0]) | set(DYNAMIC)
    assert sorted(doc['$defs']) == ['Media', 'Tweet', 'User'] and doc['$ref'] == '#/$defs/Tweet'
    assert 'reposter' in post['author']['description'] and 'not zero' in post['like_count']['description']
    assert post['text']['type'] == 'string' and post['author']['anyOf'] == [{'$ref': '#/$defs/User'}, {'type': 'null'}]
    assert post['media']['items'] == {'$ref': '#/$defs/Media'}
    code, output = text(['schema', 'tweet'], fake_env)
    assert all(re.search(rf'(?m)^{field} ', output) for field in DYNAMIC)


def test_only_the_envelope_topic_explains_every_stop_reason_and_exit_code(fake_env):
    reasons = ['limit_reached', 'exhausted', 'window_reached', 'not_paginable', 'terminated', 'empty_pages', 'budget',
               'blocked', 'query_failure']
    code, envelope = text(['schema', 'envelope'], fake_env)
    assert all(reason in envelope for reason in reasons) and all(f'exit {code}' in envelope for code in (0, 2, 3, 4, 5, 6, 7, 8, 9))
    assert 'transaction_rejected' in envelope and 'next_handle' in envelope
    for topic in ['', *[t for t in TOPICS if t != 'envelope']]:
        code, output = text(['schema', *([topic] if topic else [])], fake_env)
        assert 'empty_pages' not in output and 'query_failure' not in output


def test_export_topic_describes_lines_format_and_resume(fake_env):
    code, output = text(['schema', 'export'], fake_env)
    assert all(word in output for word in ('header', 'page', 'format 2', 'resume'))


def test_trend_id_is_described_as_an_entry_identifier(fake_env):
    code, doc = invoke(['schema', 'trend'], fake_env)
    assert 'entry' in doc['$defs']['Trend']['properties']['id']['description']


def trend_page(*descriptions):
    entries = [{'entryId': f'trend-{i}', 'content': {'itemContent': {
        'itemType': 'TimelineTrend', 'name': f'Trend {i}', 'trend_metadata': {'meta_description': d}}}}
        for i, d in enumerate(descriptions)]
    return wrap('GenericTimelineById', [{'type': 'TimelineAddEntries', 'entries': entries}])


def test_trend_descriptions_follow_chars(fake_env):
    script(fake_env, {'op': 'GenericTimelineById', 'body': trend_page('A long trend description')})
    code, output = text(['trends', '--chars', '6'], fake_env)
    assert code == 0 and 'A long…' in output and 'A long trend' not in output


def test_place_card_descriptions_follow_chars(fake_env):
    script(fake_env, {'op': 'ListByRestId', 'body': wrap('ListByRestId', {
        'id_str': '1', 'name': 'Example list', 'description': 'Synthetic list description'})})
    code, output = text(['list', '1', '--tab', 'about', '--chars', '4'], fake_env)
    assert code == 0 and 'Synt…' in output and 'Synthetic list' not in output


def business(identity='100', handle='example'):
    node = user(identity, handle)
    node.update(verification={'verified_type': 'Business'}, relationship_counts={'followers': 1800000, 'following': 40},
                profile_bio={'description': 'Reads at https://t.co/bio'},
                legacy={'entities': {'description': {'urls': [{'url': 'https://t.co/bio', 'expanded_url': 'https://example.com/bio'}]}}})
    return node


def test_listing_renders_as_the_agreed_dense_text(fake_env):
    node = tweet('2102897863097545197')
    node['core']['user_results']['result'] = business()
    node['legacy'].update(full_text='…outbreak\n\nRead the full piece…', created_at='Wed Sep 23 23:08:00 +0000 2026',
                          favorite_count=855, retweet_count=63, reply_count=137, quote_count=14, entities={})
    node['views'] = {'count': '126200'}
    entries = [{'entryId': 'tweet-1', 'content': {'itemContent': {'tweet_results': {'result': node}}}},
               {'entryId': 'cursor-bottom', 'content': {'cursorType': 'Bottom', 'value': 'next'}}]
    script(fake_env, {'op': 'UserByScreenName', 'body': wrap('UserByScreenName', business())},
           {'op': 'UserTweets', 'body': wrap('UserTweets', [{'type': 'TimelineAddEntries', 'entries': entries}])})
    code, output = text(['user', '@example', '--limit', '1'], dict(fake_env, TZ='Asia/Seoul'))
    lines = output.rstrip('\n').splitlines()
    assert code == 0
    assert re.fullmatch(r'user posts · 1 shown · stopped=limit_reached · 2 requests · UserTweets 490/500 resets 1[45]m · '
                        r'window 2/200', lines[0]), lines[0]
    assert lines[1] == ('@example (Example ✓business) · followers 1.8M · following 40 · posts 50 · joined 2020-01 · '
                        'bio: "Reads at https://example.com/bio" · https://x.com/example')
    assert lines[2] == '[t1] @example ✓business · 2026-09-24 08:08+09:00 · likes=855 reposts=63 replies=137 quotes=14 views=126.2K'
    assert lines[3] == '     "…outbreak ⏎⏎ Read the full piece…"'
    assert lines[4] == '     https://x.com/example/status/2102897863097545197'
    assert re.fullmatch(r'more: uv run ".+/scripts/cli\.py" user @example --limit 1 --after [a-z0-9]{6}', lines[5])
    assert len(lines) == 6 and len(lines[0]) <= 120


def test_thread_completeness_trend_counts_and_viewer_change_keep_their_lines(fake_env):
    code, output = text(['post', '200'], fake_env)
    assert 'replies: 2 direct shown of 7 reported · +1 nested · hidden branches 0' in output.splitlines()
    assert len(output.splitlines()[0]) <= 120
    code, output = text(['trends'], fake_env)
    assert 'other items 0 · promoted excluded 0' in output.splitlines()
    (home(fake_env) / 'session.json').write_text(json.dumps({'ct0': 'x', 'viewer_id': '200', 'read_at': 0}))
    code, output = text(['home', '--limit', '1'], fake_env)
    assert 'viewer changed' in output.splitlines()[0]


def test_warnings_are_sentences_once_each_and_a_partial_failure_says_why(fake_env):
    body = {'data': {'list': {'id_str': '1', 'name': 'Example'}},
            'errors': [{'code': 214, 'message': 'Synthetic warning'}, {'code': 214, 'message': 'Synthetic warning'}]}
    script(fake_env, {'op': 'ListByRestId', 'body': body})
    code, output = text(['list', '1', '--tab', 'about'], fake_env)
    assert [line for line in output.splitlines() if line.startswith('warning:')] == ['warning: Synthetic warning']
    code, output = text(['home', '--limit', '10'], dict(fake_env, TWITTER_FAKE_SCENARIO='429'))
    last = output.rstrip('\n').splitlines()[-1]
    assert last.startswith('stopped: rate_limit: X operation rate limit reached. · fix: Wait until'), last


def test_a_secondary_bucket_shows_only_when_it_runs_low(fake_env):
    low = {'limit': 150, 'remaining': 20, 'reset': 4102444800}
    script(fake_env, {'op': 'UserByScreenName', 'body': wrap('UserByScreenName', user()), 'ratelimit': low})
    code, output = text(['user', '@example', '--limit', '1'], fake_env)
    assert 'UserByScreenName 20/150' in output.splitlines()[0] and 'UserByScreenName 20/150 resets' not in output
    code, output = text(['user', '@example', '--limit', '1'], fake_env)
    assert 'UserByScreenName' not in output.splitlines()[0]


def test_envelope_and_export_topics_are_json_schemas(fake_env):
    code, envelope = invoke(['schema', 'envelope'], fake_env)
    assert envelope['$schema'].startswith('https://json-schema.org') and 'empty_pages' in envelope['properties']['stop_reason']['enum']
    code, export = invoke(['schema', 'export'], fake_env)
    assert export['$schema'].startswith('https://json-schema.org') and export['oneOf']
