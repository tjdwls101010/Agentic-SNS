"""A post page: the post, its parent chain and its first batch of direct replies, from the post page's responses.

Each response is told apart by its shape, never by its query name (Threads renames queries): the media whose code is
the requested shortcode is the post, containing_thread holds the parents, direct_replies holds the replies. Each must
be about the requested post id; a second response claiming the same role is refused rather than guessed between.
"""
from dataclasses import dataclass, field

from threads.errors import ThreadsError
from threads.threads_web.records.lists import relate
from threads.threads_web.records.posts import identity, post_record

_CHANGED = 'Threads changed this response; the skill needs an update.'


@dataclass
class Batch:
    records: list
    cursor: str | None = None                       # the next batch, when Threads has more
    branches: dict = field(default_factory=dict)    # reply id → {cursor} of replies under it not yet sent


@dataclass
class PostPage:
    records: list
    coverage: dict
    replies_cursor: str | None = None          # the next batch of direct replies, when Threads has more
    branches: dict = field(default_factory=dict)  # direct reply id → {cursor} of its sub-replies not yet sent


def _changed(message):
    return ThreadsError(6, message, _CHANGED, reason='shape_changed')


def _info(data):
    media = data.get('media') if isinstance(data, dict) else None
    info = media.get('text_post_app_info') if isinstance(media, dict) else None
    return media, info if isinstance(info, dict) else {}


def roles(responses, code, post_id):
    """{post, parents, replies}: the one response of each role about post_id."""
    found = {'post': [], 'parents': [], 'replies': []}
    for data in responses:
        media, info = _info(data)
        if not isinstance(media, dict) or identity(media) != post_id:
            continue
        for role, fits in (('post', media.get('code') == code), ('parents', 'containing_thread' in info),
                           ('replies', 'direct_replies' in info)):
            if fits and data not in found[role]:
                found[role].append(data)
    for role, matches in found.items():
        if len(matches) != 1:
            raise _changed(f'The post page has no unambiguous {role} response for this post.')
    return {role: matches[0] for role, matches in found.items()}


def reply_batch(direct_replies, post_id, seen, *, limit, counts):
    """Records of one batch of direct replies (each followed by what hangs under it), updating `counts`."""
    if not isinstance(direct_replies, dict) or not isinstance(direct_replies.get('edges'), list):
        raise _changed('The replies response has no direct_replies.edges list.')
    records, branches = [], {}
    for edge in direct_replies['edges']:
        node = edge.get('node') if isinstance(edge, dict) else None
        posts = (node.get('posts') or {}).get('edges') if isinstance(node, dict) else None
        if not isinstance(posts, list) or not posts:
            counts['unavailable'] += 1
            continue
        group = [post_record(item.get('node') if isinstance(item, dict) else None) for item in posts]
        first = group[0]
        missing = first is None or first['unavailable']
        if missing:
            counts['unavailable'] += 1
        elif first['id'] in seen:
            continue
        else:
            counts['received_direct'] += 1
            seen.add(first['id'])
        if limit is not None and counts['groups_shown'] >= limit:
            if not missing:
                counts['unshown_received'] += 1
            continue
        counts['groups_shown'] += 1
        if not missing:
            counts['shown_direct'] += 1
        kept = [group[0]]
        for item in group[1:]:
            if item is None or (item.get('id') and item['id'] in seen):
                continue
            if item.get('id'):
                seen.add(item['id'])
            kept.append(item)
            counts['shown_descendants'] += 1
        for record in kept:
            record['role'] = 'reply'
        relate(kept)
        records.extend(kept)
        info = (node.get('posts') or {}).get('page_info')
        if not missing and isinstance(info, dict) and info.get('has_next_page') is True and info.get('end_cursor'):
            branches[first['id']] = {'cursor': info['end_cursor']}
    return records, branches


def coverage(reported, counts):
    """The reply coverage: reported, received, shown, nested, received but unshown, unavailable, never received."""
    received, unavailable = counts['received_direct'], counts['unavailable']
    estimate = reported - received - unavailable if reported is not None and reported >= received + unavailable else None
    return {'reported_direct': reported, 'received_direct': received, 'shown_direct': counts['shown_direct'],
            'shown_descendants': counts['shown_descendants'], 'unshown_received': counts['unshown_received'],
            'unavailable': unavailable, 'unfetched': estimate, 'unfetched_is_estimate': estimate is not None}


def new_counts():
    return {'received_direct': 0, 'shown_direct': 0, 'shown_descendants': 0, 'unshown_received': 0, 'unavailable': 0,
            'groups_shown': 0}


def post_page(responses, *, code, post_id, limit):
    """The post page read from its post, parents and replies responses."""
    found = roles(responses, code, post_id)
    post = post_record(found['post']['media'])
    if post is None or post['unavailable']:
        raise ThreadsError(9, 'This post is unavailable: deleted, or not visible to this account.',
                           'Tell the user; retrying will not change it.', reason='unavailable')
    _, parents_info = _info(found['parents'])
    parent_edges = ((parents_info.get('containing_thread') or {}).get('posts') or {}).get('edges')
    _, replies_info = _info(found['replies'])
    if not isinstance(parent_edges, list):
        raise _changed('The parents response has no containing_thread.posts.edges list.')
    records, seen = [], {post_id}
    for edge in parent_edges:
        parent = post_record(edge.get('node') if isinstance(edge, dict) else None)
        if parent and parent.get('id') not in seen:
            parent['role'] = 'parent'
            records.append(parent)
            if parent.get('id'):
                seen.add(parent['id'])
    records.append(post)
    counts = new_counts()
    replies, branches = reply_batch(replies_info.get('direct_replies'), post_id, seen, limit=limit, counts=counts)
    records.extend(replies)
    info = (replies_info.get('direct_replies') or {}).get('page_info')
    cursor = info.get('end_cursor') if isinstance(info, dict) and info.get('has_next_page') is True else None
    return PostPage(records, coverage(post['reply_count'], counts), cursor, branches)


def find(value, key):
    """The first value under `key` anywhere in a response (its place moves between queries)."""
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = find(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find(child, key)
            if found is not None:
                return found
    return None


def next_batch(data, post_id, seen):
    """A further batch of a post's direct replies (the refetch query's response)."""
    direct = find(data, 'direct_replies')
    if not isinstance(direct, dict):
        raise _changed('The replies response has no direct_replies.')
    counts = new_counts()
    found, branches = reply_batch(direct, post_id, seen, limit=None, counts=counts)
    info = direct.get('page_info')
    cursor = info.get('end_cursor') if isinstance(info, dict) and info.get('has_next_page') is True else None
    return Batch(found, cursor, branches)


def branch_batch(data, parent_id):
    """The replies under one reply (the inline expansion query's response): units like a post's direct replies, placed
    under the reply they answer."""
    expansion = find(data, 'inline_expansion')
    if not isinstance(expansion, dict) or not isinstance(expansion.get('edges'), list):
        raise _changed('The response holds no replies under this reply.')
    counts = new_counts()
    found, branches = reply_batch(expansion, parent_id, {parent_id}, limit=None, counts=counts)
    for record in found:
        record['depth'] = record.get('depth', 0) + 1
        if not record.get('relation'):
            record['relation'] = {'kind': 'reply', 'to': parent_id}
    info = expansion.get('page_info')
    cursor = info.get('end_cursor') if isinstance(info, dict) and info.get('has_next_page') is True else None
    return Batch(found, cursor, branches)
