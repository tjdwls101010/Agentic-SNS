"""post and comments through the real cli with a fake Aside: the body with numbered pictures and links, Naver's own-money
flag, the live reaction count, same-category posts without the post itself, comments rebuilt under their parents, and
the account a post page names."""
import json

from tests.sns.naver_blog.scene import ACCOUNT, CBOX, FIXTURES, M, response
from tests.sns.support.cli import command_of, more_line

POST = 'cafe_note/224000000001'
HTML = (FIXTURES / 'posts/smart_full.html').read_text(encoding='utf-8')
LIKES, RELATED, CBOX_PAGE = response('sympathy-1'), response('related-1'), response('cbox-1')


def first_line(out):
    return out.splitlines()[0]


def comment_rows():
    return response('cbox-1')['result']['commentList']


def cbox(rows, page=1, total_pages=1, count=None):
    body = response('cbox-1')
    body['result'].update(commentList=rows, pageModel={'page': page, 'totalPages': total_pages,
                                                       'nextPage': page + 1 if page < total_pages else 0})
    if count:
        body['result']['count'] = count
    return body


def answer_post(naver, *, with_related=True):
    naver.respond(M, '/PostView.naver', body=HTML, content_type='text/html',
                  query={'blogId': 'cafe_note', 'logNo': '224000000001'})
    naver.respond(M, '/api/blogs/cafe_note/posts/224000000001/sympathy-users', json=LIKES)
    if with_related:
        naver.respond(M, '/api/blogs/cafe_note/v1/category-related-posts', json=RELATED, query={'categoryNo': '12'})


def test_post_reads_the_whole_body_with_numbered_pictures_and_links(naver):
    answer_post(naver)
    code, out, _ = naver.run('naver-blog', 'post', 'https://m.blog.naver.com/' + POST)
    assert code == 0, out
    assert 'requests=3' in first_line(out)
    assert 'text[full]' in out and '[image 1: 입구]' in out and '[sticker: image 4]' in out
    assert 'likes=525 (like 514 · impressive 10 · thanks 1)' in out
    assert 'no Naver 내돈내산 인증 card' in out
    assert 'https://mkt.shopping.naver.com/link/6811aaa6000000000000abcd (mkt.shopping.naver.com, id 6811aaa6000000000000abcd)' in out
    assert 'https://link.coupang.com/a/bXyZ12 (link.coupang.com, id bXyZ12)' in out
    assert 'tags: 성수카페, 디저트, 내돈내산' in out
    same = out.split('same category:')[1]
    assert '224000000005' in same and '224000000006' in same and '224000000001' not in same
    assert 'viewer_me' not in out and '778899' not in out and 'SYNTHETIC-SECRET' not in out


def test_the_page_names_the_viewer_for_free_and_that_is_kept_as_a_hint(naver, data_dir):
    answer_post(naver)
    naver.run('naver-blog', 'post', POST)
    saved = json.loads((data_dir / 'naver_blog' / ACCOUNT / 'session' / 'viewer.json').read_text())
    assert saved['viewer'] == 'viewer_me' and '/api/current-user' not in naver.paths()


def test_post_json_carries_the_body_record_with_the_shared_head(naver):
    answer_post(naver)
    code, out, _ = naver.run('naver-blog', 'post', POST, '--json')
    envelope = json.loads(out)
    record = next(s for s in envelope['sections'] if s['name'] == 'post')['data'][0]
    assert (record['kind'], record['id'], record['url']) == ('post', 'post:cafe_note/224000000001',
                                                             'https://blog.naver.com/cafe_note/224000000001')
    assert record['like_count'] == 525 and record['reactions'] == {'like': 514, 'impressive': 10, 'thanks': 1}
    assert record['coverage']['label'] == 'text[full]' and record['images'][3]['kind'] == 'sticker'
    assert record['own_money'] is False and record['blog_no'] == '123456' and 'viewer_id' not in record
    assert [s['name'] for s in envelope['sections']] == ['post', 'reactions', 'same category']


