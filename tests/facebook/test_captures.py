"""Local capture check: real responses saved during reconnaissance (tests/facebook/captures/, never committed).

Skipped when there are no captures. A capture is evidence about Facebook's current shapes; failures here mean the
parser meets a real response it does not read as expected.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from facebook import graphql

CAPTURES = Path(__file__).resolve().parent / 'captures'
NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


def decode(text):
    return [json.loads(line) for line in text.split('\n') if line.strip()]


def feed_captures():
    return sorted(CAPTURES.glob('*newsfeed*.ndjson')) if CAPTURES.exists() else []


@pytest.mark.skipif(not feed_captures(), reason='no local captures')
@pytest.mark.parametrize('path', feed_captures(), ids=lambda p: p.name)
def test_real_feed_pages_read_without_unexpected_issues(path):
    page = graphql.posts_page(decode(path.read_text()), source='newsfeed', connection_key='news_feed', captured_at=NOW)
    assert page.records and page.issues == []
    assert isinstance(page.page_info, dict) and page.page_info.get('has_next_page') is True
    for record in page.records:
        assert record['id'] and record['author_name'] and record['author_url'] and record['created_at']
        assert record['type'] != 'unknown'
        assert record['incomplete'] is False
    photos = [m for r in page.records for m in r['media'] if m['kind'] == 'image' and m['alt']]
    assert photos  # P2: every photo-typed media node carried accessibility_caption; video posters do not


def observed(name):
    path = CAPTURES / f'{name}.json'
    if not path.exists():
        return None
    return [o for o in json.loads(path.read_text())['observed'] if o.get('mode') == 'graphql']


@pytest.mark.skipif(observed('r3_thread') is None, reason='no local captures')
def test_real_permalink_and_comment_pages():
    responses = observed('r3_thread')
    record, issues = graphql.permalink_post(decode(responses[0]['body']), captured_at=NOW)
    assert record and record['text'] and record['author_url'] and record['created_at'] and issues == []
    page = graphql.comments_page(decode(responses[1]['body']), post_id=record['id'], captured_at=NOW)
    assert page.records and page.issues == [] and isinstance(page.page_info, dict)
    assert all(r['depth'] == 0 and r['author_url'] and r['created_at'] for r in page.records)


@pytest.mark.skipif(observed('r3b_replies') is None, reason='no local captures')
def test_real_reply_batches_and_their_cursor():
    responses = observed('r3b_replies')
    parents = graphql.comments_page(decode(responses[1]['body']), post_id='P', captured_at=NOW)
    target = max(parents.records, key=lambda r: r['reply_count'] or 0)
    assert parents.handles[target['id']]['expandable']
    batch = graphql.replies_page(decode(responses[2]['body']), post_id='P', parent_id=target['id'], captured_at=NOW)
    assert len(batch.records) == 10 and all(r['depth'] == 1 and r['parent_id'] == target['id'] for r in batch.records)
    assert batch.page_info['has_next_page'] is True and batch.page_info['end_cursor']
    second = observed('r3c_replies2')
    if second:
        more = graphql.replies_page(decode(second[0]['body']), post_id='P', parent_id=target['id'], captured_at=NOW)
        assert len(more.records) == 10 and not {r['id'] for r in more.records} & {r['id'] for r in batch.records}


@pytest.mark.skipif(observed('r4_search') is None, reason='no local captures')
def test_real_search_pages():
    posts_recent, posts_dated, groups = observed('r4_search')
    for response in (posts_recent, posts_dated):
        page = graphql.search_page(decode(response['body']), vertical='posts', captured_at=NOW)
        assert page.records and all('kind' not in r and r['created_at'] for r in page.records)
        assert page.issues == [] and isinstance(page.page_info, dict)
    page = graphql.search_page(decode(groups['body']), vertical='groups', captured_at=NOW)
    assert page.records and {r['kind'] for r in page.records} == {'group'} and page.issues == []


@pytest.mark.skipif(observed('r5_group_page') is None, reason='no local captures')
def test_real_page_about_overview():
    about = decode(observed('r5_group_page')[4]['body'])
    assert len(graphql.about_collections(about)) >= 3
    fields, issues = graphql.about_fields([about], profile_id='p', collection_names=[None], captured_at=NOW)
    assert fields and issues == []
