"""The parsers over real X responses captured in recon (tests/sns/captures/x/, gitignored, deleted before merge):
nothing raises, records come out with the shared head keys and their identity, and the shapes the fixtures assume are
really there. Runs only when tests/sns/captures/x/ exists."""
import json
from pathlib import Path

import pytest

from sns.x import web as x_web

CAPTURES = Path(__file__).resolve().parents[1] / 'captures' / 'x'
FILES = sorted(CAPTURES.glob('*.json')) if CAPTURES.is_dir() else []
pytestmark = pytest.mark.skipif(not CAPTURES.is_dir() or not FILES, reason='no local captures: tests/sns/captures/x/')


def body(path):
    text = path.read_text()
    return json.loads(text) if text.strip() else None


def instructions(data):
    def find(value):
        if isinstance(value, dict):
            if isinstance(value.get('instructions'), list):
                return value['instructions']
            for child in value.values():
                found = find(child)
                if found is not None:
                    return found
        return None
    return find(data)


HEAD = ('kind', 'id', 'url', 'created_at')


def check_post(record):
    assert all(key in record for key in HEAD), record
    if record.get('unavailable'):
        return
    assert record['id'] and record['url'].startswith('https://x.com/'), record
    assert record['author'] is None or record['author']['username'], record
    if record.get('reposted_post'):
        assert record['text'] == '' and record['reposted_post'].get('id')


@pytest.mark.parametrize('path', [p for p in FILES if not p.name.startswith(('post_', 'r2_', 'r3_article', 'r3_noted',
                                                                             'r3_edit'))], ids=lambda p: p.name)
def test_list_pages(path):
    data = body(path)
    found = instructions(data) if data else None
    if found is None:
        pytest.skip('not a timeline')
    page = x_web.list_page(found)
    for record in page.records:
        assert all(key in record for key in HEAD), record
        if record.get('kind') == 'post':
            check_post(record)
        elif record.get('kind') == 'account':
            assert record['id'] and record['username'], record


@pytest.mark.parametrize('path', [p for p in FILES if p.name.startswith(('post_TweetDetail_p1', 'r2_conv38_p1',
                                                                         'r2_conv4428_p1', 'r3_'))
                                  and 'polls' not in p.name and 'spaces' not in p.name and 'Birdwatch' not in p.name],
                         ids=lambda p: p.name)
def test_post_pages(path):
    data = body(path)
    found = instructions(data)
    focal = next((e['entryId'][6:] for i in found for e in i.get('entries', []) if e['entryId'].startswith('tweet-')),
                 None)
    page = x_web.post_page(found, focal)
    roles = [r['role'] for r in page.records]
    assert roles.count('post') == 1
    for record in page.records:
        check_post(record)
    assert page.coverage['direct_shown'] + page.coverage['nested_shown'] + page.coverage['unavailable'] == \
        roles.count('reply')


def test_the_repost_rows_of_a_profile_are_reposter_acts():
    path = CAPTURES / 'profile_UserTweets.json'
    if not path.exists():
        pytest.skip('no capture')
    records = x_web.list_page(instructions(body(path))).records
    reposts = [r for r in records if r.get('reposted_post')]
    assert reposts and all(r['like_count'] is None and r['text'] == '' for r in reposts)


def test_noted_article_and_edited_posts_carry_their_extras():
    checks = {'r3_noted_p1.json': 'community_note', 'r3_article_p1.json': 'article', 'r3_edit_initial_p1.json': 'edit'}
    for name, key in checks.items():
        path = CAPTURES / name
        if not path.exists():
            continue
        found = instructions(body(path))
        focal = next(e['entryId'][6:] for i in found for e in i.get('entries', []) if e['entryId'].startswith('tweet-'))
        post = next(r for r in x_web.post_page(found, focal).records if r['role'] == 'post' or r['id'] == focal)
        assert post[key], (name, key)
        if key == 'article':
            assert post['article']['text'] and len(post['article']['text']) > 1000


def test_media_of_captured_posts_is_numbered_from_one_and_keeps_a_videos_poster():
    for path in FILES:
        data = body(path)
        found = instructions(data) if data else None
        if found is None:
            continue
        for record in x_web.list_page(found).records:
            for post in (record, record.get('quoted_post') or {}, record.get('reposted_post') or {}):
                items = post.get('media') or []
                assert [m['n'] for m in items] == list(range(1, len(items) + 1)), path.name
                assert all(m['image_url'] for m in items if m['kind'] in ('video', 'gif')), path.name