def test_a_failed_section_is_shown_and_partial(naver):
    answer_post(naver, with_related=False)
    naver.respond(M, '/api/blogs/cafe_note/v1/category-related-posts', status=502, body='')
    code, out, _ = naver.run('naver-blog', 'post', POST)
    assert code == 8 and 'same category: unavailable' in out and 'text[full]' in out
    assert 'coverage: incomplete' in out and 'more:' not in out


def test_a_hold_met_by_a_later_section_keeps_the_post_and_is_partial(naver, data_dir):
    answer_post(naver, with_related=False)
    naver.respond(M, '/api/blogs/cafe_note/v1/category-related-posts', status=429, body='')
    code, out, _ = naver.run('naver-blog', 'post', POST)
    assert code == 8 and 'text[full]' in out and 'same category: unavailable' in out
    sent = len(naver.fetches())
    code, out, _ = naver.run('naver-blog', 'post', POST)
    assert code == 5 and len(naver.fetches()) == sent, 'the hold stands: nothing more is sent'


def test_a_deleted_post_is_exit_9(naver):
    naver.respond(M, '/PostView.naver', status=404, body="location.href='/MobileErrorView.naver?errorType=noPost'")
    code, out, _ = naver.run('naver-blog', 'post', POST)
    assert code == 9 and json.loads(out)['error'] == 'unavailable'


def test_a_naver_me_link_is_resolved_by_one_counted_hop(naver):
    naver.respond('naver.me', '/AbCd12Ef', status=307, location='https://m.blog.naver.com/' + POST, body='')
    answer_post(naver)
    code, out, _ = naver.run('naver-blog', 'post', 'https://naver.me/AbCd12Ef')
    assert code == 0 and 'requests=4' in first_line(out)


def test_a_naver_me_link_elsewhere_names_where_it_goes(naver):
    naver.respond('naver.me', '/AbCd12Ef', status=307, location='https://brandconnect.naver.com/x/y', body='')
    code, out, _ = naver.run('naver-blog', 'post', 'naver.me/AbCd12Ef')
    assert code == 2 and 'brandconnect.naver.com' in json.loads(out)['message']


def test_post_with_comments_reads_one_page_of_ten_parents(naver):
    answer_post(naver)
    naver.respond(*CBOX, json=cbox(comment_rows()), query={'objectId': '123456_201_224000000001', 'page': 1})
    code, out, _ = naver.run('naver-blog', 'post', POST, '--comments')
    assert code == 0 and 'requests=4' in first_line(out) and 'comments:' in out
    assert 'comments-info' not in ' '.join(naver.paths()), 'the post page already names the blog number'


def test_comments_are_rebuilt_under_their_parents(naver):
    naver.hint()
    naver.respond(M, '/api/blogs/cafe_note/posts/224000000001/comments-info',
                  json={'isSuccess': True, 'result': {'blogNo': 123456, 'totalCount': 5}})
    naver.respond(*CBOX, json=cbox(comment_rows()))
    code, out, _ = naver.run('naver-blog', 'comments', POST)
    assert code == 0, out
    lines = out.splitlines()
    assert '5 shown' in lines[0] and 'stopped=exhausted' in lines[0]
    order = [line.split('#')[1].split()[0] for line in lines if line.lstrip().startswith('[c')]
    assert order == ['11', '10', '14', '12', '13']
    assert "coverage: Naver's count: 3 comments · 2 replies · 0 deleted · 0 blinded · 5 total" in out
    assert '(parent not shown)' in out and 'url: https://blog.naver.com/cafe_note/224000000001' not in out


