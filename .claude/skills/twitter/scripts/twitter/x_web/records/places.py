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


_ROLES = {'NonMember': 'not a member', 'Member': 'member', 'Moderator': 'moderator', 'Admin': 'admin'}


def community_record(node):
    """One X community: its size, how one joins, its topic and rules, and this account's role; None for anything X
    sends in place of a community (a community that does not exist comes back as another __typename, measured)."""
    node = _dict(node)
    ident = _str(node.get('id_str')) or (str(node['rest_id']) if node.get('rest_id') else None)
    if node.get('__typename') != 'Community' or not ident:
        return None
    rules = [_str(_dict(rule).get('name')) for rule in node.get('rules') or []]
    policy = _str(node.get('join_policy'))
    return {'kind': 'community', 'id': ident, 'name': _str(node.get('name')),
            'description': _str(node.get('description')), 'member_count': _count(node.get('member_count')),
            'moderator_count': _count(node.get('moderator_count')), 'created_at': _ms(node.get('created_at')),
            'open_to_join': policy == 'Open' if policy else None, 'join_policy': policy,
            'nsfw': node.get('is_nsfw') if isinstance(node.get('is_nsfw'), bool) else None,
            'your_role': _ROLES.get(node.get('role'), _str(node.get('role'))),
            'topic': _str(_dict(node.get('primary_community_topic')).get('topic_name')),
            'rules': [rule for rule in rules if rule], 'creator': _who(node.get('creator_results')),
            'url': f'{ORIGIN}/i/communities/{ident}'}
