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
