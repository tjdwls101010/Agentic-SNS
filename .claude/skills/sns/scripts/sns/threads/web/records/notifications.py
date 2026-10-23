"""The viewer's activity list: bucket headers set seen state but never become notification records."""
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from typing import get_args, get_origin
from urllib.parse import quote

from sns.threads.web.records.lists import Page, _changed
from sns.threads.web.records.posts import ORIGIN, _integer, _time


@dataclass
class Notification:
    kind: str
    id: str
    url: str | None
    created_at: str | None
    notification_type: str | None
    text: str
    unseen: bool | None
    actors: list[str]
    post: dict | None
    captured_at: str


NOTES = {
    'kind': 'notification',
    'id': 'Threads edge_id; no command takes it as an argument',
    'url': 'the ufi_media post URL, else the first actor profile URL, else null',
    'created_at': 'notification timestamp as ISO 8601 UTC; null when Threads sent no usable time',
    'notification_type': 'Threads notif_name; the set of type words is open',
    'text': 'title text, then body text on a new line unless it repeats the title; never shortened in JSON',
    'unseen': 'true after NEW, false after EARLIER, null before a header or after an unknown bucket; not changed',
    'actors': 'usernames from sender_users, in their received order, without @',
    'post': '{url, like_count, direct_reply_count, quote_count, repost_count} from ufi_media; null without media; '
            'url or a count is null when Threads sent none',
    'captured_at': 'ISO 8601 UTC time the list was parsed; changes each run',
}


def _schema_type(annotation):
    """The public schema vocabulary from the record's annotations, including nullable fields and array items."""
    names = {str: 'string', bool: 'boolean', dict: 'object', type(None): 'null'}
    if annotation in names:
        return names[annotation]
    args = get_args(annotation)
    if get_origin(annotation) is list:
        return f'array<{_schema_type(args[0])}>'
    return ' | '.join(_schema_type(arg) for arg in args)


SCHEMA = {'object': 'notification', 'description': 'One row of your activity list, read without marking it seen.',
          'fields': {f.name: f'{_schema_type(f.type)} — {NOTES[f.name]}' for f in fields(Notification)}}


def _text(value):
    found = value.get('text') if isinstance(value, dict) else None
    return found if isinstance(found, str) else ''


def _post(media):
    if media is None:
        return None
    if not isinstance(media, dict):
        raise _changed('An activity row has unreadable post data.')
    user = media.get('user') if isinstance(media.get('user'), dict) else {}
    username, code = user.get('username'), media.get('code')
    url = (f'{ORIGIN}/@{quote(username, safe="._-")}/post/{quote(code, safe="_-")}'
           if isinstance(username, str) and username and isinstance(code, str) and code else None)
    info = media.get('text_post_app_info') if isinstance(media.get('text_post_app_info'), dict) else {}
    return {'url': url, 'like_count': _integer(media.get('like_count')),
            **{key: _integer(info.get(key)) for key in ('direct_reply_count', 'quote_count', 'repost_count')}}


def notifications_page(data):
    """One validated activity page; a next-page flag records a server cap without exposing its unverified cursor."""
    connection = data.get('notifications') if isinstance(data, dict) else None
    if not isinstance(connection, dict) or not isinstance(connection.get('edges'), list):
        raise _changed('The activity response has no notifications.edges list.')
    info = connection.get('page_info')
    if not isinstance(info, dict) or type(info.get('has_next_page')) is not bool:
        raise _changed('The activity response has no page_info.has_next_page.')
    page = Page(stop='server_capped' if info['has_next_page'] else None)
    captured_at, unseen = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'), None
    for edge in connection['edges']:
        node = edge.get('node') if isinstance(edge, dict) else None
        if not isinstance(node, dict):
            raise _changed('An activity edge has no node.')
        if node.get('__typename') == 'XTHNotifFeedBucketHeader':
            unseen = {'NEW': True, 'EARLIER': False}.get(node.get('bucket_type'))
            continue
        if node.get('__typename') != 'XTHNotificationFeedRow':
            raise _changed('The activity response contains an unknown row type.')
        identity, title, body = node.get('edge_id'), _text(node.get('title')), _text(node.get('body'))
        if not isinstance(identity, str) or not identity or not (title or body):
            raise _changed('An activity row has no identity or readable text.')
        text = '\n'.join(part for part in (title, body if body != title else '') if part)
        senders = node.get('sender_users')
        edges = senders.get('edges') if isinstance(senders, dict) else None
        if not isinstance(edges, list):
            raise _changed('An activity row has no sender_users.edges list.')
        actors = []
        for sender in edges:
            actor = sender.get('node') if isinstance(sender, dict) else None
            username = actor.get('username') if isinstance(actor, dict) else None
            if not isinstance(username, str) or not username:
                raise _changed('An activity sender has no username.')
            actors.append(username)
        post = _post(node.get('ufi_media'))
        profile = f'{ORIGIN}/@{quote(actors[0], safe="._-")}' if actors else None
        name = node.get('notif_name')
        record = asdict(Notification('notification', identity, (post or {}).get('url') or profile,
                                     _time(node.get('timestamp')), name if isinstance(name, str) else None,
                                     text, unseen, actors, post, captured_at))
        page.records.append(record)
        page.groups.append([record])
    return page
