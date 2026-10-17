"""Threads' post and user objects as the skill's records; an unavailable piece is marked where it is."""
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from threads.errors import ThreadsError

ORIGIN = 'https://www.threads.com'
MEDIA_TYPES = {1: 'image', 2: 'video', 8: 'carousel', 19: 'text'}
# 성진: 공유(인용·리포스트) 중첩은 8단계에서 끊는다 — 적대적·순환 응답의 작업량 상한. 실제 응답에 더 깊은 사슬이 보이면 올린다
MAX_SHARE_DEPTH = 8


def _identifier(value):
    """An ASCII-decimal identifier string, or None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value) if value >= 0 else None
    if isinstance(value, str) and value and value.isascii() and value.isdecimal():
        return value
    return None


def identity(node):
    """A node's id: pk first; else a decimal id; else the numeric head of a `<pk>_<author pk>` media id."""
    if not isinstance(node, dict):
        return None
    if node.get('pk') is not None:
        return _identifier(node['pk'])
    found = _identifier(node.get('id'))
    if found:
        return found
    head, _, tail = str(node.get('id') or '').partition('_')
    return head if head.isascii() and head.isdecimal() and tail.isascii() and tail.isdecimal() else None


def _integer(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip('-').isdigit():
        return int(value.strip())
    return None


def _largest(candidates):
    """The usable candidate with the largest pixel area; ties keep their order."""
    if not isinstance(candidates, list):
        return None
    usable = [c for c in candidates if isinstance(c, dict) and isinstance(c.get('url'), str) and c['url']]

    def area(candidate):
        width, height = _integer(candidate.get('width')), _integer(candidate.get('height'))
        return -1 if width is None or height is None else width * height
    return max(usable, key=area) if usable else None


def _media(item):
    kind_code = _integer(item.get('media_type'))
    versions = item.get('image_versions2')
    image = _largest(versions.get('candidates') if isinstance(versions, dict) else None)
    video = _largest(item.get('video_versions'))
    chosen = (video or image) if kind_code == 2 else (image or video)
    kind = {1: 'photo', 2: 'video', 8: 'carousel'}.get(kind_code) or ('video' if video else 'photo' if image else 'unknown')
    chosen = chosen or {}
    width, height = _integer(chosen.get('width')), _integer(chosen.get('height'))
    alt = item.get('accessibility_caption')
    return {'kind': kind, 'url': chosen.get('url') if isinstance(chosen.get('url'), str) else '',
            'width': width if width is not None else _integer(item.get('original_width')),
            'height': height if height is not None else _integer(item.get('original_height')),
            'alt_text': alt if isinstance(alt, str) else None}


def _post_media(raw):
    carousel = raw.get('carousel_media')
    if isinstance(carousel, list) and carousel:
        items = [item for item in carousel if isinstance(item, dict)]
    elif isinstance(raw.get('image_versions2'), dict) or isinstance(raw.get('video_versions'), list):
        items = [raw]
    else:
        items = []
    return [media for media in (_media(item) for item in items) if media['url']]


def _unwrap(url):
    """Threads routes outbound links through l.threads.com/?u=<destination>; the destination is the link."""
    if not isinstance(url, str):
        return None
    parts = urlsplit(url)
    if parts.hostname == 'l.threads.com':
        destination = (parse_qs(parts.query).get('u') or [None])[0]
        if destination and urlsplit(destination).scheme in ('http', 'https'):
            return destination
    return url


def _link(info):
    attachment = info.get('link_preview_attachment')
    if not isinstance(attachment, dict):
        return None
    title = attachment.get('title')
    link = {'url': _unwrap(attachment.get('url')), 'title': title if isinstance(title, str) else None}
    return link if any(value is not None for value in link.values()) else None


def _time(stamp):
    if type(stamp) in (int, float) or (isinstance(stamp, str) and stamp.isdigit()):
        try:
            return datetime.fromtimestamp(float(stamp), timezone.utc).isoformat().replace('+00:00', 'Z')
        except (ValueError, OSError, OverflowError):
            return None
    return None


def user_record(raw):
    """A user object as a record, or None when it has no identity."""
    found = identity(raw)
    if found is None:
        return None
    name = raw.get('username') if isinstance(raw.get('username'), str) else ''
    verified = raw.get('is_verified', raw.get('text_post_app_is_verified'))
    return {'id': found, 'username': name, 'full_name': raw.get('full_name'),
            'is_verified': verified if isinstance(verified, bool) else None,
            'private': raw.get('text_post_app_is_private') if isinstance(raw.get('text_post_app_is_private'), bool)
            else None,
            'follower_count': _integer(raw.get('follower_count')), 'bio': raw.get('biography'),
            'bio_links': [link['url'] for link in raw.get('bio_links') or [] if isinstance(link, dict) and link.get('url')],
            'friendship_status': raw.get('friendship_status') if isinstance(raw.get('friendship_status'), dict) else {},
            'profile_pic_url': raw.get('profile_pic_url'), 'url': ORIGIN + '/@' + name if name else None}


def _unavailable(found, reason):
    return {'id': found, 'unavailable': True, 'unavailable_reason': reason, 'role': 'post', 'depth': 0,
            'relation': None}


def post_record(raw, ancestors=()):
    """A post object as a record; a tombstone, a share cycle or the depth bound become an unavailable marker."""
    if not isinstance(raw, dict):
        return None
    found = identity(raw)
    if raw.get('is_post_unavailable') or raw.get('attachment_tombstone_info') or found is None:
        return _unavailable(found, 'Post unavailable: deleted, hidden, or not visible to this account')
    if found in ancestors or len(ancestors) >= MAX_SHARE_DEPTH:
        return _unavailable(found, 'Nested share cycle or depth limit')
    author = user_record(raw.get('user'))
    info = raw.get('text_post_app_info') if isinstance(raw.get('text_post_app_info'), dict) else {}
    share = info.get('share_info') if isinstance(info.get('share_info'), dict) else {}
    code = raw.get('code') if isinstance(raw.get('code'), str) else None
    url = (f'{ORIGIN}/@{author["username"]}/post/{code}' if author and author['username'] and code
           else f'{ORIGIN}/t/{code}' if code else None)
    caption = raw.get('caption') if isinstance(raw.get('caption'), dict) else {}
    pinned = info.get('pinned_post_info') if isinstance(info.get('pinned_post_info'), dict) else {}
    nested = ancestors + (found,)
    return {'id': found, 'code': code, 'url': url, 'created_at': _time(raw.get('taken_at')),
            'text': caption.get('text') if isinstance(caption.get('text'), str) else '', 'author': author,
            'like_count': None if raw.get('like_and_view_counts_disabled') else _integer(raw.get('like_count')),
            'reply_count': _integer(info.get('direct_reply_count')), 'repost_count': _integer(info.get('repost_count')),
            'quote_count': _integer(info.get('quote_count')),
            'media_type': MEDIA_TYPES.get(_integer(raw.get('media_type')), 'text'), 'media': _post_media(raw),
            'link_preview': _link(info),
            'is_reply': bool(info.get('is_reply', info.get('reply_to_author') is not None)),
            'reply_to_id': _identifier(info.get('reply_to_id')), 'root_post_id': _identifier(info.get('root_post_id')),
            'reply_level': _integer(info.get('reply_level')),
            'reply_to_author': (user_record(info.get('reply_to_author')) or {}).get('username') or None,
            'quoted_post': post_record(share.get('quoted_post'), nested),
            'reposted_post': post_record(share.get('reposted_post'), nested),
            'is_pinned': bool(pinned.get('is_pinned_to_profile')), 'unavailable': False, 'role': 'post', 'depth': 0,
            'relation': None}


def profile_card(raw, requested):
    """A profile's card: its user record with the counts Threads publishes (followers only)."""
    record = user_record(raw)
    if record is None or record['username'].lower() != requested.lower():
        raise ThreadsError(6, 'The profile response is about someone other than the requested handle.',
                           'Threads changed this response; the skill needs an update.', reason='shape_changed')
    # Threads publishes no following or mutual count: null is unknown, and graph following lists the accounts.
    return {**record, 'counts': {'followers': record['follower_count'], 'following': None, 'mutuals': None}}
