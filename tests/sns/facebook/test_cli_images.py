"""facebook images: the post read again, then each chosen picture fetched from Facebook's image hosts and saved."""
import base64
import json

from tests.sns.facebook.scenes import known_tab, page_result, query_result, run, story
from tests.sns.facebook.test_cli_thread import URL

ALBUM = [{'media': {'__typename': 'Photo', 'id': 'M1', 'accessibility_caption': 'May be an image of a cat',
                    'image': {'uri': 'https://scontent-x.xx.fbcdn.net/a1.jpg?oh=S', 'width': 1280, 'height': 720}}},
         {'media': {'__typename': 'Video', 'id': 'M2', 'is_playable': True,
                    'image': {'uri': 'https://scontent-x.xx.fbcdn.net/poster.jpg', 'width': 640, 'height': 360}}}]


def scripted(browser, album=ALBUM):
    known_tab(browser)
    root = story('P1')
    root['__typename'] = 'Story'
    if album:
        root['attachments'] = [{'styles': {'attachment': {'all_subattachments': {'nodes': album}}}}]
    browser.respond('facebook.page', page_result(URL, '<script>{"storyID":"UzpfSTE6Mg=="}</script>'))
    browser.respond('facebook.query', query_result(json.dumps({'data': {'node_v2': root}})),
                    name='CometSinglePostDialogContentQuery')


def picture(browser, url, data=b'\xff\xd8\xff\xe0jpg'):
    browser.respond('aside.media', {'status': 200, 'type': 'image/jpeg', 'size': len(data),
                                    'data': base64.b64encode(data).decode()}, url=url)


def test_a_chosen_picture_of_an_album_is_saved_without_reading_comments(browser, data_dir):
    scripted(browser)
    picture(browser, 'https://scontent-x.xx.fbcdn.net/poster.jpg')
    code, out, _ = run(browser, 'images', URL, '2')
    assert code == 0, out
    assert '[i1] [image 2] video poster · 640x360' in out and f'saved: {data_dir / "images"}' in out
    assert [c['args']['name'] for c in browser.calls() if c['op'] == 'facebook.query'] == [
        'CometSinglePostDialogContentQuery']


def test_all_and_json(browser, data_dir):
    scripted(browser)
    picture(browser, 'https://scontent-x.xx.fbcdn.net/a1.jpg?oh=S')
    picture(browser, 'https://scontent-x.xx.fbcdn.net/poster.jpg')
    code, out, _ = run(browser, 'images', URL, '--all', '--json')
    assert code == 0 and [(r['n'], r['media_id']) for r in json.loads(out)['results']] == [(1, 'M1'), (2, 'M2')]


def test_the_post_media_line_numbers_each_picture(browser):
    scripted(browser)
    browser.respond('facebook.query', query_result(json.dumps({'data': {'node': {
        '__typename': 'Feedback', 'comment_rendering_instance_for_feed_location': {'comments': {
            'edges': [], 'page_info': {'has_next_page': False, 'end_cursor': None}}}}}})),
                    name='CommentListComponentsRootQuery')
    code, out, _ = run(browser, 'post', URL)
    assert code == 0, out
    assert 'media: [image 1] photo alt="May be an image of a cat" · [image 2] video' in out


def test_numbers_or_all_must_be_given(browser, data_dir):
    code, out, _ = run(browser, 'images', URL)
    assert code == 2
