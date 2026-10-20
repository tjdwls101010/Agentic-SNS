"""Post HTML → PostDoc: the body text, numbered pictures, links with their ids, Naver's flags, and an honest tally of how
much was read."""
import json

import pytest

from sns.errors import SnsError
from sns.naver_blog import web
from tests.sns.naver_blog.scene import FIXTURES, KIND_OF, fixture

BODY = fixture('body.json')


def parsed(case):
    html = (FIXTURES / case['file']).read_text(encoding='utf-8')
    return web.parse_post(html, blog_id=case['request']['blog_id'], log_no=case['request']['log_no'])


def check(doc, expect):
    data = doc.to_dict()
    for key, value in expect.items():
        if key == 'coverage':
            assert {k: data['coverage'][k] for k in value} == value
        elif key == 'never_in_output':
            text = json.dumps(data, ensure_ascii=False)
            assert not [v for v in value if v in text]
        elif key == 'viewer_id':
            assert doc.viewer_id == value
        else:
            assert data[key] == value, key


@pytest.mark.parametrize('name', ['full', 'partial', 'legacy'])
def test_post_page(name):
    check(parsed(BODY[name]), BODY[name]['expect'])


@pytest.mark.parametrize('case', BODY['pages'], ids=lambda c: f"{c['file']}:{c['request']['log_no']}")
def test_page_rules(case):
    if 'outcome' in case:
        with pytest.raises(SnsError) as caught:
            parsed(case)
        assert (caught.value.kind, caught.value.reason) == (KIND_OF[case['outcome']['code']], case['outcome']['reason'])
    else:
        check(parsed(case), case['expect'])


@pytest.mark.parametrize('case', BODY['deep']['cases'], ids=lambda c: c['name'])
def test_deep_markup(case):
    html = case['template'].format(open=case['open'] * case['repeat'], close=case['close'] * case['repeat'])
    lines = web.parse_post('<script>var gsTagName = "";</script><div id="_post_property" logno="1"></div>' + html,
                           blog_id='b', log_no='1').lines
    if 'expect_lines' in case:
        assert lines == case['expect_lines']
    else:
        assert len(lines) == case['expect_line_count']


def test_a_link_keeps_its_host_and_a_commercial_hosts_id():
    link = web.link_of('https://link.coupang.com/a/bXyZ12', 'buy')
    assert link == {'url': 'https://link.coupang.com/a/bXyZ12', 'text': 'buy', 'host': 'link.coupang.com',
                    'link_id': 'bXyZ12'}


def test_a_post_page_is_a_record_with_the_shared_head():
    data = parsed(BODY['full']).to_dict()
    blog, number = BODY['full']['request']['blog_id'], BODY['full']['request']['log_no']
    assert list(data)[:4] == ['kind', 'id', 'url', 'created_at']
    assert (data['kind'], data['id'], data['url']) == ('post', f'post:{blog}/{number}',
                                                       f'https://blog.naver.com/{blog}/{number}')
    assert data['like_count'] is None and data['reactions'] is None and 'viewer_id' not in data
