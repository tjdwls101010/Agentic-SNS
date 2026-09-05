"""Pure media/identity normalization ported from agentic-threads; no I/O."""
from dataclasses import dataclass, asdict
from typing import Any

@dataclass
class Media:
    kind: str
    url: str
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None

    def to_dict(self):
        return asdict(self)

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


def _link_preview(text_post_app_info: dict[str, Any]) -> dict[str, str | None] | None:
    attachment = text_post_app_info.get("link_preview_attachment")
    if not isinstance(attachment, dict):
        return None
    url = attachment.get("url")
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
