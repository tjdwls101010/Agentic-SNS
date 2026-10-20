"""The adapter and the record contract: the platform's policy is the plan's table row, every record the fixtures build
carries the head every platform's records share (kind, id, url, created_at), and every key a record emits is described
by `naver-blog schema <object>` — nothing is emitted undocumented and nothing documented is made up. Another platform's
link given to a Naver command is refused naming the command that reads it, and the other way round."""
import json

import pytest

from sns.naver_blog import CHOICES, COMMANDS, PLATFORM, web
from tests.sns.naver_blog.scene import FIXTURES, fixture
from tests.sns.naver_blog.shapes import clip_items
from tests.sns.support.policies import POLICIES

HEAD = {'kind', 'id', 'url', 'created_at'}
KIND = {'post_read': 'post', 'link': 'link', 'image': 'image'}


def described(name):
    return set(PLATFORM.schemas[name]['fields'])


def built():
    """(object name, record dict) for every record the fixtures and the builders make."""
    found = []
    for case in fixture('records_posts.json')['cases']:
        record = web.post_record(case['raw'], blog_id=(case.get('context') or {}).get('blog_id'))
        found += [('post', record.to_dict())] if record else []
    for case in fixture('records_comments.json')['cases']:
        record = web.comment_record(case['raw'], post_url='https://blog.naver.com/b/1')
        found += [('comment', record.to_dict())] if record else []
    blogs = fixture('records_blogs.json')
    found += [('blog', web.blog_record(c['raw']).to_dict()) for c in blogs['cards'] if web.blog_record(c['raw'])]
    found += [('category', c.to_dict()) for c in web.categories(blogs['categories']['raw'], 'sample_blog')]
    found += [('buddy', web.buddy_record(c['raw']).to_dict()) for c in blogs['buddies'] if web.buddy_record(c['raw'])]
    found += [('topic', t.to_dict()) for t in web.topics(blogs['topics']['raw'])]
    found += [('clip', web.clip_record(raw).to_dict()) for raw in clip_items(2)]
    found += [('keyword', k.to_dict()) for k in web.keyword_records([{'keyword': 'a'}, 'b'])]
    found += [('group', web.group_record({'groupId': 3, 'groupName': 'g'}).to_dict())]
    found += [('link', web.Resolved(id='link:naver.me/x', url='naver.me/x', link='naver.me/x', status=302).to_dict())]
    found += [('image', web.Saved(id='image:b/1#1', url='https://blog.naver.com/b/1', n=1).to_dict())]
    body = fixture('body.json')['full']
    html = (FIXTURES / body['file']).read_text(encoding='utf-8')
    found += [('post_read', web.parse_post(html, **body['request']).to_dict())]
    return found


RECORDS = built()


@pytest.mark.parametrize('name, record', RECORDS, ids=lambda v: v if isinstance(v, str) else v.get('id', ''))
def test_every_record_has_the_shared_head_first_and_only_described_keys(name, record):
    assert list(record)[:4] == ['kind', 'id', 'url', 'created_at'], (name, list(record)[:4])
    assert set(record) == described(name), (name, set(record) ^ described(name))
    assert record['kind'] == KIND.get(name, name)


def test_every_object_schema_describes_its_record_and_the_listing_is_complete():
    assert set(PLATFORM.schemas) == {'post', 'post_read', 'comment', 'blog', 'category', 'buddy', 'topic', 'clip',
                                     'keyword', 'group', 'link', 'image'}
    for name, document in PLATFORM.schemas.items():
        assert document['object'] == name and document['description'] and HEAD <= set(document['fields']), name
        assert all(' — ' in text for text in document['fields'].values()), name


def test_schema_prints_each_object_through_the_cli(naver):
    code, out, _ = naver.run('naver-blog', 'schema')
    assert code == 0 and [r['object'] for r in json.loads(out)['results']] == [
        'result', 'out', 'post', 'post_read', 'comment', 'blog', 'category', 'buddy', 'topic', 'clip', 'keyword', 'group',
        'link', 'image']
    code, out, _ = naver.run('naver-blog', 'schema', 'post_read')
    assert code == 0 and 'viewer_id' not in out and 'coverage' in out


def test_the_platform_adapter_is_the_plans_row():
    assert PLATFORM.policy == POLICIES['naver_blog']
    assert (PLATFORM.key, PLATFORM.word, PLATFORM.title, PLATFORM.site, PLATFORM.transport) == (
        'naver_blog', 'naver-blog', 'Naver Blog', 'blog.naver.com', 'fetch')
    assert PLATFORM.unblock_scope is None and PLATFORM.idle_action is None
    assert PLATFORM.window.tz.utcoffset(None).total_seconds() == 9 * 3600 and PLATFORM.window.tz.tzname(None) == 'KST'


def test_the_commands_are_the_plans_twelve_in_its_order_with_their_closed_sets():
    assert list(COMMANDS) == ['search', 'keywords', 'post', 'comments', 'images', 'resolve', 'blog', 'posts', 'feed',
                              'buddies', 'topic', 'monthly']   # doctor and schema are the shared ones after them
    assert CHOICES == {'search.type': ['posts', 'blogs', 'tags', 'clips'], 'search.sort': ['sim', 'date']}


@pytest.mark.parametrize('argv, names', [
    (['post', 'https://www.reddit.com/r/example/comments/abc123/a_title/'], 'reddit post'),
    (['blog', 'https://www.reddit.com/r/python'], 'reddit sub'),
    (['comments', 'https://www.reddit.com/r/example/comments/abc123/a_title/'], 'reddit post'),
])
def test_another_platforms_link_is_refused_naming_its_command(naver, argv, names):
    code, out, _ = naver.run('naver-blog', *argv)
    envelope = json.loads(out)
    assert code == 2 and 'Reddit link' in envelope['message'] and names in envelope['fix'] and naver.fetches() == []


@pytest.mark.parametrize('argv, names', [
    (['post', 'https://blog.naver.com/sample_blog/224000000001'], 'naver-blog post'),
    (['sub', 'https://blog.naver.com/sample_blog'], 'naver-blog blog'),
    (['post', 'https://naver.me/AbCd12Ef'], 'naver-blog resolve'),
])
def test_a_naver_link_given_to_reddit_is_refused_naming_the_naver_command(naver, argv, names):
    code, out, _ = naver.run('reddit', *argv)
    envelope = json.loads(out)
    assert code == 2 and 'Naver Blog link' in envelope['message'] and names in envelope['fix']
    assert naver.fetches() == []
