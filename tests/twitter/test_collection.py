"""Collecting across pages: cached tails, stops, date windows, continuation handles and page-committed --out files."""
import json
from pathlib import Path

import pytest

from .fake_data import entry, tweet, wrap
from .helpers import calls, home, invoke, more_args, records, script


def page(*nodes, cursor='next', pinned=None):
    entries = [entry(n) for n in nodes]
    if cursor:
        entries.append({'entryId': 'cursor-bottom', 'content': {'cursorType': 'Bottom', 'value': cursor}})
    body = [{'type': 'TimelinePinEntry', 'entry': entry(pinned)}] if pinned else []
    return body + [{'type': 'TimelineAddEntries', 'entries': entries}]


def dated(identity, when, parent=None):
    """A post created at an X-format timestamp such as 'Fri Jan 01 00:00:00 +0000 2021'."""
    node = tweet(identity, parent)
    node['legacy']['created_at'] = when
    return node


def ids(doc):
    return [r['id'] for r in doc['results']]


def test_cached_tail_is_served_in_order_before_another_request(fake_env):
    code, first = invoke(['user', '@example', '--limit', '2'], fake_env)
    before = len(calls(fake_env))
    code, second = invoke(more_args(first['next']), fake_env)
    assert code == 0 and ids(first) == ['200', '201'] and ids(second) == ['202', '203']
    assert len(calls(fake_env)) == before and second['budget']['requests'] == 0


def test_partial_failure_keeps_results_and_resumes_from_the_failed_cursor(fake_env):
    code, doc = invoke(['home', '--limit', '10'], dict(fake_env, TWITTER_FAKE_SCENARIO='429'))
    assert code == 8 and ids(doc) == ['200', '201', '202', '203', '204'] and doc['stop_reason'] == 'blocked'
    assert calls(fake_env)[-1]['variables']['cursor'] == 'next'
    (home(fake_env) / 'budget.json').unlink()
    code, resumed = invoke(more_args(doc['next']), fake_env)
    assert code == 0 and ids(resumed) == ['205', '206']
    assert calls(fake_env)[-1]['variables']['cursor'] == 'next'


def test_account_lists_stop_after_three_empty_pages(fake_env):
    code, doc = invoke(['graph', '@example', 'followers'], dict(fake_env, TWITTER_FAKE_SCENARIO='empty_users'))
    assert (code, doc['stop_reason']) == (8, 'empty_pages')
    assert [c['op'] for c in calls(fake_env)].count('Followers') == 3


def test_duplicates_are_dropped_and_a_repeated_cursor_ends_the_listing(fake_env):
    script(fake_env, {'op': 'UserTweets', 'body': wrap('UserTweets', page(tweet('200'), tweet('201'), cursor='same'))},
           {'op': 'UserTweets', 'body': wrap('UserTweets', page(tweet('201'), tweet('202'), cursor='same'))})
    code, doc = invoke(['user', '@example', '--limit', '3'], fake_env)
    assert code == 0 and ids(doc) == ['200', '201', '202'] and doc['stop_reason'] == 'exhausted'
    assert [c['op'] for c in calls(fake_env)].count('UserTweets') == 2


def test_date_window_ignores_the_pin_and_stops_early_only_on_profile_posts(fake_env):
    first = page(dated('new', 'Fri Jan 01 00:00:00 +0000 2026'), pinned=dated('pin', 'Fri Jan 01 00:00:00 +0000 2010'))
    script(fake_env, {'op': 'UserTweets', 'body': wrap('UserTweets', first)},
           {'op': 'UserTweets', 'body': wrap('UserTweets', page(dated('old', 'Wed Jan 01 00:00:00 +0000 2020'), cursor='end'))},
           {'op': 'ListLatestTweetsTimeline',
            'body': wrap('ListLatestTweetsTimeline', page(dated('old', 'Wed Jan 01 00:00:00 +0000 2020'), cursor=None))})
    code, doc = invoke(['user', '@example', '--since', '2025-01-01'], fake_env)
    assert doc['stop_reason'] == 'window_reached' and ids(doc) == ['new']
    assert [c['op'] for c in calls(fake_env)].count('UserTweets') == 2
    code, doc = invoke(['list', '1', '--since', '2025-01-01'], fake_env)
    assert doc['stop_reason'] == 'exhausted' and ids(doc) == []


def test_parent_and_focal_do_not_spend_the_reply_display_limit(fake_env):
    code, doc = invoke(['post', '200', '--limit', '1'], fake_env)
    assert code == 0 and ids(doc) == ['99', '200', '301']
    assert [r['role'] for r in doc['results']] == ['parent', 'focal', 'reply']
    code, tail = invoke(more_args(doc['next']), fake_env)
    assert ids(tail)[0] == '302'


