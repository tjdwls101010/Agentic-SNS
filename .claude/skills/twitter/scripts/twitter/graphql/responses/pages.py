"""Raw X roots to record rows: single lookups, timelines and threads."""
from .records import build_place, build_trend, build_tweet, build_user
from .thread import thread_records
from .timeline import walk


def normalize_page(root, op, rows, focal_id=None, cursor=None):
    """Records of one page as dicts, the bottom cursor, and page metadata; `rows` is the record kind a timeline holds."""
    if op in ('UserByScreenName', 'UsersByScreenNames', 'TweetResultsByRestIds', 'ListByRestId', 'CommunityByRestId'):
        nodes = root if isinstance(root, list) else [root]
        records = []
        for node in nodes:
            if not node or node.get('__typename') in ('UserUnavailable', 'TweetTombstone'):
                continue
            item = (build_user(node) if op.startswith('User') else build_tweet(node) if op.startswith('Tweet') else
                    build_place(node, 'list' if op == 'ListByRestId' else 'community'))
            if item:
                records.append(item.to_dict())
        return records, None, dict(not_paginable=True)
    page = walk(root)
    if op == 'TweetDetail':
        records, metadata = thread_records(page, focal_id, continuing=bool(cursor))
    else:
        records, metadata = [], {}
        for entry in page.entries:
            if entry.kind not in (('trend', 'event') if rows == 'trend' else (rows,)):
                if entry.kind != 'cursor':
                    page.other_items += 1
                continue
            item = build_tweet(entry.node, entry.pinned) if entry.kind == 'tweet' else build_user(entry.node) if entry.kind == 'user' else build_trend(entry.node, entry.entry_id, entry.kind == 'event')
            if not item:
                continue
            row = item.to_dict()
            if row.get('promoted'):
                page.promoted += 1
                continue
            if entry.module_id:
                row['module'] = entry.module_id
                if entry.module_id.startswith(('communityModerators', 'communityMembers')):
                    row['role'] = 'moderator' if entry.module_id.startswith('communityModerators') else 'member'
            if entry.social_context.get('landingUrl'):
                landing = entry.social_context['landingUrl']
                row['community_url'] = landing.get('url') if isinstance(landing, dict) else landing
            records.append(row)
        if rows == 'trend':
            metadata.update(other_items=page.other_items, promoted=page.promoted, not_paginable=True)
    metadata['terminated'] = page.terminated
    return records, page.bottom_cursor, metadata
