"""keywords through the real cli: Naver's popular searches of the day, or the searches related to one keyword."""
import json

from tests.sns.naver_blog.scene import M, response


def test_popular_keywords_with_their_date(naver):
    naver.respond(M, '/api/v1/popular-keywords', json=response('test_cli_new-16'))
    code, out, _ = naver.run('naver-blog', 'keywords')
    assert code == 0, out
    first = out.splitlines()[0]
    assert 'kind=popular' in first and '12 shown' in first and 'requests=1' in first
    assert '[k1] 인기0' in out and 'as of 2026-10-19' in out and 'a ranking, not a share of searches' in out


def test_related_keywords_for_one_keyword(naver):
    naver.respond(M, '/api/related-keywords', json=response('test_cli_new-26'), query={'keyword': '성수 카페'})
    code, out, _ = naver.run('naver-blog', 'keywords', '성수', '카페')
    assert code == 0 and 'kind=related' in out.splitlines()[0] and '[k15] 연관14' in out


def test_no_related_keywords_is_an_explicit_empty_result(naver):
    naver.respond(M, '/api/related-keywords', json={'isSuccess': True, 'result': {'keywords': [], 'totalCount': 0}})
    code, out, _ = naver.run('naver-blog', 'keywords', '없는말')
    assert code == 7 and 'related to' in json.loads(out)['message']
