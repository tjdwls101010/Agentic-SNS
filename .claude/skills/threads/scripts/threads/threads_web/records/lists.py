"""Connections: where a surface's records sit in a response, how it pages, and the relations inside one unit.

A unit (one edge) can carry several posts: a post and a reply to it, or an author continuing their own post. They stay
one group, and each later post says what it is to the post it answers, so it never reads as an unrelated post.
"""
from dataclasses import dataclass, field

from threads.errors import ThreadsError
from threads.threads_web.records.posts import post_record, user_record

RELAY, OFFSET, CAPPED, SINGLE = 'relay', 'offset', 'capped', 'single_batch'
# surface → (path from data to the connection, path from an edge node to its thread items or None for users, policy)
SURFACES = {
    'feed': ('feedData', 'text_post_app_thread.thread_items', RELAY),
    'profile_tab': ('mediaData', 'thread_items', RELAY),
    'search_posts': ('searchResults', 'thread.thread_items', RELAY),
    'search_accounts': ('xdt_api__v1__users__search_connection', None, SINGLE),
    'followers': ('user.followers', None, CAPPED),
    'following': ('user.following', None, OFFSET),
    'following_more': ('fetch__XDTUserDict.following', None, OFFSET),
    'liked': ('xdt_text_app_viewer.liked_media', 'thread_items', SINGLE),
    'saved': ('xdt_text_app_viewer.saved_media', 'thread_items', SINGLE),
}
_CHANGED = 'Threads changed this response; the skill needs an update.'


@dataclass
class Page:
    records: list = field(default_factory=list)
    groups: list = field(default_factory=list)
    has_next: bool = False
    cursor: str | None = None
    stop: str = 'exhausted'          # the natural stop when this page is the last: exhausted, server_capped, not_paginable
    reported_total: int | None = None


def _changed(message):
    return ThreadsError(6, message, _CHANGED, reason='shape_changed')


def _at(value, path):
    for key in path.split('.'):
        if not isinstance(value, dict) or key not in value:
            raise _changed('A response is missing ' + path + '.')
        value = value[key]
    return value


def relate(group):
    """Give each later post of a unit its relation to the earlier post it answers, and its depth under it."""
    seen = {}
    for record in group:
        target = seen.get(record.get('reply_to_id')) if record.get('id') != record.get('reply_to_id') else None
        if target is not None:
            same = (record.get('author') or {}).get('id') == (target.get('author') or {}).get('id') is not None
            record['relation'] = {'kind': 'continuation' if same else 'reply', 'to': target['id']}
            record['depth'] = target.get('depth', 0) + 1
        if record.get('id'):
            seen[record['id']] = record
    return group


def connection_page(data, surface):
    """One page of `surface` from a response's data: records grouped by unit, and how it continues."""
    root, items, policy = SURFACES[surface]
    connection = _at(data, root)
    if not isinstance(connection, dict) or not isinstance(connection.get('edges'), list):
        raise _changed('A list response has no explicit edges.')
    page = Page(stop={CAPPED: 'server_capped', SINGLE: 'not_paginable'}.get(policy, 'exhausted'))
    if policy in (RELAY, OFFSET):
        info = connection.get('page_info')
        if not isinstance(info, dict) or type(info.get('has_next_page')) is not bool:
            raise _changed('A list response has no page_info.has_next_page.')
        page.has_next, page.cursor = info['has_next_page'], info.get('end_cursor')
        if page.has_next and (not isinstance(page.cursor, str) or not page.cursor):
            raise _changed('A continuing list page has no cursor.')
        if policy == OFFSET and page.has_next and not page.cursor.isdigit():
            raise _changed('A following page cursor is not an offset.')
    if policy == CAPPED:
        counts = data.get('counts') if isinstance(data.get('counts'), dict) else {}
        page.reported_total = counts.get('followers') if type(counts.get('followers')) is int else None
    for edge in connection['edges']:
        node = edge.get('node') if isinstance(edge, dict) else None
        if not isinstance(node, dict):
            raise _changed('A list edge has no node.')
        if items is None:
            record = user_record(node)
            if record is None:
                raise _changed('An account in a list has no identity.')
            group = [record]
        else:
            raw_items = _at(node, items)
            if not isinstance(raw_items, list):
                raise _changed('A list unit has no thread items.')
            group = []
            for item in raw_items:
                record = post_record(_at(item, 'post') if isinstance(item, dict) else None)
                if record is None:
                    raise _changed('A thread item has no post.')
                group.append(record)
            relate(group)
            unit = next((r['id'] for r in group if r.get('id')), None)
            for record in group:
                record['unit'] = unit
        page.groups.append(group)
        page.records.extend(group)
    return page
