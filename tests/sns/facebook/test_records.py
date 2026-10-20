"""The record interface: decoded response chunks → records (fixtures/records_*.json), the head keys every record
carries, the keys the schema describes, and the media contract."""
from datetime import datetime, timezone

import pytest

from sns.facebook import web
from tests.sns.facebook.data import fixture

NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)
HEAD = ('kind', 'id', 'url', 'created_at')


def cases(name, parsers=None):
    return [pytest.param(case, id=case['name']) for case in fixture(name)['cases']
            if parsers is None or case['parser'] in parsers]


def subset(expected, actual, path='$'):
    """Problems where `actual` does not hold every field of `expected`; listed records must match in number and order."""
    problems = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f'{path}: expected an object, got {actual!r}']
        for key, value in expected.items():
            if key not in actual:
                problems.append(f'{path}.{key}: missing')
            else:
                problems += subset(value, actual[key], f'{path}.{key}')
    elif isinstance(expected, list) and expected and isinstance(expected[0], dict) and path.endswith(('records', 'collections')):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return [f'{path}: expected {len(expected)} items, got {actual!r}']
        for index, (e, a) in enumerate(zip(expected, actual)):
            problems += subset(e, a, f'{path}[{index}]')
    elif isinstance(expected, list) and path.endswith('records'):
        if actual != []:
            problems.append(f'{path}: expected no records, got {actual!r}')
    elif expected != actual:
        problems.append(f'{path}: expected {expected!r}, got {actual!r}')
    return problems


def parse(case):
    args = case.get('args', {})
    if case['parser'] == 'posts':
        page = web.posts_page(case['body_lines'], source=args['source'], connection_key=args['connection_key'],
                              captured_at=NOW)
        return {'records': page.records, 'page_info': page.page_info, 'issues': page.issues}
    if case['parser'] == 'permalink':
        record, issues = web.permalink_post(case['body_lines'], captured_at=NOW)
        return {'records': [record] if record else [], 'issues': issues}
    if case['parser'] == 'comments':
        page = web.comments_page(case['body_lines'], post_id=args['post_id'], captured_at=NOW)
        return {'records': page.records, 'page_info': page.page_info, 'issues': page.issues, 'handles': page.handles}
    if case['parser'] == 'replies':
        page = web.replies_page(case['body_lines'], post_id=args['post_id'], parent_id=args['parent_id'],
                                captured_at=NOW)
        return {'records': page.records, 'page_info': page.page_info, 'issues': page.issues}
    if case['parser'] == 'search':
        page = web.search_page(case['body_lines'], vertical=args['search_type'], captured_at=NOW)
        return {'records': page.records, 'page_info': page.page_info, 'issues': page.issues}
    if case['parser'] == 'notifications':
        page = web.notifications_page(case['body_lines'], captured_at=NOW)
        return {'records': page.records, 'page_info': page.page_info, 'issues': page.issues,
                'has_items': page.has_items}
    if case['parser'] == 'about_collections':
        return {'collections': web.about_collections(case['body_lines'])}
    if case['parser'] == 'about':
        fields, issues = web.about_fields(case['bodies'], profile_id=args['profile_id'],
                                          collection_names=args['collection_names'], captured_at=NOW)
        return {'records': fields, 'issues': issues}
    if case['parser'] == 'group_card':
        record, issues = web.group_card(case['body_lines'], group_id=args['group_id'], captured_at=NOW)
        return {'records': [record] if record else [], 'issues': issues}
    if case['parser'] == 'group_about':
        details, issues = web.group_about(case['body_lines'])
        return {'records': [details] if details else [], 'issues': issues}
    raise ValueError(case['parser'])


@pytest.mark.parametrize('case', cases('records_posts.json'))
def test_post_records(case):
    assert subset(case['expected'], parse(case)) == []


@pytest.mark.parametrize('case', cases('records_comments.json'))
def test_comment_records(case):
    assert subset(case['expected'], parse(case)) == []


@pytest.mark.parametrize('case', cases('records_search_about.json', ('search',)))
def test_search_records(case):
    assert subset(case['expected'], parse(case)) == []


@pytest.mark.parametrize('case', cases('records_search_about.json', ('about', 'about_collections', 'group_card',
                                                                      'group_about')))
