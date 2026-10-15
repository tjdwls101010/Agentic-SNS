"""Comment and reply records.

A comment node has depth, author (an object or null), body (an object or null) and an id; depth 0 is a comment on
the post, 1 a reply, 2 a reply to a reply. Pieces of one comment merge by id. Replies are never inline: a comment's
replies are read with its feedback id and expansion token, a batch at a time.
"""
from facebook.graphql.records.parse import deep_merge, pieces, top_page_info, unplaced
from facebook.graphql.records.time import iso, timestamp

FIELDS = {
    'id': 'string — stable identity of the comment',
    'post_id': 'string — id of the post it belongs to; matches that post record\'s id',
    'author_name': 'string | null — display name of the commenter',
    'author_url': 'string | null — the commenter\'s profile URL; the profile and about commands\' argument',
    'author_id': 'string | null — numeric id of the commenter',
    'text': 'string — the comment body as received; empty for a comment that is only an attachment',
    'created_at': 'string | null — ISO-8601 UTC time the comment was made',
    'depth': 'integer — 0 for a comment on the post, 1 for a reply, 2 for a reply to a reply',
    'parent_id': 'string | null — id of the comment this one replies to; null at depth 0',
    'reaction_count': 'integer | null — reactions; null when not sent, never guessed from an abbreviation like 1.2K',
    'reply_count': 'integer | null — replies Facebook reports under this comment, deeper replies included; null when '
                   'not sent',
    'replies_handle': 'integer | null — the handle of its first reply batch: run replies <handle>; null when there '
                      'is nothing to expand',
    'attachments': 'array<object> — what the comment carries besides text; empty text plus an attachment is that '
                   'attachment, not an empty comment',
    'attachments[].kind': 'string — photo | gif | sticker | video | link | other; media URLs are not included',
    'captured_at': 'string — ISO-8601 UTC time this tool received it; changes every run',
}
ATTACHMENT_KINDS = {'photo': 'photo', 'album': 'photo', 'animated_image_share': 'gif', 'sticker': 'sticker',
                    'video': 'video', 'video_inline': 'video', 'share': 'link', 'link': 'link'}


def is_comment_node(obj):
    return (isinstance(obj, dict) and 'depth' in obj and 'author' in obj and isinstance(obj.get('author'), (dict, type(None)))
            and isinstance(obj.get('body'), (dict, type(None))) and obj.get('id') is not None)


def _contains_comment(value):
    if is_comment_node(value):
        return True
    if isinstance(value, dict):
        return any(_contains_comment(child) for key, child in value.items() if key != 'comment_direct_parent')
    if isinstance(value, list):
        return any(_contains_comment(child) for child in value)
    return False


def nodes(chunks):
    """Comment nodes merged by id, in first-seen order; a reply's copy of its parent is not a comment of the page."""
    found = {}

    def walk(obj):
        if isinstance(obj, dict):
            if is_comment_node(obj):
                key = str(obj['id'])
                found[key] = deep_merge(found.get(key, {}), obj)
            for key, value in obj.items():
                if key != 'comment_direct_parent':
                    walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    for _, data, _, _ in pieces(chunks):
        walk(data)
    return list(found.values())


def _count(node, *path):
    current = node
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current if type(current) is int and current >= 0 else None


def reaction_count(node):
    """Reactions: reactors.count, unified_reactors.count, reaction_count.count, then the action links' exact count,
    and only last a count_reduced that is all digits (an abbreviation like 1.2K would invent precision)."""
    feedback = node.get('feedback') if isinstance(node.get('feedback'), dict) else {}
    for path in (('reactors', 'count'), ('unified_reactors', 'count'), ('reaction_count', 'count')):
        value = _count(feedback, *path)
        if value is not None:
            return value
    for link in node.get('comment_action_links') or []:
        value = _count(link, 'comment', 'feedback', 'reactors', 'count') if isinstance(link, dict) else None
        if value is not None:
            return value
    reduced = (feedback.get('reactors') or {}).get('count_reduced') if isinstance(feedback.get('reactors'), dict) else None
    return int(reduced) if isinstance(reduced, str) and reduced.isascii() and reduced.isdigit() else None


def handle(node):
    """{feedback_id, expansion_token, expandable}: what expands this comment's replies. A count of 0 means none; a
    missing count lets the token decide."""
    feedback = node.get('feedback') if isinstance(node.get('feedback'), dict) else {}
    info = feedback.get('expansion_info') if isinstance(feedback.get('expansion_info'), dict) else {}
    token = info.get('expansion_token') if isinstance(info.get('expansion_token'), str) else None
    replies = _count(node, 'feedback', 'replies_fields', 'total_count')
    identity = feedback.get('id') if isinstance(feedback.get('id'), str) else None
    expandable = bool(identity and token) and replies != 0
    return {'feedback_id': identity, 'expansion_token': token, 'expandable': expandable}


def build(node, *, post_id, captured_at):
    author = node.get('author') if isinstance(node.get('author'), dict) else {}
    body = node.get('body') if isinstance(node.get('body'), dict) else {}
    parent = node.get('comment_direct_parent') if isinstance(node.get('comment_direct_parent'), dict) else {}
    attachments = []
    for attachment in node.get('attachments') or []:
        if isinstance(attachment, dict):
            styles = attachment.get('style_list')
            first = styles[0] if isinstance(styles, list) and styles and isinstance(styles[0], str) else None
            attachments.append({'kind': ATTACHMENT_KINDS.get(first, 'other')})
    return {
        'id': str(node['id']),
        'post_id': post_id,
        'author_name': author.get('name') if isinstance(author.get('name'), str) else None,
        'author_url': author.get('url') if isinstance(author.get('url'), str) else None,
        'author_id': str(author['id']) if author.get('id') is not None else None,
        'text': body.get('text') if isinstance(body.get('text'), str) else '',
        'created_at': iso(timestamp(node.get('created_time'))),
        'depth': node['depth'] if type(node.get('depth')) is int else 0,
        'parent_id': str(parent['id']) if parent.get('id') else None,
        'reaction_count': reaction_count(node),
        'reply_count': _count(node, 'feedback', 'replies_fields', 'total_count'),
        'replies_handle': None,
        'attachments': attachments,
        'captured_at': iso(captured_at),
    }


def issues(chunks):
    """Response issues of a comment response: pieces no comment consumed; comment records carry no incomplete flag."""
    touched, found = unplaced(chunks, consumed=lambda path, data: _contains_comment(data))
    return list(dict.fromkeys(found + [reason for reasons in touched.values() for reason in reasons]))


def parents(chunks, *, post_id, captured_at):
    """(depth-0 comments in server order, {comment id: reply handle}, page_info of the comments connection)."""
    records, handles = [], {}
    for node in nodes(chunks):
        record = build(node, post_id=post_id, captured_at=captured_at)
        if record['depth'] != 0:
            continue
        records.append(record)
        handles[record['id']] = handle(node)
    return records, handles, top_page_info(chunks, 'comments')


def replies(chunks, *, post_id, parent_id, captured_at):
    """(replies to `parent_id` from one expansion response, their own reply handles, the batch's page_info).

    A reply without a parent link belongs to the comment that was expanded; a reply to another comment is left out.
    """
    records, handles = [], {}
    for node in nodes(chunks):
        record = build(node, post_id=post_id, captured_at=captured_at)
        if record['id'] == parent_id or record['depth'] <= 0:
            continue
        record['parent_id'] = record['parent_id'] or parent_id
        if record['parent_id'] == parent_id:
            records.append(record)
            handles[record['id']] = handle(node)
    return records, handles, top_page_info(chunks, 'replies_connection')