def test_export_stores_only_the_date_window_but_remembers_every_seen_post(fake_env, tmp_path):
    body = page(dated('old', 'Wed Jan 01 00:00:00 +0000 2020'), dated('inside', 'Wed Jan 01 00:00:00 +0000 2025'),
                dated('future', 'Fri Jan 01 00:00:00 +0000 2027'), cursor=None)
    script(fake_env, {'op': 'UserTweets', 'body': wrap('UserTweets', body)})
    out = tmp_path / 'window.ndjson'
    invoke(['user', '@example', '--since', '2024-01-01', '--until', '2026-01-01', '--out', str(out)], fake_env)
    lines = records(out)
    assert [r['id'] for r in lines if 'id' in r] == ['inside']
    assert set(lines[-1]['state']['seen']) == {'old', 'inside', 'future'}


def test_thread_export_accumulates_hidden_branches_and_reply_counts(fake_env, tmp_path):
    focal, reply, nested = tweet('1'), tweet('2', '1'), tweet('3', '2')
    focal['legacy']['reply_count'] = 9
    more = [{'type': 'TimelineAddToModule', 'moduleEntryId': 'conversationthread-' + m, 'moduleItems': [
        {'entryId': 'more-' + m, 'item': {'itemContent': {'cursorType': 'ShowMoreThreads', 'value': m}}}]} for m in 'ab']
    script(fake_env, {'op': 'TweetDetail', 'body': wrap('TweetDetail', page(focal, reply) + more)},
           {'op': 'TweetDetail', 'body': wrap('TweetDetail', page(nested, cursor=None))})
    out = tmp_path / 'thread.ndjson'
    code, doc = invoke(['post', '1', '--limit', '10', '--out', str(out)], fake_env)
    assert code == 0 and doc['hidden_branches'] == 2
    metadata = [r for r in records(out) if r.get('kind') == 'page'][-1]['state']['metadata']
    assert {k: metadata[k] for k in ('reported', 'direct_shown', 'nested_shown', 'hidden_branches')} == dict(
        reported=9, direct_shown=1, nested_shown=1, hidden_branches=2)


def test_export_recovers_an_uncommitted_tail_and_refuses_another_viewer(fake_env, tmp_path):
    out = tmp_path / 'posts.ndjson'
    code, first = invoke(['user', '@example', '--limit', '2', '--out', str(out)], fake_env)
    assert code == 0 and first['stored'] == 5
    with out.open('ab') as stream:
        stream.write(b'{"id":"uncommitted"}\n')
    code, resumed = invoke(['user', '@example', '--limit', '2', '--out', str(out)], fake_env)
    stored = [r['id'] for r in records(out) if 'id' in r]
    assert code == 0 and resumed['stored'] == 7 and 'uncommitted' not in stored and len(stored) == len(set(stored))
    assert calls(fake_env)[-1]['variables']['cursor'] == 'next'
    session = json.loads((home(fake_env) / 'session.json').read_text())
    (home(fake_env) / 'session.json').write_text(json.dumps(dict(session, viewer_id='200')))
    code, doc = invoke(['user', '@example', '--limit', '2', '--out', str(out)], fake_env)
    assert (code, doc['error']) == (2, 'arguments') and 'different query or viewer' in doc['message']


def test_continuation_is_private_and_bound_to_the_viewer(fake_env):
    code, doc = invoke(['user', '@example', '--limit', '2'], fake_env)
    handle = Path(home(fake_env) / 'cursors' / f"{doc['next_handle']}.json")
    assert handle.stat().st_mode & 0o777 == 0o600
    session = json.loads((home(fake_env) / 'session.json').read_text())
    (home(fake_env) / 'session.json').write_text(json.dumps(dict(session, viewer_id='200')))
    code, doc = invoke(more_args(doc['next']), fake_env)
    assert (code, doc['error']) == (2, 'arguments')


def test_rest_of_a_received_trends_page_is_a_free_continuation(fake_env):
    entries = [{'entryId': f'trend-{i}', 'content': {'itemContent': {'itemType': 'TimelineTrend', 'name': f'T{i}'}}}
               for i in range(3)]
    script(fake_env, {'op': 'GenericTimelineById',
                      'body': wrap('GenericTimelineById', [{'type': 'TimelineAddEntries', 'entries': entries}])})
    code, first = invoke(['trends', '--limit', '1'], fake_env)
    before = len(calls(fake_env))
    assert code == 0 and [r['name'] for r in first['results']] == ['T0'] and first['next']
    code, rest = invoke(more_args(first['next']), fake_env)
    assert code == 0 and [r['name'] for r in rest['results']] == ['T1'] and len(calls(fake_env)) == before


def test_export_header_carries_the_format_and_an_older_file_is_refused_untouched(fake_env, tmp_path):
    out = tmp_path / 'new.ndjson'
    invoke(['user', '@example', '--limit', '2', '--out', str(out)], fake_env)
    assert records(out)[0]['format'] == 2
    old = tmp_path / 'old.ndjson'
    header = {'kind': 'header', 'command': 'user', 'target': ['example'], 'operation': 'UserTweets', 'viewer_id': '100',
              'tab': 'posts', 'sort': None, 'feed': None, 'type': None, 'scope': None, 'relation': None, 'collection': None,
              'since': None, 'until': None}
    old.write_text(json.dumps(header) + '\n')
    old.chmod(0o600)
    before = old.read_bytes()
    code, doc = invoke(['user', '@example', '--limit', '2', '--out', str(old)], fake_env)
    assert (code, doc['error']) == (2, 'arguments') and 'older' in doc['message'] and '--out' in doc['fix']
    assert old.read_bytes() == before


