"""X's lists, communities, spaces and notifications as the skill's records (P2 R5, R8 shapes).

Times X sends as milliseconds become UTC ISO like every other record. Each record carries its own x.com url.
"""
from datetime import datetime, timezone

from twitter.x_web.records.posts import ORIGIN, account_record


def _dict(value):
    return value if isinstance(value, dict) else {}


def _str(value):
    return value if isinstance(value, str) and value else None


def _count(value):
    return value if type(value) is int and value >= 0 else None


def _ms(value):
    """Milliseconds since the epoch (an int or a digit string) as UTC ISO, or None."""
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if type(value) is not int or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _who(node):
    """The account behind a nested user result, in brief: id, username and name."""
    record = account_record(_dict(_dict(node).get('result')))
    if record.get('unavailable') or not record.get('username'):
        return None
    return {'id': record.get('id'), 'username': record['username'], 'name': record.get('name')}


def list_record(node):
    """One X list: who made it, how many members and followers, and whether this account follows it; None for X's
    stub of a list that does not exist."""
    node = _dict(node)
    ident = _str(node.get('id_str')) or (str(node['rest_id']) if node.get('rest_id') else None)
    if not ident or not _str(node.get('name')):
        return None  # X answers a list that does not exist with a stub: an id and nothing else (measured)
    mode = _str(node.get('mode'))
    return {'kind': 'list', 'id': ident, 'name': _str(node.get('name')), 'description': _str(node.get('description')),
            'private': mode.lower() == 'private' if mode else None, 'member_count': _count(node.get('member_count')),
            'follower_count': _count(node.get('subscriber_count')), 'created_at': _ms(node.get('created_at')),
            'owner': _who(node.get('user_results')),
            'you_follow': node.get('following') if isinstance(node.get('following'), bool) else None,
            'you_are_member': node.get('is_member') if isinstance(node.get('is_member'), bool) else None,
            'url': f'{ORIGIN}/i/lists/{ident}'}
