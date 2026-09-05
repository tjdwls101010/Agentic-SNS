"""Thread roles follow reply IDs, while modules retain missing-branch evidence."""
from ._models import build_tweet
from ._errors import TwitterError


def thread_records(page, focal_id, continuing=False):
    rows = []
    found = False
    reported = None
    for entry in page.entries:
        if entry.kind != 'tweet' or entry.module_id and not entry.module_id.startswith('conversationthread-'):
            continue
        tweet = build_tweet(entry.node, entry.pinned)
        if tweet is None:
            if entry.entry_id == 'tweet-' + focal_id:
                raise TwitterError(9, 'The focal post is missing or deleted.', 'Check the post URL and visibility.')
            continue
        row = tweet.to_dict()
        if row['id'] == focal_id:
            role, found, reported = 'focal', True, row['reply_count']
        else:
            role = 'parent' if not found and not continuing and not entry.module_id else 'reply'
        row.update(role=role, module=entry.module_id, index_in_module=entry.index_in_module, depth=0)
        rows.append(row)
    by_id = {row['id']: row for row in rows}
    for row in rows:
        if row['role'] != 'reply':
            continue
        parent, visited = row.get('in_reply_to_id'), {row['id']}
        while parent in by_id and parent != focal_id and parent not in visited and by_id[parent]['role'] == 'reply':
            visited.add(parent)
            row['depth'] += 1
            parent = by_id[parent].get('in_reply_to_id')
    branch_ids = sorted({f'{e.module_id}:{e.entry_id}:{e.node.get("cursorType")}:{e.node.get("value")}' for e in page.module_cursors})
    meta = dict(focal_id=focal_id, hidden_branch_ids=branch_ids, hidden_branches=len(branch_ids))
    if reported is not None or not continuing:
        meta['reported'] = reported
    return rows, meta


def completeness(rows, focal_id, metadata):
    replies = [r for r in rows if r.get('role') == 'reply']
    direct = sum(r.get('in_reply_to_id') == focal_id for r in replies)
    return dict(reported=metadata.get('reported'), direct_shown=direct, nested_shown=len(replies) - direct,
                hidden_branches=metadata.get('hidden_branches', 0))
