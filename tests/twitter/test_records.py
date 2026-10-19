"""x_web records: raw X objects to the skill's records (fixtures: records_accounts, records_posts, timeline, thread).
Expected values name only the fields a case is about."""
import copy

import pytest

from conftest import fixture
from twitter import x_web
from twitter.errors import TwitterError

ACCOUNTS = fixture('records_accounts.json')
POSTS = fixture('records_posts.json')
TIMELINE = fixture('timeline.json')
THREAD = fixture('thread.json')


def subset(expected, actual, path='$'):
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f'{path}: {actual!r}'
        for key, value in expected.items():
            assert key in actual, f'{path}.{key} missing'
            subset(value, actual[key], f'{path}.{key}')
    elif isinstance(expected, list) and expected and isinstance(expected[0], dict):
        assert isinstance(actual, list) and len(actual) == len(expected), f'{path}: {actual!r}'
        for index, (e, a) in enumerate(zip(expected, actual)):
            subset(e, a, f'{path}[{index}]')
    else:
        assert expected == actual, f'{path}: expected {expected!r}, got {actual!r}'


def expand(value, users):
    if isinstance(value, dict):
        if '$user' in value:
            return copy.deepcopy(users[value['$user']])
        return {k: expand(v, users) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, users) for v in value]
    return value


@pytest.mark.parametrize('case', ACCOUNTS['cases'], ids=lambda c: c['name'])
def test_account_records(case):
    subset(case['expected'], x_web.account_record(case['raw']))


def quote_chain(levels, first):
    raw = None
    for level in reversed(range(levels)):
        node = {'__typename': 'Tweet', 'rest_id': str(first + level), 'legacy': {'full_text': str(level)}}
        if raw is not None:
            node['quoted_status_result'] = {'result': raw}
        raw = node
    return raw


@pytest.mark.parametrize('case', POSTS['cases'] + POSTS['after_recon']['cases'], ids=lambda c: c['name'])
def test_post_records(case):
    if 'build' in case:
        record = x_web.post_record(quote_chain(case['build']['quote_chain'], case['build']['first_id']))
        depth = 1
        while record.get('quoted_post'):
            record, depth = record['quoted_post'], depth + 1
        assert depth == case['expected']['depth_built']
        return
    entry_id = case.get('entry_id')
    record = x_web.post_record(expand(case['raw'], POSTS['users']), entry_id=entry_id)
    if case['expected'] is None:
        assert record is None
        return
    subset(case['expected'], record)


def fill_timeline(value):
    users = TIMELINE['users']
    if isinstance(value, dict):
        if '$post' in value:
            return {'__typename': 'Tweet', 'rest_id': value['$post'], 'core': {'user_results': {'result': users['A']}},
                    'legacy': {'full_text': 'post ' + value['$post'], 'created_at': 'Thu Oct 15 10:00:00 +0000 2026'}}
        if '$user' in value:
            return {'__typename': 'User', 'rest_id': value['$user'],
                    'core': {'screen_name': 'user_' + value['$user'], 'name': 'U'}}
        return {k: fill_timeline(v) for k, v in value.items()}
    if isinstance(value, list):
        return [fill_timeline(v) for v in value]
    return value


@pytest.mark.parametrize('case', TIMELINE['cases'], ids=lambda c: c['name'])
def test_timeline_instructions(case):
    page = x_web.walk(fill_timeline(case['instructions']))
    expected = case['expected']
    assert [[e.kind, e.ident, e.module, e.index, e.pinned] for e in page.entries] == expected['entries']
    for key in ('bottom', 'terminated', 'cleared', 'promoted', 'other'):
        if key in expected:
            assert getattr(page, key) == expected[key], key
    if 'branches' in expected:
        assert [{'module': b.module, 'cursor_type': b.cursor_type, 'value': b.value} for b in page.branches] == \
            expected['branches']
    records = x_web.list_page(fill_timeline(case['instructions'])).records
    if 'community_url' in expected:
        assert {r['id']: r.get('community_url') for r in records} == expected['community_url']
    if 'roles' in expected:
        assert {r['id']: r.get('role') for r in records} == expected['roles']
    if 'trends' in expected:
        subset(expected['trends'], [r for r in records if r.get('kind') in ('trend', 'event')])


