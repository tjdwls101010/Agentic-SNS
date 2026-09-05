"""Pure normalization with nested unavailability contained at its own post."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from ._entities import User, build_user
from ._media import Media, _identifier, _integer, _link_preview, _node_identifier, _post_media


@dataclass
class Post:
    id: str | None = None
    code: str | None = None
    url: str | None = None
    created_at: str | None = None
    text: str = ''
    author: User | None = None
    like_count: int | None = None
    reply_count: int | None = None
    repost_count: int | None = None
    quote_count: int | None = None
    media_type: str = 'text'
    media: list[Media] = field(default_factory=list)
    is_reply: bool = False
    reply_to_id: str | None = None
    root_post_id: str | None = None
    quoted_post: Post | None = None
    reposted_post: Post | None = None
    link_preview: dict | None = None
    is_pinned: bool = False
    unavailable: bool = False
    unavailable_reason: str | None = None
    role: str = 'post'
    depth: int = 0
    relation: str | None = None

    def to_dict(self):
        return asdict(self)


def build_post(raw, ancestors=()):
    if not isinstance(raw, dict):
        return None
    identity = _node_identifier(raw)
    if raw.get('is_post_unavailable') or raw.get('attachment_tombstone_info') or identity is None:
        return Post(id=identity, unavailable=True, unavailable_reason='Post unavailable')
    # 성진: Eight nested shares bound hostile/cyclic payload work; raise only if real Threads payloads need deeper chains.
    if identity in ancestors or len(ancestors) >= 8:
        return Post(id=identity, unavailable=True, unavailable_reason='Nested share cycle or depth limit')
    author = build_user(raw.get('user'))
    info = raw.get('text_post_app_info') or {}
    share = info.get('share_info') or {}
    code = raw.get('code')
    created = None
    stamp = raw.get('taken_at')
    if type(stamp) in (int, float) or isinstance(stamp, str) and stamp.isdigit():
        try:
            created = datetime.fromtimestamp(float(stamp), timezone.utc).isoformat().replace('+00:00', 'Z')
        except (ValueError, OSError, OverflowError):
            pass
    url = f'https://www.threads.com/@{author.username}/post/{code}' if author and code else f'https://www.threads.com/t/{code}' if code else None
    return Post(id=identity, code=code, url=url, created_at=created,
        text=(raw.get('caption') or {}).get('text') or '', author=author,
        like_count=None if raw.get('like_and_view_counts_disabled') else _integer(raw.get('like_count')),
        reply_count=_integer(info.get('direct_reply_count')), repost_count=_integer(info.get('repost_count')),
        quote_count=_integer(info.get('quote_count')), media_type={1: 'image', 2: 'video', 8: 'carousel', 19: 'text'}.get(raw.get('media_type'), 'text'),
        media=_post_media(raw), is_reply=bool(info.get('is_reply', info.get('reply_to_author') is not None)),
        reply_to_id=_identifier(info.get('reply_to_id')), root_post_id=_identifier(info.get('root_post_id')),
        quoted_post=build_post(share.get('quoted_post'), ancestors + (identity,)),
        reposted_post=build_post(share.get('reposted_post'), ancestors + (identity,)),
        link_preview=_link_preview(info), is_pinned=bool((info.get('pinned_post_info') or {}).get('is_pinned_to_profile')))
