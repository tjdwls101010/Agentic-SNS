"""Pure normalization of Threads' raw objects into the model's records; nested unavailability stays at its own post."""
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..model import Counts, Media, Post, User


def _identifier(value: object) -> str | None:
    """Return an ASCII-decimal identifier string, or ``None`` for any other value."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value) if value >= 0 else None
    if isinstance(value, str) and value and value.isascii() and value.isdecimal():
        return value
    return None


def _node_identifier(node: dict[str, Any]) -> str | None:
    primary = node.get("pk")
    return _identifier(node.get("id") if primary is None else primary)


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped and stripped.lstrip("-").isdigit():
            return int(stripped)
    return None


def _best_candidate(value: object) -> dict[str, Any] | None:
    """Select the usable candidate with the largest pixel area, preserving tie order."""
    if not isinstance(value, list):
        return None
    usable = [
        candidate
        for candidate in value
        if isinstance(candidate, dict)
        and isinstance(candidate.get("url"), str)
        and candidate["url"]
    ]
    if not usable:
        return None

    def area(candidate: dict[str, Any]) -> int:
        width = _integer(candidate.get("width"))
        height = _integer(candidate.get("height"))
        if width is None or height is None:
            return -1
        return width * height

    return max(usable, key=area)


def build_media(raw_media_item: dict[str, Any]) -> Media:
    """Normalize one Instagram-style Threads media object."""
    media_type = _integer(raw_media_item.get("media_type"))
    image_versions = raw_media_item.get("image_versions2")
    image_candidates = (
        image_versions.get("candidates") if isinstance(image_versions, dict) else None
    )
    image = _best_candidate(image_candidates)
    video = _best_candidate(raw_media_item.get("video_versions"))

    if media_type == 2:
        selected = video or image
    else:
        selected = image or video

    if media_type == 1:
        kind = "photo"
    elif media_type == 2:
        kind = "video"
    elif media_type == 8:
        kind = "carousel"
    elif media_type == 19:
        kind = "unknown"
    elif video is not None:
        kind = "video"
    elif image is not None:
        kind = "photo"
    else:
        kind = "unknown"

    selected = selected or {}
    url = selected.get("url") if isinstance(selected.get("url"), str) else ""
    width = _integer(selected.get("width"))
    height = _integer(selected.get("height"))
    if width is None:
        width = _integer(raw_media_item.get("original_width"))
    if height is None:
        height = _integer(raw_media_item.get("original_height"))
    alt_text = raw_media_item.get("accessibility_caption")

    return Media(
        kind=kind,
        url=url,
        width=width,
        height=height,
        alt_text=alt_text if isinstance(alt_text, str) else None,
    )


def _unwrap(url: object) -> object:
    """Threads routes outbound links through l.threads.com/?u=<destination>&e=<tracking>; keep the destination."""
    if not isinstance(url, str):
        return url
    parts = urlsplit(url)
    if parts.hostname == "l.threads.com":
        destination = parse_qs(parts.query).get("u", [None])[0]
        if destination and urlsplit(destination).scheme in ("http", "https"):
            return destination
    return url


def _link_preview(text_post_app_info: dict[str, Any]) -> dict[str, str | None] | None:
    attachment = text_post_app_info.get("link_preview_attachment")
    if not isinstance(attachment, dict):
        return None
    url = _unwrap(attachment.get("url"))
    title = attachment.get("title")
    normalized = {
        "url": url if isinstance(url, str) else None,
        "title": title if isinstance(title, str) else None,
    }
    return normalized if any(value is not None for value in normalized.values()) else None


def _post_media(raw_post: dict[str, Any]) -> list[Media]:
    carousel = raw_post.get("carousel_media")
    if isinstance(carousel, list) and carousel:
        raw_items = [item for item in carousel if isinstance(item, dict)]
    elif isinstance(raw_post.get("image_versions2"), dict) or isinstance(
        raw_post.get("video_versions"), list
    ):
        raw_items = [raw_post]
    else:
        raw_items = []
    return [media for media in (build_media(item) for item in raw_items) if media.url]


def build_user(raw):
    if not isinstance(raw, dict) or _node_identifier(raw) is None:
        return None
    name = raw.get('username') or ''
    return User(id=_node_identifier(raw), username=name, full_name=raw.get('full_name'),
        is_verified=raw.get('is_verified', raw.get('text_post_app_is_verified')),
        private=raw.get('text_post_app_is_private'), follower_count=_integer(raw.get('follower_count')),
        bio=raw.get('biography'), bio_links=[x['url'] for x in raw.get('bio_links') or [] if isinstance(x, dict) and x.get('url')],
        friendship_status=raw.get('friendship_status') or {}, profile_pic_url=raw.get('profile_pic_url'),
        url='https://www.threads.com/@' + name if name else None)


def build_counts(raw):
    raw = raw if isinstance(raw, dict) else {}
    return Counts(*(_integer(raw.get(key)) for key in ('followers', 'following', 'mutuals')))


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
