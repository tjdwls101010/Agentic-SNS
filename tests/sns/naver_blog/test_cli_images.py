"""images through the real cli: a post's numbered pictures saved to the skill's picture store (one request each), what
cannot be saved named and skipped, and a stop (the time limit, a hold) that names the pictures left."""
import base64
import json
import os
import time

from tests.sns.naver_blog.scene import FIXTURES, M
from tests.sns.support.cli import command_of

PICTURE = b'\xff\xd8\xff\xe0' + b'synthetic-jpeg' * 10
POST = 'cafe_note/224000000001'
HTML = (FIXTURES / 'posts/smart_full.html').read_text(encoding='utf-8')


def first_line(out):
    return out.splitlines()[0]


def answer_post(naver, html=HTML):
    naver.respond(M, '/PostView.naver', body=html, content_type='text/html')


def image(naver, host='postfiles.pstatic.net', path=None, **envelope):
    naver.respond(host, path, **{'status': 200, 'content_type': 'image/jpeg', 'body': '',
                                 'b64': base64.b64encode(PICTURE).decode(), **envelope})


def test_images_saves_the_numbered_pictures_and_prints_their_paths(naver, data_dir):
    answer_post(naver)
    image(naver, path='/MjAyNjEw/one.jpg')
    image(naver, host='storep-phinf.pstatic.net', path='/ogq_sample/original_1.png', content_type='image/png')
    code, out, _ = naver.run('naver-blog', 'images', POST, '1', '4')
    assert code == 0, out
    assert 'requests=3' in first_line(out)
    paths = [line.split(' · ')[-2] for line in out.splitlines() if line.startswith('[i')]
    assert len(paths) == 2 and all(p.startswith(str(data_dir / 'images') + '/naver-blog-') for p in paths)
    assert open(paths[0], 'rb').read() == PICTURE and paths[1].endswith('.png')
    assert 'removed once 24 hours old' in out
    assert naver.fetches()[1]['query'] == {'type': 'w800'}


def test_a_saved_picture_is_a_record_with_the_shared_head(naver, data_dir):
    answer_post(naver)
    image(naver, path='/MjAyNjEw/two.jpg')
    code, out, _ = naver.run('naver-blog', 'images', POST, '2', '--json')
    record, = json.loads(out)['results']
    assert (record['kind'], record['id'], record['url'], record['created_at']) == (
        'image', 'image:cafe_note/224000000001#2', 'https://blog.naver.com/cafe_note/224000000001', None)
    assert record['n'] == 2 and record['picture_kind'] == 'photo' and record['caption'] == '창가 자리'
    assert record['bytes'] == len(PICTURE) and record['content_type'] == 'image/jpeg'


def test_images_refuses_numbers_the_post_does_not_have(naver):
    answer_post(naver)
    code, out, _ = naver.run('naver-blog', 'images', POST, '9')
    assert code == 2 and len(naver.fetches()) == 1 and '1-6' in json.loads(out)['fix']


def test_images_without_numbers_or_all_asks_which(naver):
    answer_post(naver)
    code, out, _ = naver.run('naver-blog', 'images', POST)
    assert code == 2 and 'N' in json.loads(out)['fix']


def test_a_post_without_pictures_is_exit_7(naver):
    html = (FIXTURES / 'posts/no_tags.html').read_text(encoding='utf-8')
    answer_post(naver, html)
    code, out, _ = naver.run('naver-blog', 'images', 'notag_blog/5', '--all')
    assert code == 7 and naver.paths() == ['/PostView.naver']


def test_images_all_stops_at_the_time_limit_and_names_the_rest(naver, data_dir):
    answer_post(naver)
    for path in ('/MjAyNjEw/one.jpg', '/MjAyNjEw/two.jpg', '/MjAyNjEw/three.jpg'):
        image(naver, path=path)
    for host, path in (('storep-phinf.pstatic.net', '/ogq_sample/original_1.png'),
                       ('simg.pstatic.net', '/static.map/v2/map/staticmap.bin'),
                       ('shopping-phinf.pstatic.net', '/book/cover.jpg')):
        image(naver, host=host, path=path)
    code, out, _ = naver.run('naver-blog', 'images', POST, '--all', '--json', env={'SNS_DEADLINE_SECONDS': '6'})
    first = json.loads(out)
    saved = len(first['results'])
    assert code == 0 and first['stop_reason'] == 'time_limit' and 0 < saved < 6
    assert [w for w in first['next'].split('images')[1].split() if w != '--json'] == [
        POST, *map(str, range(saved + 1, 7))]
    naver.monkeypatch.delenv('SNS_DEADLINE_SECONDS')   # the pacing the first run left is still owed in the second
    naver.respond(M, '/PostView.naver', body=HTML, content_type='text/html')
    code, out, _ = naver.run(*command_of('more: ' + first['next']), '--json')
    second = json.loads(out)
    assert code == 0 and [r['n'] for r in first['results'] + second['results']] == [1, 2, 3, 4, 5, 6]
    assert 'next' not in second


def test_a_photo_that_is_not_a_picture_is_not_saved_and_all_failing_alike_is_a_changed_contract(naver, data_dir):
    answer_post(naver)
    image(naver, path='/MjAyNjEw/one.jpg', content_type='text/html', b64=None)
    code, out, _ = naver.run('naver-blog', 'images', POST, '1')
    assert code == 6 and not list((data_dir / 'images').glob('*'))


def test_one_missing_photo_does_not_stop_the_others(naver, data_dir):
    answer_post(naver)
    naver.respond('postfiles.pstatic.net', '/MjAyNjEw/one.jpg', status=404, body='', content_type='text/html')
    image(naver, path='/MjAyNjEw/two.jpg')
    code, out, _ = naver.run('naver-blog', 'images', POST, '1', '2')
    assert code == 8 and '[i1] image 2' in out and 'image 1 not saved' in out
    assert 'coverage: incomplete' in out


def test_a_picture_over_ten_megabytes_is_named_and_not_saved(naver, data_dir):
    answer_post(naver)
    image(naver, path='/MjAyNjEw/one.jpg', b64=None, oversize=11 * 1024 * 1024)
    image(naver, path='/MjAyNjEw/two.jpg')
    code, out, _ = naver.run('naver-blog', 'images', POST, '1', '2')
    assert code == 8 and 'image 1 not saved' in out and 'larger than 10 MB' in out and '[i1] image 2' in out


def test_a_picture_hosted_outside_naver_is_named_and_skipped(naver, data_dir):
    html = (FIXTURES / 'posts/smart_partial.html').read_text(encoding='utf-8')
    naver.respond(M, '/PostView.naver', body=html, content_type='text/html')
    image(naver, host='dthumb-phinf.pstatic.net', path='/')
    code, out, _ = naver.run('naver-blog', 'images', 'popup_blog/224000000002', '1', '2')
    assert code == 8 and '[i1] image 2' in out and 'image 1 not saved' in out and 'www.reviewplace.example' in out
    assert 'more:' not in out and [c['args']['host'] for c in naver.calls() if c['op'] == 'naver_blog.fetch'] == [
        'm.blog.naver.com', 'dthumb-phinf.pstatic.net']


def test_saved_photos_older_than_a_day_are_removed_when_the_next_is_saved(naver, data_dir):
    old = data_dir / 'images/old.jpg'
    old.parent.mkdir(parents=True)
    old.write_bytes(b'x')
    past = time.time() - 25 * 3600
    os.utime(old, (past, past))
    answer_post(naver)
    image(naver, path='/MjAyNjEw/one.jpg')
    naver.run('naver-blog', 'images', POST, '1')
    assert not old.exists()
