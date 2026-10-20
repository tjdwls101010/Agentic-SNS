"""threads images: the post read again, then each chosen picture fetched from Threads' image hosts and saved."""
import base64
import json

from tests.sns.threads.scenes import known_tab, query_result, run
from tests.sns.threads.test_cli_thread import URL, post_page

CAROUSEL = [{'pk': '701', 'media_type': 1,
             'image_versions2': {'candidates': [{'url': 'https://scontent-x.cdninstagram.com/one.jpg?oh=S', 'width': 10,
                                                 'height': 10}]}},
            {'pk': '702', 'media_type': 2,
             'image_versions2': {'candidates': [{'url': 'https://scontent-x.cdninstagram.com/poster.jpg', 'width': 20,
                                                 'height': 20}]},
             'video_versions': [{'url': 'https://scontent-x.cdninstagram.com/two.mp4', 'width': 40, 'height': 40}]}]


def scripted(browser, carousel=CAROUSEL):
    known_tab(browser)
    bodies = post_page()
    media = bodies[0]['data']['media']
    if carousel is not None:
        media['media_type'] = 8
        media['carousel_media'] = carousel
    for body in bodies:
        browser.respond('threads.query', query_result(body))


def picture(browser, url, data=b'\xff\xd8\xff\xe0jpg'):
    browser.respond('aside.media', {'status': 200, 'type': 'image/jpeg', 'size': len(data),
                                    'data': base64.b64encode(data).decode()}, url=url)


def test_a_chosen_picture_of_a_carousel_is_saved(browser, data_dir):
    scripted(browser)
    picture(browser, 'https://scontent-x.cdninstagram.com/poster.jpg')
    code, out, _ = run(browser, 'images', URL, '2')
    assert code == 0, out
    assert '[i1] [image 2] video poster' in out and f'saved: {data_dir / "images"}' in out


def test_all_and_json(browser, data_dir):
    scripted(browser)
    picture(browser, 'https://scontent-x.cdninstagram.com/one.jpg?oh=S')
    picture(browser, 'https://scontent-x.cdninstagram.com/poster.jpg')
    code, out, _ = run(browser, 'images', URL, '--all', '--json')
    assert code == 0 and [(r['n'], r['media_id']) for r in json.loads(out)['results']] == [(1, '701'), (2, '702')]


def test_numbers_or_all_must_be_given(browser, data_dir):
    code, out, _ = run(browser, 'images', URL)
    assert code == 2
