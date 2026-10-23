"""sns.threads.web records: raw Threads objects to the skill's records (fixtures: records_posts, records_lists,
records_thread). Expected values name only the fields a case is about."""
import pytest

from sns.errors import SnsError
from sns.threads import web as threads_web
from tests.sns.threads.data import fixture

POSTS = fixture('records_posts.json')
LISTS = fixture('records_lists.json')
THREAD = fixture('records_thread.json')
B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'


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
            return {**users[value['$user']], **{k: expand(v, users) for k, v in value.items() if k != '$user'}}
        return {k: expand(v, users) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, users) for v in value]
    return value


def shortcode(number):
    code = ''
    while True:
        number, digit = divmod(number, 64)
        code = B64[digit] + code
        if not number:
            return code


def quote_chain(levels, first_pk):
    raw = None
    for level in reversed(range(levels)):
        node = {'pk': str(first_pk + level), 'code': shortcode(first_pk + level),
                'user': {'pk': '1000000001', 'username': 'example.author'}}
        if raw is not None:
            node['text_post_app_info'] = {'share_info': {'quoted_post': raw}}
        raw = node
    return raw


@pytest.mark.parametrize('case', POSTS['cases'], ids=lambda c: c['name'])
def test_post_and_user_records(case):
    if case['parser'] == 'user':
        record = threads_web.user_record(case['raw'])
        if case['expected'] is None:
            assert record is None
        else:
            subset(case['expected'], record)
        return
    if 'generate' in case:
        record, level = threads_web.post_record(quote_chain(case['generate']['levels'], case['generate']['first_pk'])), 0
        while record and not record['unavailable']:
            record, level = record['quoted_post'], level + 1
        assert level == case['expected']['first_unavailable_level']
        return
    subset(case['expected'], threads_web.post_record(case['raw']))


@pytest.mark.parametrize('case', POSTS['cards']['cases'], ids=lambda c: c['name'])
def test_profile_cards(case):
    if case['expected'].get('outcome') == 'failed':
        with pytest.raises(SnsError) as error:
            threads_web.profile_card(case['raw'], case['requested'])
        assert error.value.kind == 'failed' and error.value.reason == case['expected']['kind']
        return
    subset(case['expected'], threads_web.profile_card(case['raw'], case['requested']))


@pytest.mark.parametrize('case', LISTS['cases'], ids=lambda c: c['name'])
def test_connections(case):
    data = expand(case['data'], LISTS['users'])
    expected = case['expected']
    if expected.get('outcome') == 'failed':
        with pytest.raises(SnsError) as error:
            threads_web.connection_page(data, case['surface'])
        assert error.value.kind == 'failed' and error.value.reason == expected['kind']
        return
    page = threads_web.connection_page(data, case['surface'])
    ids = [r['id'] for r in page.records]
    checks = {'ids': ids, 'groups': [[r['id'] for r in group] for group in page.groups],
              'has_next': page.has_next, 'cursor': page.cursor, 'stop': page.stop,
              'reported_total': page.reported_total,
              'unavailable': [r['id'] for r in page.records if r.get('unavailable')],
              'pinned': [r['id'] for r in page.records if r.get('pinned')],
              'relations': {r['id']: r['relation'] for r in page.records if r.get('relation')}}
    for key, value in expected.items():
        assert checks[key] == value, key


@pytest.mark.parametrize('case', THREAD['cases'], ids=lambda c: c['name'])
def test_post_pages(case):
    by_name = {c['name']: c for c in THREAD['cases']}
    responses = expand(case.get('responses') or by_name[case['responses_from']]['responses'], THREAD['users'])
    expected = case['expected']
    if expected.get('outcome'):
        with pytest.raises(SnsError) as error:
            threads_web.post_page(responses, code=case['code'], post_id=case['post_id'], limit=case['limit'])
        assert error.value.kind == expected['outcome']
        if expected['outcome'] == 'failed':
            assert error.value.reason == expected['kind']
        return
    page = threads_web.post_page(responses, code=case['code'], post_id=case['post_id'], limit=case['limit'])
    records, coverage = page.records, page.coverage
    if 'records' in expected:
        subset(expected['records'], records)
    if 'ids' in expected:
        assert [r['id'] for r in records] == expected['ids']
    if 'coverage' in expected:
        subset(expected['coverage'], coverage)


