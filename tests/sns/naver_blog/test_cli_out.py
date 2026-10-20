"""--out collections: page-committed NDJSON, resume, completeness, refusals that leave a foreign file untouched. A
collection is tied to the account (it asks who is logged in first, current-user once per run)."""
import json

from tests.sns.naver_blog.scene import M
from tests.sns.naver_blog.shapes import blog_posts, post_items, post_list, search_page


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def first_line(out):
    return out.splitlines()[0]


def test_search_collects_resumes_and_then_reads_nothing(naver, tmp_path):
    out = tmp_path / 'c.ndjson'
    naver.logged_in()
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30)), query={'page': 1})
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30, 31)), query={'page': 2})
    code, text, _ = naver.run('naver-blog', 'search', '카페', '--out', str(out), '--limit', '45')
    assert code == 0, text
    assert '60 saved to' in text and 'requests=3' in text, 'whole pages are committed, so a little over --limit'
    rows = lines(out)
    assert rows[0]['kind'] == 'header' and rows[0]['format'] == 1 and rows[0]['platform'] == 'naver_blog'
    assert rows[0]['context']['command'] == 'search' and rows[0]['viewer'] == 'viewer_blog'
    records = [r for r in rows if r.get('kind') not in ('page', 'header')]
    assert len(records) == 60 and records[0]['kind'] == 'post' and records[0]['id'].startswith('post:')
    assert (out.stat().st_mode & 0o777) == 0o600
    naver.logged_in()
    code, again, _ = naver.run('naver-blog', 'search', '카페', '--out', str(out), '--limit', '45')
    assert code == 0 and naver.paths()[3:] == ['/api/current-user'], 'a file at its limit asks only who is logged in'


def test_a_file_of_another_query_is_refused_unchanged(naver, tmp_path):
    out = tmp_path / 'c.ndjson'
    naver.logged_in()
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(3)))
    naver.run('naver-blog', 'search', '카페', '--out', str(out))
    before = out.read_bytes()
    code, text, _ = naver.run('naver-blog', 'search', '연남', '--out', str(out))
    assert code == 2 and out.read_bytes() == before


def test_a_file_written_by_the_old_skill_is_refused_byte_for_byte(naver, tmp_path):
    out = tmp_path / 'old.ndjson'
    old = ('{"command":"search","text":"카페","type":"posts","sort":"sim","kind":"header",'
           '"started_at":"2026-09-07T00:00:00+00:00","limit_unit":"records displayed"}\n'
           '{"id":"post:a/1","title":"x"}\n{"kind":"page","state":{"page":2},"ids":["post:a/1"],"n":1,"stop_reason":"page"}\n')
    out.write_text(old)
    code, text, _ = naver.run('naver-blog', 'search', '카페', '--out', str(out))
    assert code == 2 and out.read_text() == old and naver.fetches() == []


def test_a_stop_by_the_time_limit_is_not_done_and_the_same_command_resumes_to_the_end(naver, tmp_path):
    out = tmp_path / 'big.ndjson'
    naver.logged_in()
    for page in range(1, 41):
        naver.respond(M, '/api/blogs/b/post-list', json=post_list(blog_posts(30, start=30 * (page - 1), blog='b')),
                      query={'page': page})
    naver.respond(M, '/api/blogs/b/post-list', json=post_list(blog_posts(3, start=30 * 40, blog='b')),
                  query={'page': 41})
    code, text, _ = naver.run('naver-blog', 'posts', 'b', '--out', str(out), env={'SNS_DEADLINE_SECONDS': '12'})
    assert code == 0 and 'stopped=time_limit' in text and 'resume: ' in text
    assert lines(out)[-1].get('end') == 'interrupted'
    naver.monkeypatch.delenv('SNS_DEADLINE_SECONDS')   # the pacing the first run left is still owed in the second
    naver.logged_in()
    code, text, _ = naver.run('naver-blog', 'posts', 'b', '--out', str(out))
    assert code == 0 and 'stopped=exhausted' in text
    assert lines(out)[-1].get('end') == 'final'
    ids = [r['id'] for r in lines(out) if str(r.get('id', '')).startswith('post:')]
    assert len(ids) == len(set(ids)) == 30 * 40 + 3


