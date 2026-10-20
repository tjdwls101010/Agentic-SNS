"""Notifications: the rows of the viewer's notification list as notification records, in the connection's order.

A row's node is a notification (`row_type` NOTIFICATION, its data in `notif`) or layout (a bucket header, the
see-previous button), which is never a record and not an item either: a page of layout rows alone is an empty page,
not a changed answer. `tracking`, the image, the icon and the settings attachments of a notification are not exported.
"""
from sns.facebook.web.records.moment import iso, timestamp
from sns.facebook.web.records.parse import find_page_info, pieces, unplaced

KEY = 'notifications_page'
FIELDS = {
    'kind': 'string — notification',
    'id': 'string — Facebook\'s notif_id (its id when a row has no notif_id); no command takes it as an argument',
    'url': 'string | null — what the notification points at (a post, a comment, a profile); null when it names none',
    'created_at': 'string | null — ISO-8601 UTC time Facebook gives the notification; null when it gave none',
    'notification_type': 'string | null — Facebook\'s own type word, e.g. feed_comment_reply; the set is open',
    'text': 'string | null — the notification as Facebook words it, e.g. "A replied to your comment"',
    'seen': 'string | null — unseen (Facebook\'s UNSEEN) | seen (SEEN_BUT_UNREAD) | read (SEEN_AND_READ); null when '
            'Facebook sent none or one this skill does not know (a coverage note says so)',
    'captured_at': 'string — ISO-8601 UTC time this tool received it; changes every run',
}
SEEN = {'UNSEEN': 'unseen', 'SEEN_BUT_UNREAD': 'seen', 'SEEN_AND_READ': 'read'}
LAYOUT = frozenset({'BUCKET_HEADER', 'SEE_PREVIOUS_BUTTON'})


def _edges(obj):
    """The edges of every notifications connection in a decoded piece, in order."""
    if isinstance(obj, dict):
        connection = obj.get(KEY)
        if isinstance(connection, dict) and isinstance(connection.get('edges'), list):
            yield from connection['edges']
        for key, value in obj.items():
            if key != KEY:
                yield from _edges(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _edges(value)


def _text(value):
    return value if isinstance(value, str) and value else None


def _record(notif, captured_at):
    """(the notification record, or None when the row names no id; the issue its seen state raised, or None)."""
    found = notif.get('notif_id') or notif.get('id')
    if type(found) not in (str, int) or found == '':
        return None, None
    seen_state = notif.get('seen_state')
    seen = SEEN.get(seen_state) if isinstance(seen_state, str) else None
    issue = 'unknown_seen_state' if seen_state is not None and seen is None else None
    moment = notif.get('creation_time')
    body = notif.get('body')
    return {'kind': 'notification', 'id': str(found), 'url': _text(notif.get('url')),
            'created_at': iso(timestamp(moment.get('timestamp') if isinstance(moment, dict) else None)),
            'notification_type': _text(notif.get('notif_type')),
            'text': _text(body.get('text') if isinstance(body, dict) else None),
            'seen': seen, 'captured_at': iso(captured_at)}, issue


def page(chunks, *, captured_at):
    """(records in list order, page_info, whether the page held any non-layout row, response issues)."""
    records, issues, has_items = [], [], False
    for _, data, _, _ in pieces(chunks):
        for edge in _edges(data):
            node = edge.get('node') if isinstance(edge, dict) else None
            if not isinstance(node, dict) or node.get('row_type') in LAYOUT:
                continue
            has_items = True
            notif = node.get('notif')
            record, issue = _record(notif, captured_at) if isinstance(notif, dict) else (None, None)
            if record:
                records.append(record)
            if issue:
                issues.append(issue)
    # 성진: 늦게 도착하는(@defer) 알림 조각은 적용하지 않고 unplaced 이슈로만 알린다. 캡처에서 알림 필드를 담은 조각이 보이면 구현할 것
    return records, find_page_info(chunks, KEY), has_items, list(dict.fromkeys(issues + unplaced(chunks)[1]))
