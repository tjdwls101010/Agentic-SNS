"""Who the browser is logged in as, cached because asking costs a request.

Naver has no token to refresh, so a session here is only an identity: which account the
Aside browser is signed into. It matters because continuation handles are page numbers
into that account's view of a surface, and another account's view is a different one.
"""
import json
import re
import shutil
import time

from ._budget import account_lock, cache_dir, write_state
from ._errors import NaverBlogError

TTL = 12 * 3600
# The mobile feed page links to the viewer's own buddy list; that link is where the id lives.
VIEWER_LINK = re.compile(r'href="/BuddyList\.naver\?blogId=([A-Za-z0-9_-]{1,64})"')
VIEWER_VAR = re.compile(r'var\s+userId\s*=\s*"([A-Za-z0-9_-]{1,64})"')


def read_viewer(html, *, source):
    """source 'feed' demands the buddy-list link; 'post' takes the viewer variable if present."""
    if source == 'post':
        match = VIEWER_VAR.search(html)
        return match[1] if match else None
    match = VIEWER_LINK.search(html)
    if not match:
        # A maintenance page and a redesign look identical here, and neither proves a logout.
        raise NaverBlogError(6, 'The feed page did not identify the logged-in account.',
                             'Open Naver Blog in Aside and confirm it is signed in, then run doctor.',
                             error='envelope_drift')
    return match[1]


def load():
    try:
        record = json.loads((cache_dir() / 'session.json').read_text())
        if (not isinstance(record.get('viewer_id'), str) or not record['viewer_id']
                or type(record.get('read_at')) not in (int, float)):
            raise ValueError
        return record
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def store(viewer_id, *, account='u0'):
    """A different viewer invalidates every page-number handle: they mean another account's view."""
    with account_lock():
        previous = load()
        write_state('session.json', {'viewer_id': viewer_id, 'read_at': time.time(), 'account': account})
        if previous and previous['viewer_id'] != viewer_id:
            shutil.rmtree(cache_dir() / 'cursors', ignore_errors=True)
    return viewer_id


def cached_viewer():
    record = load()
    if record and time.time() - record['read_at'] < TTL:
        return record['viewer_id']
    return None


def ensure(transport):
    """Return the viewer id, spending one request only when the cache is absent or stale."""
    viewer = cached_viewer()
    if viewer:
        return viewer
    html = transport.get('feed_html')
    return store(read_viewer(html, source='feed'))


def note_viewer(html):
    """Post HTML already names the viewer, so reading one refreshes the session for free."""
    viewer = read_viewer(html, source='post')
    if viewer:
        store(viewer)
    return viewer