def test_a_page_after_a_bottom_termination_has_no_next_even_with_a_cursor():
    instructions = [{'type': 'TimelineAddEntries', 'entries': [
        {'entryId': 'cursor-bottom-1', 'content': {'cursorType': 'Bottom', 'value': 'STILL'}}]},
        {'type': 'TimelineTerminateTimeline', 'direction': 'Bottom'}]
    page = x_web.list_page(instructions)
    assert page.cursor == 'STILL' and page.has_next is False


def test_records_of_a_list_carry_their_unit_for_the_window():
    case = next(c for c in TIMELINE['cases'] if c['name'] == 'module-items-keep-position')
    records = x_web.list_page(fill_timeline(case['instructions'])).records
    assert {r['unit'] for r in records} == {'profile-conversation-1850000000000000010'}


def fill_thread(value):
    users = THREAD['users']
    if isinstance(value, dict):
        if '$post' in value:
            ident, parent = value['$post']
            legacy = {'full_text': 'post ' + ident, 'created_at': 'Thu Oct 15 10:00:00 +0000 2026'}
            if parent:
                legacy['in_reply_to_status_id_str'] = parent
            legacy.update(value.get('legacy_extra') or {})
            return {'__typename': 'Tweet', 'rest_id': ident, 'core': {'user_results': {'result': users['A']}},
                    'legacy': legacy}
        return {k: fill_thread(v) for k, v in value.items()}
    if isinstance(value, list):
        return [fill_thread(v) for v in value]
    return value


@pytest.mark.parametrize('case', THREAD['cases'], ids=lambda c: c['name'])
def test_post_pages(case):
    expected = case['expected']
    instructions = fill_thread(case['instructions'])
    if expected.get('error') == 'unavailable':
        with pytest.raises(TwitterError) as error:
            x_web.post_page(instructions, case['post_id'], continuing=case['cursor'] is not None)
        assert error.value.code == 9
        return
    page = x_web.post_page(instructions, case['post_id'], continuing=case['cursor'] is not None)
    assert [[r['id'], r['role'], r['depth']] for r in page.records] == expected['order']
    if 'bottom' in expected:
        assert page.cursor == expected['bottom']
    coverage = expected.get('coverage') or {}
    for key, value in coverage.items():
        assert page.coverage[key] == value, key
    if expected.get('coverage_has_reported') is False:
        assert 'reported' not in page.coverage
    if 'unavailable_ids' in expected:
        assert [r['id'] for r in page.records if r.get('unavailable')] == expected['unavailable_ids']
    if 'branch_of' in expected:
        assert page.branches == expected['branch_of']
    if 'hidden_cursor' in expected:
        assert page.hidden_cursor == expected['hidden_cursor']
    if 'parent_shown' in expected:
        assert {r['id']: r['parent_shown'] for r in page.records if r['role'] == 'reply'} == expected['parent_shown']


def test_a_list_record_and_the_stub_x_sends_for_a_list_that_does_not_exist():
    list_record = x_web.list_record
    owner = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'author_a', 'name': 'A'}}
    record = list_record({'id_str': '15', 'name': 'L', 'mode': 'Private', 'member_count': 3, 'subscriber_count': 0,
                          'created_at': 1767225600000, 'following': True, 'user_results': {'result': owner}})
    assert record['private'] is True and record['follower_count'] == 0 and record['you_follow'] is True
    assert record['created_at'] == '2026-01-01T00:00:00+00:00' and record['owner']['username'] == 'author_a'
    assert record['url'] == 'https://x.com/i/lists/15' and record['you_are_member'] is None
    assert list_record({'facepile_urls': [], 'id': 'TGlzdDox', 'id_str': '1'}) is None