def test_about_records(case):
    assert subset(case['expected'], parse(case)) == []


@pytest.mark.parametrize('case', cases('records_notifications.json'))
def test_notification_records(case):
    assert subset(case['expected'], parse(case)) == []


def test_comment_records_carry_every_documented_field():
    record = parse(fixture('records_comments.json')['cases'][0])['records'][0]
    assert set(record) == {key for key in web.SCHEMAS['comment']['fields'] if '[' not in key}


def test_post_records_carry_every_documented_field():
    record = parse(fixture('records_posts.json')['cases'][0])['records'][0]
    assert set(record) == {key for key in web.SCHEMAS['post']['fields'] if '[' not in key}


def test_page_reports_whether_the_connection_had_items():
    empty = [{'data': {'viewer': {'news_feed': {'edges': [], 'page_info': {'has_next_page': True, 'end_cursor': 'C'}}}}}]
    unreadable = [{'data': {'viewer': {'news_feed': {'edges': [{'node': {'something': 'else'}}],
                                                     'page_info': {'has_next_page': True, 'end_cursor': 'C'}}}}}]
    assert web.posts_page(empty, source='newsfeed', connection_key='news_feed', captured_at=NOW).has_items is False
    page = web.posts_page(unreadable, source='newsfeed', connection_key='news_feed', captured_at=NOW)
    assert page.records == [] and page.has_items is True


# --- the shared contract of records ---------------------------------------------------------------------------------

def every_record():
    """One record of every parser case of the fixtures, shared posts and group-about details left out of the count."""
    found = []
    for name in ('records_posts.json', 'records_comments.json', 'records_search_about.json',
                 'records_notifications.json'):
        for case in fixture(name)['cases']:
            if case['parser'] == 'group_about':
                continue  # the extra fields a card takes from the About screen, not a record
            found += parse(case).get('records', [])
    nested = []
    for record in found:
        shared = record.get('shared_post')
        while isinstance(shared, dict):
            nested.append(shared)
            shared = shared.get('shared_post')
    return found + nested


def schema_of(record):
    if record['kind'] in ('person', 'page'):
        return web.SCHEMAS['entity']
    if record['kind'] == 'group':
        return web.SCHEMAS['group'] if 'privacy' in record else web.SCHEMAS['entity']
    return web.SCHEMAS[record['kind']]


def test_every_record_carries_kind_id_url_and_created_at():
    records = every_record()
    assert len(records) > 40
    missing = [(r.get('kind'), r.get('id'), [k for k in HEAD if k not in r]) for r in records
               if any(k not in r for k in HEAD)]
    assert not missing, missing


def test_every_kind_of_record_is_one_the_schemas_know():
    kinds = {r['kind'] for r in every_record()}
    assert kinds == {'post', 'comment', 'about', 'person', 'page', 'group', 'notification'}


def test_every_key_a_record_exports_is_described_by_its_schema():
    undocumented = []
    for record in every_record():
        extra = set(record) - {key for key in schema_of(record)['fields'] if '[' not in key}
        if extra:
            undocumented.append((record['kind'], record.get('id'), sorted(extra)))
    assert not undocumented, undocumented


def test_a_media_items_numbers_start_at_one_per_record_and_a_video_keeps_its_poster():
    album = next(c for c in fixture('records_posts.json')['cases'] if c['name'] == 'album-video-without-playable-url')
    [record] = parse(album)['records']
    assert [m['n'] for m in record['media']] == [1, 2]
    video = record['media'][1]
    assert video['kind'] == 'video' and video['image_url'].endswith('poster.jpg') and video['video_url'] is None
    assert all(set(m) == {'n', 'kind', 'image_url', 'video_url', 'width', 'height', 'alt', 'media_id'}
               for r in every_record() for m in r.get('media', []))


def test_a_shared_posts_media_is_numbered_in_its_own_record():
    shared = next(c for c in fixture('records_posts.json')['cases'] if c['name'] == 'share-chain-nests')
    for record in parse(shared)['records']:
        while record:
            assert [m['n'] for m in record['media']] == list(range(1, len(record['media']) + 1))
            record = record.get('shared_post')
