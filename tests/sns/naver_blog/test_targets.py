"""Target rules: what a typed target normalizes to with no request, or its refusal; and which links are this platform's
(so another platform's command can name the command that reads them)."""
import pytest

from sns.errors import SnsError
from sns.naver_blog import web
from tests.sns.naver_blog.scene import KIND_OF, fixture

CASES = fixture('targets.json')


@pytest.mark.parametrize('case', CASES['cases'], ids=lambda c: f"{c['kind']}:{c['input']}")
def test_target(case):
    if 'error' in case:
        with pytest.raises(SnsError) as caught:
            web.parse_target(case['input'], case['kind'])
        assert caught.value.kind == KIND_OF[case['error']]
        return
    target = web.parse_target(case['input'], case['kind'])
    got = {k: v for k, v in {'blog_id': target.blog_id, 'log_no': target.log_no, 'category_no': target.category_no,
                             'short': target.short}.items() if v}
    assert got == case['expect']


@pytest.mark.parametrize('case', CASES['short_destinations']['cases'], ids=lambda c: str(c['location']))
def test_short_link_destination(case):
    if 'error' in case:
        with pytest.raises(SnsError) as caught:
            web.short_destination(case['location'], case['kind'])
        assert caught.value.kind == KIND_OF[case['error']]
        if case.get('names'):
            assert case['names'] in caught.value.message
        return
    target = web.short_destination(case['location'], case['kind'])
    assert {'blog_id': target.blog_id, 'log_no': target.log_no} == case['expect']


@pytest.mark.parametrize('url,expected', [
    ('https://blog.naver.com/sample_blog/224000000001', ('post', 'https://blog.naver.com/sample_blog/224000000001')),
    ('https://m.blog.naver.com/sample_blog/224000000001', ('post', 'https://m.blog.naver.com/sample_blog/224000000001')),
    ('https://blog.naver.com/PostView.naver?blogId=sample_blog&logNo=224000000001',
     ('post', 'https://blog.naver.com/PostView.naver?blogId=sample_blog&logNo=224000000001')),
    ('https://blog.naver.com/sample_blog', ('blog', 'https://blog.naver.com/sample_blog')),
    ('https://blog.naver.com/PostList.naver?blogId=sample_blog&categoryNo=3',
     ('posts', 'https://blog.naver.com/PostList.naver?blogId=sample_blog&categoryNo=3')),
    ('https://naver.me/AbCd12Ef', ('resolve', 'https://naver.me/AbCd12Ef')),
    ('naver.me/AbCd12Ef', ('resolve', 'naver.me/AbCd12Ef')),
])
def test_locate_names_the_command_that_opens_a_naver_link(url, expected):
    assert web.locate(url) == expected


@pytest.mark.parametrize('url', ['https://www.reddit.com/r/python', 'https://x.com/someone/status/20', 'sample_blog',
                                 'https://blog.naver.com/PostWrite.naver', 'https://cafe.naver.com/someone',
                                 'https://example.com/blog.naver.com/x'])
def test_locate_leaves_what_is_not_a_blog_link(url):
    assert web.locate(url) is None
