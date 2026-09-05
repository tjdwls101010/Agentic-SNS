"""CSRF cache bound to the viewer cookie; never read auth_token."""
import json
import re
import time
from urllib.parse import unquote
from ._blocked import account_lock, cache_dir, read_state, write_state
from ._errors import TwitterError


def viewer_from_twid(value):
    match = re.fullmatch(r'u=(\d+)', unquote(value or '').strip('"'))
    return match[1] if match else None


def ensure(transport, force=False, personal=False):
    session = read_state('session.json')
    if not force and session.get('ct0') and session.get('viewer_id') and (not personal or time.time() - session.get('read_at', 0) < 86400):
        return session
    try:
        body = json.loads(transport.auxiliary('cookie', {})['body'])
        viewer = viewer_from_twid(body.get('twid'))
        if not body.get('ct0') or not viewer:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise TwitterError(4, 'No usable X session was found.', 'Log in to x.com in Aside, then run doctor.') from None
    with account_lock():
        prior = read_state('session.json')
        changed = prior.get('viewer_id') is not None and prior['viewer_id'] != viewer
        if changed:
            for path in (cache_dir() / 'cursors').glob('*.json'):
                path.unlink()
        session = dict(ct0=body['ct0'], viewer_id=viewer, viewer_handle=None if changed else prior.get('viewer_handle'), read_at=time.time())
        write_state('session.json', session)
        transport.changed_viewer = changed
    return session
