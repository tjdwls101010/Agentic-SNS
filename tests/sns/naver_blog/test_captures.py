"""Real answers captured during recon (tests/sns/captures/naver_blog_*.json, local only, never committed: they hold real
people's names): the readers turn them into records without an unexpected error. Skipped when there is no capture."""
import json
from pathlib import Path

import pytest

from sns.naver_blog import web

NEWS = Path(__file__).resolve().parents[1] / 'captures' / 'naver_blog_news.json'


@pytest.mark.skipif(not NEWS.exists(), reason='no local capture of the news list')
def test_the_captured_news_list_reads_to_records():
    bodies = json.loads(NEWS.read_text(encoding='utf-8'))['bodies']
    url, captured = next((url, body) for url, body in bodies.items() if '/ajax/NewsList.naver' in url)
    payload = web.classify('news', {'status': captured.get('status', 200), 'url': url, 'location': None,
                                    'content_type': 'application/json', 'body': captured['text'], 'b64': None})
    rows = web.at(payload, 'result.list')
    records = [record.to_dict() for record in map(web.news_record, rows) if record]
    assert len(records) == len(rows)
    for record in records:
        assert record['kind'] == 'news' and record['id'] and record['created_at']
        assert isinstance(record['category'], str) and isinstance(record['read'], bool)
        assert record['url'] and record['author']['name'] and record['title']
