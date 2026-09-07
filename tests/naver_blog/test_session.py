"""A session here is only an identity, and a changed identity invalidates page handles."""
import json
import time

import pytest

from naver_blog_skill import _session
from naver_blog_skill._budget import cache_dir
from naver_blog_skill._errors import NaverBlogError

FEED = '<a href="/BuddyList.naver?blogId=testviewer">내 이웃</a>'


def test_the_feed_page_names_the_logged_in_account():
    assert _session.read_viewer(FEED, source='feed') == 'testviewer'


def test_a_feed_page_without_the_link_is_a_shape_change_and_not_a_logout():
    # A maintenance page and a redesign look exactly like this; neither proves the account is out.
    with pytest.raises(NaverBlogError) as caught:
        _session.read_viewer('<html><body>점검 중입니다</body></html>', source='feed')
    assert caught.value.code == 6 and caught.value.error == 'envelope_drift'


def test_post_html_refreshes_the_session_without_spending_a_request():
    assert _session.note_viewer('var userId = "testviewer";') == 'testviewer'
    assert _session.cached_viewer() == 'testviewer'


def test_post_html_from_a_logged_out_read_simply_says_nothing():
    assert _session.note_viewer('<html>no variables here</html>') is None


def test_a_fresh_session_is_reused_and_a_stale_one_is_not():
    _session.store('testviewer')
    assert _session.cached_viewer() == 'testviewer'
    record = json.loads((cache_dir() / 'session.json').read_text())
    record['read_at'] = time.time() - _session.TTL - 1
    (cache_dir() / 'session.json').write_text(json.dumps(record))
    assert _session.cached_viewer() is None


def test_a_different_viewer_discards_every_continuation_handle():
    _session.store('firstaccount')
    cursors = cache_dir() / 'cursors'
    cursors.mkdir(parents=True, exist_ok=True)
    (cursors / '1.json').write_text('{}')
    _session.store('secondaccount')
    # Page numbers mean a position in that account's view of a surface, so they cannot carry over.
    assert not (cursors / '1.json').exists()


def test_the_same_viewer_keeps_its_handles():
    _session.store('testviewer')
    cursors = cache_dir() / 'cursors'
    cursors.mkdir(parents=True, exist_ok=True)
    (cursors / '1.json').write_text('{}')
    _session.store('testviewer')
    assert (cursors / '1.json').exists()


def test_a_corrupt_session_file_is_treated_as_absent():
    cache_dir().mkdir(parents=True, exist_ok=True)
    (cache_dir() / 'session.json').write_text('{ not json')
    assert _session.cached_viewer() is None
