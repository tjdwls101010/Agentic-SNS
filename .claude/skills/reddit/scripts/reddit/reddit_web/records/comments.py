"""A t1 (comment) → the skill's comment record (flat: the tree is kept by parent_id and depth, not nesting)."""
from reddit.reddit_web.records.common import BASE, absolute, fullname, images, number, optional, text, timestamp


def _removed(data):
    """'removed' when moderators or Reddit took the text away, 'deleted' when its author did, else None."""
    body = data.get('body')
    if body == '[removed]':
        return 'removed'
    if body == '[deleted]' and data.get('author') in (None, '[deleted]'):
        return 'deleted'
    return None


def comment(data, depth=None):
    identity = fullname(data, 't1')
    post_id = text(data.get('link_id'))
    sent_depth = number(data.get('depth'))
    return {
        'kind': 'comment', 'id': identity,
        'url': absolute(data.get('permalink')) or f'{BASE}/comments/{post_id[3:]}/_/{identity[3:]}/',
        'parent_id': text(data.get('parent_id')), 'post_id': post_id, 'text': text(data.get('body')),
        'author': text(data.get('author')) or '[deleted]', 'subreddit': text(data.get('subreddit')),
        'created_at': timestamp(data.get('created_utc')), 'score': number(data.get('score')),
        'score_hidden': data.get('score_hidden') is True,
        'depth': depth if depth is not None else int(sent_depth or 0),
        'is_op': data.get('is_submitter') is True, 'distinguished': optional(data.get('distinguished')),
        'author_flair': optional(data.get('author_flair_text')), 'pinned': data.get('stickied') is True,
        'locked': data.get('locked') is True, 'edited_at': timestamp(data.get('edited')),
        'collapsed': data.get('collapsed') is True, 'collapsed_reason': optional(data.get('collapsed_reason_code')),
        'controversial': data.get('controversiality') == 1, 'removed': _removed(data),
        'media': images(data.get('media_metadata')),
    }