def test_comments_continue_without_the_lookup(naver):
    naver.hint()
    naver.respond(M, '/api/blogs/cafe_note/posts/224000000001/comments-info',
                  json={'isSuccess': True, 'result': {'blogNo': 123456, 'totalCount': 200}})
    rows = [{'commentNo': 5000 - i, 'parentCommentNo': 5000 - i, 'replyLevel': 1, 'userName': f'u{i}', 'contents': 'c',
             'objectId': '123456_201_224000000001'} for i in range(100)]
    naver.respond(*CBOX, json=cbox(rows, 1, 2, {'comment': 200, 'reply': 0, 'total': 200}), query={'page': 1})
    code, out, _ = naver.run('naver-blog', 'comments', POST)
    assert code == 0 and '20 shown' in first_line(out)
    naver.logged_in()
    code, again, _ = naver.run(*command_of(more_line(out)))
    assert code == 0 and '20 shown' in first_line(again)
    assert naver.paths().count('/api/blogs/cafe_note/posts/224000000001/comments-info') == 1
    assert naver.paths().count('/commentBox/cbox/web_naver_list_json.json') == 1, 'the waiting rows cost no request'


def test_comments_follow_the_comment_boxs_own_next_page(naver):
    naver.hint()
    naver.respond(M, '/api/blogs/cafe_note/posts/224000000001/comments-info',
                  json={'isSuccess': True, 'result': {'blogNo': 123456, 'totalCount': 3}})
    rows = lambda start: [{'commentNo': start + i, 'parentCommentNo': start + i, 'replyLevel': 1, 'userName': 'u',
                           'contents': 'c', 'objectId': '123456_201_224000000001'} for i in range(2)]
    naver.respond(*CBOX, json=cbox(rows(10), 1, 2, {'comment': 4, 'reply': 0, 'total': 4}), query={'page': 1})
    naver.respond(*CBOX, json=cbox(rows(20), 2, 2, {'comment': 4, 'reply': 0, 'total': 4}), query={'page': 2})
    code, out, _ = naver.run('naver-blog', 'comments', POST, '--limit', '10')
    assert code == 0 and '4 shown' in first_line(out) and 'stopped=exhausted' in first_line(out)


def test_a_post_page_naming_another_account_than_the_command_started_with_is_a_changed_login(naver, tmp_path):
    answer_post(naver)
    naver.logged_in()   # --out checks the account first: the browser says viewer_blog; the page says viewer_me
    code, out, _ = naver.run('naver-blog', 'post', POST, '--out', str(tmp_path / 'post.ndjson'))
    envelope = json.loads(out)
    assert code == 4 and envelope['error'] == 'login' and 'viewer_me' in envelope['message']


def test_post_out_is_written_only_when_every_section_was_read_so_a_rerun_gets_all_of_it(naver, tmp_path):
    answer_post(naver, with_related=False)
    naver.respond(M, '/api/blogs/cafe_note/v1/category-related-posts', status=502, body='')
    naver.logged_in(userId='viewer_me')
    out = tmp_path / 'post.ndjson'
    code, text, _ = naver.run('naver-blog', 'post', POST, '--out', str(out))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert code == 8 and [r.get('kind') for r in rows] == ['header', 'page'] and rows[-1]['end'] == 'interrupted'
    answer_post(naver)   # the same command again, Naver healthy
    naver.logged_in(userId='viewer_me')
    code, text, _ = naver.run('naver-blog', 'post', POST, '--out', str(out))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert code == 0 and rows[-1]['end'] == 'final'
    assert not [r for r in rows if str(r.get('id', '')).startswith('section:')]
    post = next(r for r in rows if r.get('id') == 'post:cafe_note/224000000001')
    assert post['like_count'] == 525, 'no stale half-read post stays in the file'
    assert any(r.get('id') == 'post:cafe_note/224000000005' for r in rows)


def test_post_out_of_a_good_post_is_final_and_a_rerun_reads_nothing(naver, tmp_path):
    answer_post(naver)
    naver.logged_in(userId='viewer_me')
    out = tmp_path / 'post.ndjson'
    code, text, _ = naver.run('naver-blog', 'post', POST, '--out', str(out))
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert code == 0 and rows[-1]['end'] == 'final'
    assert [r['id'] for r in rows if r.get('kind') == 'post'][0] == 'post:cafe_note/224000000001'
    sent = len(naver.fetches())
    code, text, _ = naver.run('naver-blog', 'post', POST, '--out', str(out))
    assert code == 0 and 'already complete' in text and len(naver.fetches()) == sent