def test_continuation_state_carries_the_format_and_an_older_one_is_refused(fake_env):
    code, doc = invoke(['user', '@example', '--limit', '2'], fake_env)
    state = home(fake_env) / 'cursors' / f"{doc['next_handle']}.json"
    saved = json.loads(state.read_text())
    assert saved['format'] == 2
    saved.pop('format')
    state.write_text(json.dumps(saved))
    code, doc = invoke(more_args(doc['next']), fake_env)
    assert (code, doc['error']) == (2, 'arguments') and 'older' in doc['message'] and 'without --after' in doc['fix']


def cursor_files(env):
    return sorted(p.stem for p in (home(env) / 'cursors').glob('*.json'))


def test_handles_are_random_six_character_names_that_redraw_on_collision(fake_env):
    env = dict(fake_env, FAKE_HANDLE_CHARS='aaaaaabbbbbb')
    code, first = invoke(['user', '@example', '--limit', '2'], env)
    code, second = invoke(['home', '--limit', '2'], env)
    assert (first['next_handle'], second['next_handle']) == ('aaaaaa', 'bbbbbb')
    assert cursor_files(fake_env) == ['aaaaaa', 'bbbbbb']


@pytest.mark.parametrize('handle', ['../x', '1', 'ABCDEF', 'abcdefg', 'abc/ef'])
def test_malformed_handles_are_refused_before_any_file_or_request(handle, fake_env):
    (home(fake_env) / 'cursors').mkdir(mode=0o000)
    try:
        code, doc = invoke(['home', '--after', handle], fake_env)
    finally:
        (home(fake_env) / 'cursors').chmod(0o700)
    assert (code, doc['error']) == (2, 'arguments') and 'six lowercase letters or digits' in doc['message']
    assert '--after' in doc['fix'] and calls(fake_env) == []


def test_a_handle_expires_a_day_after_it_was_issued_and_is_swept_by_the_next_save(fake_env):
    code, doc = invoke(['user', '@example', '--limit', '2'], fake_env)
    later = dict(fake_env, FAKE_CLOCK_OFFSET='86401')
    code, expired = invoke(more_args(doc['next']), later)
    assert (code, expired['error']) == (2, 'arguments') and 'expired' in expired['message']
    assert 'without --after' in expired['fix']
    code, fresh = invoke(['home', '--limit', '2'], later)
    assert cursor_files(fake_env) == [fresh['next_handle']]


def test_more_repeats_only_what_was_typed_plus_limit_chars_and_json(fake_env):
    code, doc = invoke(['user', '@example', '--limit', '2', '--chars', '50'], fake_env)
    words = more_args(doc['next'])
    assert words == ['user', '@example', '--limit', '2', '--chars', '50', '--after', doc['next_handle'], '--json']
    code, doc = invoke(['search', 'python', '--type', 'users', '--limit', '2'], fake_env)
    assert more_args(doc['next'])[:6] == ['search', 'python', '--type', 'users', '--limit', '2']
    code, doc = invoke(['graph', '@example', 'followers', '--limit', '1'], fake_env)
    assert more_args(doc['next'])[:3] == ['graph', '@example', 'followers'] and '--tab' not in doc['next']


def empty_pages(count):
    return [{'op': 'HomeTimeline', 'body': wrap('HomeTimeline', page(cursor=f'c{i}'))} for i in range(count)]


def test_a_continuation_keeps_the_request_cap_of_the_call_that_issued_it(fake_env):
    script(fake_env, *empty_pages(25))
    code, first = invoke(['home'], fake_env)
    assert (code, first['stop_reason'], first['budget']['requests']) == (8, 'budget', 10)
    code, second = invoke(more_args(first['next']), fake_env)
    assert second['budget']['requests'] == 10
    script(fake_env, *empty_pages(25))
    code, explicit = invoke(['home', '--limit', '10'], fake_env)
    assert explicit['budget']['requests'] > 10


def test_an_existing_export_readable_by_others_is_refused_untouched_and_new_ones_are_private(fake_env, tmp_path):
    shared = tmp_path / 'shared.ndjson'
    shared.write_text('')
    shared.chmod(0o644)
    code, doc = invoke(['user', '@example', '--out', str(shared)], fake_env)
    assert (code, doc['error']) == (2, 'arguments') and 'chmod 600' in doc['fix'] and '--out' in doc['fix']
    assert shared.read_bytes() == b'' and shared.stat().st_mode & 0o777 == 0o644 and calls(fake_env) == []
    fresh = tmp_path / 'fresh.ndjson'
    invoke(['user', '@example', '--out', str(fresh)], fake_env)
    assert fresh.stat().st_mode & 0o777 == 0o600
