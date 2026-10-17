"""threads_web records: raw Threads objects to the skill's records (fixtures: records_posts, records_lists,
records_thread). Expected values name only the fields a case is about."""
import pytest

from conftest import fixture
from threads import threads_web
from threads.errors import ThreadsError

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
        with pytest.raises(ThreadsError) as error:
            threads_web.profile_card(case['raw'], case['requested'])
        assert error.value.code == 6 and error.value.reason == case['expected']['kind']
        return
    subset(case['expected'], threads_web.profile_card(case['raw'], case['requested']))


@pytest.mark.parametrize('case', LISTS['cases'], ids=lambda c: c['name'])
def test_connections(case):
    data = expand(case['data'], LISTS['users'])
    expected = case['expected']
    if expected.get('outcome') == 'failed':
        with pytest.raises(ThreadsError) as error:
            threads_web.connection_page(data, case['surface'])
        assert error.value.code == 6 and error.value.reason == expected['kind']
        return
    page = threads_web.connection_page(data, case['surface'])
    ids = [r['id'] for r in page.records]
    checks = {'ids': ids, 'groups': [[r['id'] for r in group] for group in page.groups],
              'has_next': page.has_next, 'cursor': page.cursor, 'stop': page.stop,
              'reported_total': page.reported_total,
              'unavailable': [r['id'] for r in page.records if r.get('unavailable')],
              'pinned': [r['id'] for r in page.records if r.get('is_pinned')],
              'relations': {r['id']: r['relation'] for r in page.records if r.get('relation')}}
    for key, value in expected.items():
        assert checks[key] == value, key


@pytest.mark.parametrize('case', THREAD['cases'], ids=lambda c: c['name'])
def test_post_pages(case):
    by_name = {c['name']: c for c in THREAD['cases']}
    responses = expand(case.get('responses') or by_name[case['responses_from']]['responses'], THREAD['users'])
    expected = case['expected']
    if expected.get('outcome'):
        with pytest.raises(ThreadsError) as error:
            threads_web.post_page(responses, code=case['code'], post_id=case['post_id'], limit=case['limit'])
        assert error.value.code == {'failed': 6, 'unavailable': 9}[expected['outcome']]
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
