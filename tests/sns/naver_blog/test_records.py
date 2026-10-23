"""Records in the skill's terms: one builder per kind for every surface that sends it."""
import pytest

from sns.naver_blog import web
from tests.sns.naver_blog.scene import fixture

POSTS = fixture('records_posts.json')
COMMENTS = fixture('records_comments.json')
BLOGS = fixture('records_blogs.json')


def subset(record, expect):
    data = record.to_dict()
    return {key: data.get(key) for key in expect}


@pytest.mark.parametrize('case', POSTS['cases'], ids=lambda c: c['name'])
def test_post(case):
    record = web.post_record(case['raw'], blog_id=(case.get('context') or {}).get('blog_id'))
    if case['expect'] is None:
        assert record is None
    else:
        assert subset(record, case['expect']) == case['expect']


@pytest.mark.parametrize('case', POSTS['stamp'], ids=lambda c: repr(c['input']))
def test_stamp(case):
    assert web.stamp(case['input']) == case['output']


@pytest.mark.parametrize('case', POSTS['clean'], ids=lambda c: repr(c['input']))
def test_clean(case):
    assert web.clean(case['input']) == case['output']


@pytest.mark.parametrize('case', COMMENTS['cases'], ids=lambda c: c['name'])
def test_comment(case):
    record = web.comment_record(case['raw'])
    if case['expect'] is None:
        assert record is None
    else:
        assert subset(record, case['expect']) == case['expect']


def test_replies_are_rebuilt_under_their_parent():
    page = COMMENTS['page']
    rebuilt = web.thread_comments([web.comment_record(raw) for raw in page['raw']])
    got = [{'comment_no': c.comment_no, 'depth': c.depth, **({'parent_shown': c.parent_shown} if c.depth else {})}
           for c in rebuilt]
    assert got == page['expect_order']


def test_comment_counts():
    assert web.comment_counts(COMMENTS['counts']['raw']) == COMMENTS['counts']['expect']


@pytest.mark.parametrize('case', BLOGS['cards'], ids=lambda c: c['name'])
def test_blog_card(case):
    record = web.blog_record(case['raw'])
    assert (record and subset(record, case['expect'])) == case['expect']


def test_categories_skip_dividers_and_nest():
    got = [c.to_dict() for c in web.categories(BLOGS['categories']['raw'], 'sample_blog')]
    assert got == BLOGS['categories']['expect']


@pytest.mark.parametrize('case', BLOGS['buddies'], ids=lambda c: c['name'])
def test_buddy(case):
    record = web.buddy_record(case['raw'])
    assert (record and subset(record, case['expect'])) == case['expect']


def test_topics():
    assert [t.to_dict() for t in web.topics(BLOGS['topics']['raw'])] == BLOGS['topics']['expect']
