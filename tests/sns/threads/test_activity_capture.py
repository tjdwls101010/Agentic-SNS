"""The activity list's local recon capture is never committed; it runs independently of the older capture set."""
import json
from pathlib import Path

import pytest

from sns.threads import web

CAPTURE = Path(__file__).resolve().parents[1] / 'captures/threads/d2_first.json'


@pytest.mark.skipif(not CAPTURE.exists(), reason='no local activity capture')
def test_real_activity_list_parses_with_the_shared_head_and_no_issues():
    page = web.notifications_page(json.loads(CAPTURE.read_text())['data'])
    assert page.records
    assert all(list(record)[:4] == ['kind', 'id', 'url', 'created_at'] for record in page.records)
    assert all(record['kind'] == 'notification' and record['id'] for record in page.records)
    assert not getattr(page, 'issues', [])
