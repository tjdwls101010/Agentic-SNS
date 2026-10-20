"""x images: a post read again by id (one request), then each chosen picture fetched from X's image host and saved."""
import base64
import json
import time

from tests.sns.x.scenes import known_tab, queries, query_result, run

A = {'__typename': 'User', 'rest_id': '1000000001', 'core': {'screen_name': 'author_a', 'name': 'A'}}
RATE = {'x-rate-limit-limit': '300', 'x-rate-limit-remaining': '299', 'x-rate-limit-reset': str(int(time.time()) + 900)}
PHOTO = {'type': 'photo', 'id_str': '11', 'media_key': '3_11', 'media_url_https': 'https://pbs.twimg.com/media/P1.jpg',
         'original_info': {'width': 800, 'height': 600}, 'ext_alt_text': 'a chart'}
VIDEO = {'type': 'video', 'id_str': '12', 'media_key': '7_12', 'media_url_https': 'https://pbs.twimg.com/ext_tw_video_thumb/12/pu/img/V.jpg',
         'original_info': {'width': 1280, 'height': 720},
         'video_info': {'variants': [{'content_type': 'video/mp4', 'bitrate': 832000, 'url': 'https://video.twimg.com/v.mp4'}]}}


def tweet(media):
    return {'__typename': 'Tweet', 'rest_id': '201', 'core': {'user_results': {'result': A}},
            'legacy': {'full_text': 'look', 'created_at': 'Thu Oct 15 10:00:00 +0000 2026',
                       'extended_entities': {'media': media}, 'entities': {'media': media}}}


def batch(media):
    return query_result({'data': {'tweetResult': [{'result': tweet(media)}]}}, headers=RATE)


def picture(browser, url, data=b'\xff\xd8\xff\xe0jpg'):
    browser.respond('aside.media', {'status': 200, 'type': 'image/jpeg', 'size': len(data),
                                    'data': base64.b64encode(data).decode()}, url=url)


def test_the_chosen_pictures_are_saved_and_named(browser, data_dir):
    known_tab(browser).respond('x.query', batch([PHOTO, VIDEO]))
    picture(browser, 'https://pbs.twimg.com/ext_tw_video_thumb/12/pu/img/V.jpg')
    code, out, _ = run(browser, 'images', 'https://x.com/author_a/status/201', '2')
    assert code == 0, out
    assert out.splitlines()[0].startswith('x images · 1 shown')
    line = next(line for line in out.splitlines() if line.startswith('[i1]'))
    assert '[image 2]' in line and 'video poster' in line and f'saved: {data_dir / "images"}' in out
    [query] = queries(browser)
    assert query['args']['name'] == 'TweetResultsByRestIds' and query['args']['variables']['tweetIds'] == ['201']


def test_all_saves_every_picture_and_json_names_each(browser, data_dir):
    known_tab(browser).respond('x.query', batch([PHOTO, VIDEO]))
    picture(browser, 'https://pbs.twimg.com/media/P1.jpg')
    picture(browser, 'https://pbs.twimg.com/ext_tw_video_thumb/12/pu/img/V.jpg')
    code, out, _ = run(browser, 'images', '201', '--all', '--json')
    records = json.loads(out)['results']
    assert code == 0 and [(r['n'], r['media_kind'], r['media_id']) for r in records] == [(1, 'photo', '11'),
                                                                                         (2, 'video', '12')]
    assert records[0]['alt'] == 'a chart'


def test_a_number_the_post_does_not_have_is_named_and_partial(browser, data_dir):
    known_tab(browser).respond('x.query', batch([PHOTO]))
    code, out, _ = run(browser, 'images', '201', '4')
    browser_calls = [c for c in browser.calls() if c['op'] == 'aside.media']
    assert code == 8 and 'picture 4: this post has 1' in out and len(browser_calls) == 0


def test_numbers_or_all_must_be_given(browser, data_dir):
    code, out, _ = run(browser, 'images', '201')
    assert code == 2 and '--all' in json.loads(out)['fix']


def test_post_text_numbers_the_pictures_images_takes(browser, data_dir):
    known_tab(browser).respond('x.query', batch([PHOTO, VIDEO]))
    code, out, _ = run(browser, 'post', '201', '202')
    assert '[image 1] photo alt="a chart" · [image 2] video' in out
