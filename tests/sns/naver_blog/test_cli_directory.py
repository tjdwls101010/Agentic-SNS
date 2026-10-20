"""topic and monthly through the real cli with a fake Aside: the topic directory, a topic's newest and featured posts, and
the blogs of the month from the mobile API (the old section API stopped at 2020-04)."""
import json

import pytest

from tests.sns.naver_blog.scene import M, SECTION, response
from tests.sns.naver_blog.shapes import topic_page, topic_posts, XSSI

DIRECTORY = response('topic-directory-xssi')


def first_line(out):
    return out.splitlines()[0]


def test_the_directory_lists_topics(naver):
    naver.respond(SECTION, '/ajax/DirectoryList.naver', body=DIRECTORY)
    code, out, _ = naver.run('naver-blog', 'topic')
    assert code == 0 and '[5] 문학·책 · 엔터테인먼트·예술' in out and '[20] 맛집' in out


def test_a_topic_by_name_costs_one_lookup_and_lists_newest(naver):
    naver.hint()
    naver.respond(SECTION, '/ajax/DirectoryList.naver', body=DIRECTORY)
    naver.respond(SECTION, '/ajax/DirectoryPostList.naver', body=topic_page(topic_posts(10)),
                  query={'directorySeq': '20', 'pageNo': 1})
    code, out, _ = naver.run('naver-blog', 'topic', '맛집')
    assert code == 0 and 'topic=맛집' in first_line(out) and 'requests=2' in first_line(out)
    assert 'url: https://blog.naver.com/tb0/900' in out and 'coverage: topic 맛집 is number 20' in out
    assert 'stops at 1,000' in out


def test_a_topic_number_costs_no_lookup(naver):
    naver.hint()
    naver.respond(SECTION, '/ajax/DirectoryPostList.naver', body=topic_page(topic_posts(10)),
                  query={'directorySeq': '20', 'pageNo': 1})
    code, out, _ = naver.run('naver-blog', 'topic', '20', '--limit', '3')
    assert code == 0 and '3 shown' in first_line(out) and naver.paths() == ['/ajax/DirectoryPostList.naver']


def test_featured_posts_are_one_page(naver):
    naver.respond(SECTION, '/ajax/DirectoryTopPostList.naver', body=XSSI + json.dumps({'result': topic_posts(3)}),
                  query={'directorySeq': '5'})
    code, out, _ = naver.run('naver-blog', 'topic', '5', '--top')
    assert code == 0 and 'shelf=featured' in first_line(out) and 'stopped=not_paginable' in out
    assert 'more:' not in out


@pytest.mark.parametrize('args', [['--top'], ['--since', '2026-10-01'], ['5', '--top', '--since', '2026-10-01'],
                                  ['5', '--top', '--out', 'f.ndjson']])
def test_one_page_surfaces_refuse_windows_and_files(naver, args):
    code, out, _ = naver.run('naver-blog', 'topic', *args)
    assert code == 2 and json.loads(out).get('command') == 'topic' and naver.fetches() == []


ISSUES = response('test_cli_directory-65')
GROUPS = response('test_cli_directory-66')
PROFILES = response('test_cli_directory-67')
POSTS = response('test_cli_directory-68')


def answer_monthly(naver, query=None):
    naver.respond(M, '/api/thismonthblog/year-month-list', json=ISSUES)
    naver.respond(M, '/api/thismonthblog/directory-blogid-list', json=GROUPS, query=query or {})
    naver.respond(M, '/api/blogs/profiles/profile-relation-list', json=PROFILES, query={'blogIdList': 'mb1,mb2,mb3'})
    naver.respond(M, '/api/blogs/posts/popular-post-list', json=POSTS, query={'blogIdList': 'mb1,mb2,mb3'})


def test_monthly_names_the_issue_and_groups_blogs_by_topic(naver):
    answer_monthly(naver, {'year': 2026, 'month': 9})
    code, out, _ = naver.run('naver-blog', 'monthly')
    assert code == 0, out
    assert 'requests=4' in first_line(out) and 'coverage: issue 2026-09' in out
    assert '공연·전시:' in out and '드라마:' in out and '[b1] mb1' in out
    assert out.count('대표 1-') == 2 and 'blocked' not in out
    assert 'posts <id> --popular' in out


def test_a_past_issue(naver):
    answer_monthly(naver, {'year': 2025, 'month': 11})
    code, out, _ = naver.run('naver-blog', 'monthly', '--year', '2025', '--month', '11')
    assert code == 0 and 'coverage: issue 2025-11' in out


def test_an_unpublished_month_names_the_latest_instead_of_swapping_it(naver):
    naver.respond(M, '/api/thismonthblog/year-month-list', json=ISSUES)
    code, out, _ = naver.run('naver-blog', 'monthly', '--year', '2026', '--month', '10')
    envelope = json.loads(out)
    assert code == 9 and '2026-09' in envelope['fix'] and len(naver.fetches()) == 1


def test_month_out_of_range_or_alone_is_refused(naver):
    for args in (['--month', '13'], ['--year', '2026']):
        code, out, _ = naver.run('naver-blog', 'monthly', *args)
        assert code == 2 and json.loads(out)['command'] == 'monthly'
    assert naver.fetches() == []


def test_a_failed_representative_posts_section_is_shown_beside_the_blogs(naver):
    naver.respond(M, '/api/thismonthblog/year-month-list', json=ISSUES)
    naver.respond(M, '/api/thismonthblog/directory-blogid-list', json=GROUPS)
    naver.respond(M, '/api/blogs/profiles/profile-relation-list', json=PROFILES)
    naver.respond(M, '/api/blogs/posts/popular-post-list', status=502, body='')
    code, out, _ = naver.run('naver-blog', 'monthly')
    assert code == 8 and 'representative posts: unavailable' in out and '공연·전시:' in out and '[b1] mb1' in out
