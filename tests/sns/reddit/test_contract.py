"""The record contract: every record the fixtures build carries the head every platform's records share (kind, id, url,
created_at), and every key a record emits is described by `reddit schema <object>` — nothing is emitted undocumented and
nothing documented is made up."""
import json

import pytest

from sns.reddit import PLATFORM
from sns.reddit import web
from tests.sns.reddit.scene import fixture
from tests.sns.reddit.shapes import pair, t1

HEAD = {'kind', 'id', 'url', 'created_at'}


def described(object_name):
    """The key names a schema document lists (its field names may group several: 'kind, id, url')."""
    return {name.strip() for key in PLATFORM.schemas[object_name]['fields'] for name in key.split(',')}


def built():
    """(object name, record) for every record the record fixtures build, plus a comment-link page's context rows."""
    found = []
    for name, convert in (('records_posts.json', lambda c: ('post', web.post(c['raw']))),
                          ('records_comments.json', lambda c: ('comment', web.comment(c['raw'])))):
        data = fixture(name)
        found += [convert(case) for case in data['cases'] + data.get('after_recon', {}).get('cases', [])]
    data = fixture('records_entities.json')
    for case in data['cases'] + data.get('after_recon', {}).get('cases', []):
        raw = case['raw']
        found.append({'t5': lambda: ('subreddit', web.community(raw)), 't2': lambda: ('user', web.user(raw)),
                      't3': lambda: ('post', web.post(raw)), 'moderator': lambda: ('moderator', web.moderator(raw)),
                      'wiki_page': lambda: ('wiki_page', web.wiki_page(raw['subreddit'], raw['page'], raw['data'])),
                      'wiki_index': lambda: ('wiki_index', web.wiki_index(raw['subreddit'], raw['data'])),
                      'rule': lambda: ('rule', None)}[case['kind']]())
    found.append(('reply', web.reply({'id': 'm1', 'name': 't1_m1', 'author': 'a', 'body': 'b', 'type': 'comment_reply',
                                      'context': '/r/x/comments/p/t/m1/?context=3', 'created_utc': 1792000000,
                                      'link_title': 'T', 'subreddit': 'x', 'parent_id': 't1_p', 'new': True})))
    return [(name, record) for name, record in found if record is not None]


RECORDS = built()


@pytest.mark.parametrize('name, record', RECORDS, ids=lambda v: v if isinstance(v, str) else v.get('id', ''))
def test_every_record_has_the_shared_head_and_only_described_keys(name, record):
    assert HEAD <= set(record), (name, HEAD - set(record))
    assert set(record) <= described(name), (name, set(record) - described(name))
    assert record['kind'] == name


def test_the_nested_pieces_use_the_names_their_description_gives():
    post = web.post({'id': 'a', 'is_gallery': True, 'gallery_data': {'items': [{'media_id': 'm'}]},
                     'media_metadata': {'m': {'e': 'Image', 's': {'u': 'https://i.redd.it/m.jpg', 'x': 1, 'y': 2}}}})
    media_text = PLATFORM.schemas['post']['fields']['media']
    assert all(key in media_text for key in post['media'][0]), set(post['media'][0])
    cross = web.post({'id': 'c', 'crosspost_parent_list': [{'id': 'o', 'name': 't3_o'}]})
    assert set(cross['crosspost']) <= described('post') and HEAD <= set(cross['crosspost'])


def test_a_comment_pages_extra_keys_are_described():
    _post, items = web.thread(pair([t1('c1', 't3_aaa1')]))
    record = {**items[0]['record'], 'context': True, 'anchor': True}
    assert set(record) <= described('comment')


def test_every_object_schema_describes_something_and_names_its_label():
    assert set(PLATFORM.schemas) == {'post', 'reply', 'comment', 'subreddit', 'user', 'moderator', 'wiki_page',
                                     'wiki_index', 'image'}
    for name, document in PLATFORM.schemas.items():
        assert document['object'] == name and document['fields'] and document['description'], name


def test_schema_prints_each_object_through_the_cli(reddit):
    code, out, _ = reddit.run('reddit', 'schema')
    assert code == 0 and [r['object'] for r in json.loads(out)['results']] == [
        'result', 'out', 'post', 'reply', 'comment', 'subreddit', 'user', 'moderator', 'wiki_page', 'wiki_index',
        'image']
    code, out, _ = reddit.run('reddit', 'schema', 'post')
    assert code == 0 and 'media_id' in json.dumps(json.loads(out)['results'][0])
