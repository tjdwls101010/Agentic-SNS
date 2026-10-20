"""reddit images: a post read again lightly (one request), then each chosen picture fetched from Reddit's image hosts."""
import base64
import json

from tests.sns.reddit.shapes import pair

GALLERY = {'is_gallery': True, 'is_self': False,
           'gallery_data': {'items': [{'media_id': 'g1', 'caption': 'first'}, {'media_id': 'g2'}]},
           'media_metadata': {'g1': {'e': 'Image', 'm': 'image/jpg', 's': {'u': 'https://preview.redd.it/g1.jpg?s=SIG',
                                                                            'x': 640, 'y': 480}},
                              'g2': {'e': 'Image', 'm': 'image/png', 's': {'u': 'https://i.redd.it/g2.png', 'x': 10,
                                                                            'y': 10}}}}


def picture(reddit, url, data=b'\xff\xd8\xff\xe0jpg', content_type='image/jpeg'):
    reddit.browser.respond('aside.media', {'status': 200, 'type': content_type, 'size': len(data),
                                           'data': base64.b64encode(data).decode()}, url=url)


def test_a_gallerys_chosen_pictures_are_saved(reddit, data_dir):
    reddit.json('/comments/aaa1.json', pair([], **GALLERY), query={'limit': 1})
    picture(reddit, 'https://i.redd.it/g2.png', b'\x89PNG..', 'image/png')
    code, out, _ = reddit.run('reddit', 'images', 'https://www.reddit.com/r/example/comments/aaa1/a_title/', '2')
    assert code == 0, out
    assert '[i1] [image 2] photo' in out and f'saved: {data_dir / "images"}' in out
    assert reddit.paths()[0] == '/comments/aaa1.json'


def test_all_saves_every_picture_of_the_post(reddit, data_dir):
    reddit.json('/comments/aaa1.json', pair([], **GALLERY))
    picture(reddit, 'https://preview.redd.it/g1.jpg?s=SIG')
    picture(reddit, 'https://i.redd.it/g2.png', b'\x89PNG..', 'image/png')
    code, out, _ = reddit.run('reddit', 'images', 'aaa1', '--all', '--json')
    records = json.loads(out)['results']
    assert code == 0 and [(r['n'], r['content_type']) for r in records] == [(1, 'image/jpeg'), (2, 'image/png')]


def test_a_post_without_pictures_is_explicitly_empty(reddit, data_dir):
    reddit.json('/comments/aaa1.json', pair([]))
    code, out, _ = reddit.run('reddit', 'images', 'aaa1', '--all')
    assert code == 7