def test_a_handle_in_the_old_skills_shape_is_refused_unchanged(naver, data_dir):
    handles = data_dir / 'handles'
    handles.mkdir(parents=True)
    old = '{"context":{"command":"search","text":"카페","type":"posts","sort":"sim"},"state":{"page":2,"pending":[],"seen":[]},"created_at":"2026-09-07T00:00:00+00:00"}\n'
    (handles / '7.json').write_text(old)
    code, text, _ = naver.run('naver-blog', 'search', '카페', '--after', '7')
    assert code == 2 and 'earlier version' in json.loads(text)['message'] and (handles / '7.json').read_text() == old
    assert naver.fetches() == []


def test_an_out_path_that_cannot_be_written_is_refused_before_any_request(naver, tmp_path):
    target = tmp_path / 'no-such-dir' / 'f.ndjson'
    code, text, _ = naver.run('naver-blog', 'search', '카페', '--out', str(target))
    assert code == 2 and naver.fetches() == []


def test_a_file_that_ended_at_naver_s_ceiling_repeats_that_end_and_reads_nothing(naver, tmp_path):
    out = tmp_path / 'capped.ndjson'
    naver.logged_in()
    naver.respond(M, '/api/tags/search/post', json={'isSuccess': True, 'result': {'items': post_items(10)}})
    assert naver.run('naver-blog', 'search', '카페', '--type', 'tags', '--out', str(out))[0] == 0
    rows = out.read_text().splitlines()
    last = json.loads(rows[-1])
    last['stop_reason'], last['end'], last['verdict'] = 'server_capped', 'final', None
    out.write_text('\n'.join(rows[:-1] + [json.dumps(last, ensure_ascii=False)]) + '\n')
    sent = len(naver.fetches())
    code, text, _ = naver.run('naver-blog', 'search', '카페', '--type', 'tags', '--out', str(out))
    assert code == 0 and 'stopped=server_capped' in text and 'already complete' in text and len(naver.fetches()) == sent


def test_an_out_file_at_its_limit_reads_nothing_until_the_limit_is_raised(naver, tmp_path):
    out = tmp_path / 'f.ndjson'
    naver.logged_in()
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(30)), query={'page': 1})
    code, text, _ = naver.run('naver-blog', 'search', '카페', '--out', str(out), '--limit', '20')
    assert code == 0 and '30 saved' in text, 'a whole page is committed, so a little over --limit'
    naver.logged_in()
    code, text, _ = naver.run('naver-blog', 'search', '카페', '--out', str(out), '--limit', '20')
    assert code == 0 and 'stopped=limit_reached' in text and naver.paths().count('/api/search/v1/post') == 1
    naver.logged_in()
    naver.respond(M, '/api/search/v1/post', json=search_page(post_items(10, 31)), query={'page': 2})
    code, text, _ = naver.run('naver-blog', 'search', '카페', '--out', str(out), '--limit', '100')
    assert code == 0 and '40 saved' in text and 'stopped=exhausted' in text


def test_an_out_resume_does_not_resolve_the_category_again(naver, tmp_path):
    out = tmp_path / 'cat.ndjson'
    naver.logged_in()
    naver.respond(M, '/api/blogs/b/category-list', json={'isSuccess': True, 'result': {'mylogCategoryList': [
        {'categoryNo': 3, 'categoryName': '성수'}]}})
    for page in range(1, 31):
        naver.respond(M, '/api/blogs/b/post-list', json=post_list(blog_posts(30, start=30 * (page - 1), blog='b')),
                      query={'page': page, 'categoryNo': 3})
    code, _, _ = naver.run('naver-blog', 'posts', 'b', '--category', '성수', '--out', str(out),
                           env={'SNS_DEADLINE_SECONDS': '8'})
    assert code == 0
    naver.monkeypatch.delenv('SNS_DEADLINE_SECONDS')
    naver.logged_in()
    naver.respond(M, '/api/blogs/b/post-list', json=post_list([]), query={'page': 31, 'categoryNo': 3})
    naver.run('naver-blog', 'posts', 'b', '--category', '성수', '--out', str(out))
    assert naver.paths().count('/api/blogs/b/category-list') == 1