# --- the record contract (plan: common head keys, every exported key described, one media contract) ---

HEAD = ('kind', 'id', 'url', 'created_at')


def every_record():
    """One record of every kind the fixtures produce, nested ones included."""
    found = []
    for case in POSTS['cases']:
        if case['parser'] == 'user':
            record = threads_web.user_record(case['raw'])
        elif 'raw' in case:
            record = threads_web.post_record(case['raw'])
        else:
            continue
        if record is not None:
            found.append(record)
    for case in POSTS['cards']['cases']:
        if case['expected'].get('outcome') != 'failed':
            found.append(threads_web.profile_card(case['raw'], case['requested']))
    for case in LISTS['cases']:
        if case['expected'].get('outcome') != 'failed':
            found += threads_web.connection_page(expand(case['data'], LISTS['users']), case['surface']).records
    by_name = {c['name']: c for c in THREAD['cases']}
    for case in THREAD['cases']:
        if case['expected'].get('outcome'):
            continue
        responses = expand(case.get('responses') or by_name[case['responses_from']]['responses'], THREAD['users'])
        found += threads_web.post_page(responses, code=case['code'], post_id=case['post_id'], limit=case['limit']).records
    nested = [record[key] for record in found for key in ('quoted_post', 'reposted_post')
              if isinstance(record.get(key), dict)]
    return found + nested


def test_every_record_carries_kind_id_url_and_created_at():
    records = every_record()
    assert len(records) > 60
    missing = [(r.get('kind'), r.get('id'), [k for k in HEAD if k not in r]) for r in records
               if any(k not in r for k in HEAD)]
    assert not missing, missing


def documented(schema):
    return {name.strip() for key in schema['fields'] for name in key.split(',')}


def test_every_key_a_record_exports_is_described_by_its_schema():
    undocumented = []
    for record in every_record():
        extra = set(record) - documented(threads_web.SCHEMAS[record['kind']])
        if extra:
            undocumented.append((record['kind'], record.get('id'), sorted(extra)))
    assert not undocumented, undocumented


def test_a_media_items_numbers_start_at_one_per_record_and_a_video_keeps_its_poster():
    mixed = {'pk': '3000000000000000700', 'code': 'Cmixed', 'media_type': 8, 'user': {'pk': '1', 'username': 'a'},
             'carousel_media': [
                 {'pk': '3000000000000000701', 'media_type': 1,
                  'image_versions2': {'candidates': [{'url': 'https://cdn.example/one.jpg', 'width': 10, 'height': 10}]}},
                 {'pk': '3000000000000000702', 'media_type': 2,
                  'image_versions2': {'candidates': [{'url': 'https://cdn.example/poster.jpg', 'width': 20, 'height': 20}]},
                  'video_versions': [{'url': 'https://cdn.example/two.mp4', 'width': 40, 'height': 40}]},
                 {'media_type': 1, 'image_versions2': {'candidates': [{'url': ''}]}},
                 {'pk': '3000000000000000704', 'media_type': 1,
                  'image_versions2': {'candidates': [{'url': 'https://cdn.example/four.jpg'}]}}]}
    media = threads_web.post_record(mixed)['media']
    assert [m['n'] for m in media] == [1, 2, 3]  # the item with no usable address leaves no gap
    assert [m['media_id'] for m in media] == ['3000000000000000701', '3000000000000000702', '3000000000000000704']
    assert (media[1]['image_url'], media[1]['video_url']) == ('https://cdn.example/poster.jpg', 'https://cdn.example/two.mp4')
    assert media[0]['video_url'] is None
    assert all(set(m) == {'n', 'kind', 'image_url', 'video_url', 'width', 'height', 'alt', 'media_id'} for m in media)
    quoted = threads_web.post_record({'pk': '3000000000000000710', 'code': 'Cq', 'user': {'pk': '1', 'username': 'a'},
                                      'text_post_app_info': {'share_info': {'quoted_post': mixed}}})
    assert [m['n'] for m in quoted['quoted_post']['media']] == [1, 2, 3] and quoted['media'] == []
