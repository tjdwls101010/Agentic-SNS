"""graphql record interface: decoded response chunks → records (fixtures/records_*.json, appendix A 23-44)."""
from datetime import datetime, timezone

import pytest

from conftest import fixture
from facebook import graphql

NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


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
        page = graphql.posts_page(case['body_lines'], source=args['source'], connection_key=args['connection_key'],
                                  captured_at=NOW)
        return {'records': page.records, 'page_info': page.page_info, 'issues': page.issues}
    if case['parser'] == 'permalink':
        record, issues = graphql.permalink_post(case['body_lines'], captured_at=NOW)
        return {'records': [record] if record else [], 'issues': issues}
    raise ValueError(case['parser'])


@pytest.mark.parametrize('case', cases('records_posts.json'))
def test_post_records(case):
    assert subset(case['expected'], parse(case)) == []


def test_post_records_carry_every_documented_field():
    case = fixture('records_posts.json')['cases'][0]
    record = parse(case)['records'][0]
    assert set(record) == {key for key in graphql.SCHEMAS['post']['fields'] if '[' not in key}


def test_page_reports_whether_the_connection_had_items():
    empty = [{'data': {'viewer': {'news_feed': {'edges': [], 'page_info': {'has_next_page': True, 'end_cursor': 'C'}}}}}]
    unreadable = [{'data': {'viewer': {'news_feed': {'edges': [{'node': {'something': 'else'}}],
                                                     'page_info': {'has_next_page': True, 'end_cursor': 'C'}}}}}]
    assert graphql.posts_page(empty, source='newsfeed', connection_key='news_feed', captured_at=NOW).has_items is False
    page = graphql.posts_page(unreadable, source='newsfeed', connection_key='news_feed', captured_at=NOW)
    assert page.records == [] and page.has_items is True
