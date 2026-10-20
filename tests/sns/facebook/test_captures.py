"""The parsers over real Facebook responses captured in recon (tests/sns/captures/facebook/, gitignored, deleted before
merge): nothing raises, records come out with the shared head keys and their identity, and the shapes the fixtures
assume are really there. Runs only when tests/sns/captures/facebook/ exists."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sns.facebook import web

CAPTURES = Path(__file__).resolve().parents[1] / 'captures' / 'facebook'
NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)
HEAD = ('kind', 'id', 'url', 'created_at')
pytestmark = pytest.mark.skipif(not CAPTURES.is_dir(), reason='no local captures: tests/sns/captures/facebook/')


def decode(text):
    return [json.loads(line) for line in text.split('\n') if line.strip()]


def feed_captures():
    return sorted(CAPTURES.glob('*newsfeed*.ndjson')) if CAPTURES.exists() else []


def observed(name):
    path = CAPTURES / f'{name}.json'
    if not path.exists():
        return None
    return [o for o in json.loads(path.read_text())['observed'] if o.get('mode') == 'graphql']


@pytest.mark.skipif(not feed_captures(), reason='no local feed captures')
@pytest.mark.parametrize('path', feed_captures(), ids=lambda p: p.name)
def test_real_feed_pages_read_without_unexpected_issues(path):
    page = web.posts_page(decode(path.read_text()), source='newsfeed', connection_key='news_feed', captured_at=NOW)
    assert page.records and page.issues == []
    assert isinstance(page.page_info, dict) and page.page_info.get('has_next_page') is True
    for record in page.records:
        assert all(key in record for key in HEAD)
        assert record['id'] and record['author_name'] and record['author_url'] and record['created_at']
        assert record['type'] != 'unknown' and record['incomplete'] is False
        for number, item in enumerate(record['media'], 1):
            assert item['n'] == number and item['kind'] in ('photo', 'video') and (item['image_url'] or item['video_url'])
    photos = [m for r in page.records for m in r['media'] if m['kind'] == 'photo' and m['alt']]
    assert photos  # every photo-typed media node carried accessibility_caption; video posters do not


@pytest.mark.skipif(observed('r3_thread') is None, reason='no local thread captures')
def test_real_permalink_and_comment_pages():
    responses = observed('r3_thread')
    record, issues = web.permalink_post(decode(responses[0]['body']), captured_at=NOW)
    assert record and record['text'] and record['author_url'] and record['created_at'] and issues == []
    page = web.comments_page(decode(responses[1]['body']), post_id=record['id'], captured_at=NOW)
    assert page.records and page.issues == [] and isinstance(page.page_info, dict)
    assert all(r['kind'] == 'comment' and r['depth'] == 0 and r['author_url'] and r['created_at'] for r in page.records)


@pytest.mark.skipif(observed('r3b_replies') is None, reason='no local reply captures')
def test_real_reply_batches_and_their_cursor():
    responses = observed('r3b_replies')
    parents = web.comments_page(decode(responses[1]['body']), post_id='P', captured_at=NOW)
    target = max(parents.records, key=lambda r: r['reply_count'] or 0)
    assert parents.handles[target['id']]['expandable']
    batch = web.replies_page(decode(responses[2]['body']), post_id='P', parent_id=target['id'], captured_at=NOW)
    assert len(batch.records) == 10 and all(r['depth'] == 1 and r['parent_id'] == target['id'] for r in batch.records)
    assert batch.page_info['has_next_page'] is True and batch.page_info['end_cursor']


@pytest.mark.skipif(observed('r4_search') is None, reason='no local search captures')
def test_real_search_pages():
    posts_recent, posts_dated, groups = observed('r4_search')
    for response in (posts_recent, posts_dated):
        page = web.search_page(decode(response['body']), vertical='posts', captured_at=NOW)
        assert page.records and all(r['kind'] == 'post' and r['created_at'] for r in page.records)
        assert page.issues == [] and isinstance(page.page_info, dict)
    page = web.search_page(decode(groups['body']), vertical='groups', captured_at=NOW)
    assert page.records and {r['kind'] for r in page.records} == {'group'} and page.issues == []


@pytest.mark.skipif(observed('r5_group_page') is None, reason='no local About captures')
def test_real_page_about_overview_and_group_header_card():
    about = decode(observed('r5_group_page')[4]['body'])
    assert len(web.about_collections(about)) >= 3
    fields, issues = web.about_fields([about], profile_id='p', collection_names=[None], captured_at=NOW)
    assert fields and issues == [] and all(f['kind'] == 'about' and f['id'] for f in fields)
    header = decode(observed('r5_group_page')[0]['body'])
    card, issues = web.group_card(header, group_id=header[0]['data']['group']['id'], captured_at=NOW)
    assert card and card['name'] and card['privacy'] and card['privacy_icon'] and card['member_count_text']
    assert card['join_state'] and issues == []


@pytest.mark.skipif(not (CAPTURES / 'p4_group_about_response.ndjson').exists(), reason='no local group About capture')
def test_real_group_about_details():
    details, issues = web.group_about(decode((CAPTURES / 'p4_group_about_response.ndjson').read_text()))
    assert details['description'] and details['privacy_description'] and details['rules']
    assert all(rule['title'] for rule in details['rules'])
    assert isinstance(details['posts_last_day'], int) and details['created_at'] and details['member_count_text']
    assert issues == []
