"""Connections: where a surface's records sit in a response, how it pages, and the relations inside one unit.

A unit (one edge) can carry several posts: a post and a reply to it, or an author continuing their own post. They stay
one group, and each later post says what it is to the post it answers, so it never reads as an unrelated post.
"""
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit

from threads.errors import ThreadsError
from threads.threads_web.records.posts import _time, post_record, user_record

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
RELATIONS = ('followers', 'following', 'following_more')


def _count(value, key):
    if isinstance(value, dict):
        if type(value.get(key)) is int:
            return value[key]
        for child in value.values():
            found = _count(child, key)
            if found is not None:
                return found
    return None


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
    """Give each later post of a unit its relation to the earlier post it answers, and its depth under it.

    The post it answers is the one reply_to_id names when Threads sends it; otherwise (what Threads sends now) the
    nearest earlier post of the unit one reply_level up, and only when that post's author is the reply_to_author the
    reply names. A reply that fits neither stays unplaced rather than guessed."""
    seen, earlier = {}, []
    for record in group:
        target = seen.get(record.get('reply_to_id')) if record.get('id') != record.get('reply_to_id') else None
        level = record.get('reply_level')
        if target is None and not record.get('reply_to_id') and isinstance(level, int) and level > 0:
            target = next((r for r in reversed(earlier) if r.get('reply_level') == level - 1), None)
            named = (record.get('reply_to_author') or '').lower()
            if target is not None and named and named != ((target.get('author') or {}).get('username') or '').lower():
                target = None
        earlier.append(record)
        if target is not None:
            same = (record.get('author') or {}).get('id') == (target.get('author') or {}).get('id') is not None
            record['relation'] = {'kind': 'continuation' if same else 'reply', 'to': target['id']}
            record['depth'] = target.get('depth', 0) + 1
        if record.get('id'):
            seen[record['id']] = record
    return group


def _find(value, key):
    if isinstance(value, dict):
        if isinstance(value.get(key), dict) and 'edges' in value[key]:
            return value[key]
        for child in value.values():
            found = _find(child, key)
            if found is not None:
                return found
    return None


def connection_page(data, surface):
    """One page of `surface` from a response's data: records grouped by unit, and how it continues."""
    root, items, policy = SURFACES[surface]
    try:
        connection = _at(data, root)
    except ThreadsError:
        # a relation list moves between queries (user.followers, fetch__XDTUserDict.followers): find it by name
        connection = _find(data, root.split('.')[-1]) if surface in RELATIONS else None
        if connection is None:
            raise
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
        total = counts.get('followers')
        if total is None:
            total = _count(data, 'follower_count')
        page.reported_total = total if type(total) is int else None
        # Followers are read as the one sample Threads sends (decision T5), even when the reply offers a cursor.
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


# {username|color|1|user?id=<id>|verified or none}: how the activity list names an account
_TITLE = re.compile(r'\{([A-Za-z0-9._]+)\|[^|{}]*\|[^|{}]*\|user\?id=(\d+)\|([a-z_]*)\}')


def activity_page(data, tab, post_id):
    """The quotes (tab 'quote') or reposts ('repost') of post_id from the post activity tab response: one batch, with
    the count Threads reports. A quote becomes a post record, a repost an account record with reposted_at."""
    items = data.get('feedback_hub_tab_items') if isinstance(data, dict) else None
    hub = data.get('feedback_hub') if isinstance(data, dict) else None
    if not isinstance(items, dict) or not isinstance(items.get('edges'), list) or not isinstance(hub, dict):
        raise _changed('The activity response has no feedback_hub_tab_items.edges list.')
    about = str((hub.get('post') or {}).get('strong_id__') or '')
    if about.split('_')[0] != post_id:
        raise _changed('The activity response is about another post.')
    page = Page(reported_total=hub.get('num_activity') if type(hub.get('num_activity')) is int else None)
    for edge in items['edges']:
        node = edge.get('node') if isinstance(edge, dict) else None
        extra = node.get('extra') if isinstance(node, dict) else None
        if not isinstance(extra, dict) or extra.get('icon_name') != tab:
            raise _changed(f'The activity response holds something other than {tab}s.')
        record = _activity_record(node, extra, tab)
        page.groups.append([record])
        page.records.append(record)
    # Threads sends one batch (about 100) with no way to ask for more: fewer than it reports is its own sample.
    total = page.reported_total
    page.stop = 'server_capped' if total is not None and len(page.records) < total else 'exhausted'
    return page


def _activity_record(node, extra, tab):
    title = _TITLE.fullmatch(extra.get('title') or '')
    actor = (node.get('actor') or {}).get('strong_id__')
    user = {'pk': title[2] if title else actor, 'username': title[1] if title else '', 'full_name': extra.get('context'),
            'is_verified': title[3] == 'verified' if title else None}
    if tab == 'repost':
        record = user_record(user)
        if record is None:
            raise _changed('A repost in the activity list has no account.')
        record['reposted_at'] = _time(node.get('timestamp'))
        return record
    destination = parse_qs(urlsplit('/' + (node.get('destination') or '')).query)
    record = post_record({'pk': node.get('pk'), 'code': (destination.get('shortcode') or [None])[0],
                          'taken_at': node.get('timestamp'), 'caption': {'text': extra.get('content') or ''},
                          'user': user})
    if record is None or record['unavailable']:
        raise _changed('A quote in the activity list has no post id.')
    record['role'] = 'quote'
    return record
