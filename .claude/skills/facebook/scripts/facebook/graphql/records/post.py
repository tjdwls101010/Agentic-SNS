"""Post records: every field decided explicitly by the builder, and described once in FIELDS.

Reinterpreting an existing field's meaning is a breaking change; adding one is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from facebook.graphql.records import parse
from facebook.graphql.records.fields import _iso, timestamp


@dataclass
class Media:
    kind: str  # "image" | "video" | "unknown"
    #: scontent/fbcdn URL — signed, expiring, viewer-scoped; never printed in diagnostics.
    url: str
    width: int | None
    height: int | None

    def to_dict(self) -> dict:
        return {"kind": self.kind, "url": self.url, "width": self.width, "height": self.height}


@dataclass
class LinkAttachment:
    url: str  # external/shared link target
    title: str | None
    description: str | None

    def to_dict(self) -> dict:
        return {"url": self.url, "title": self.title, "description": self.description}


@dataclass
class Post:
    id: str  # feedback id — stable identity, dedup/merge key
    url: str | None  # permalink (story.wwwURL)
    type: (
        str  # "status" | "photo" | "video" | "shared" | "link" | "reel" | "life_event" | "unknown"
    )
    pinned: bool
    author_name: str | None
    author_url: str | None
    author_id: str | None
    created_at: datetime | None  # from creation_time (unix int, UTC); None if unlocatable
    edited_at: datetime | None
    text: str  # full body (message.text), truncation-resolved; "" if none
    text_truncated: bool  # payload carried a truncation marker, regardless of resolution
    text_resolved: bool  # a fallback fetch recovered the full body
    media: list[Media]
    links: list[LinkAttachment]
    reaction_count: int | None
    comment_count: int | None
    share_count: int | None
    shared_post: Post | None  # attached_story (quoted/shared)
    #: Which surface this post came from — "timeline" | "newsfeed" | "group" |
    #: "search" | "permalink". Chained command outputs get mixed together by
    #: callers, so a post has to be able to say where it came from without
    #: external context. "permalink" is the honest answer for a post fetched by
    #: URL: its original surface is genuinely unknown.
    source: str
    captured_at: datetime  # UTC, when this tool captured the response
    sponsored: bool = False
    incomplete: bool = False

    @property
    def undated(self) -> bool:
        return self.created_at is None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "type": self.type,
            "pinned": self.pinned,
            "sponsored": self.sponsored,
            "undated": self.undated,
            "incomplete": self.incomplete,
            "author_name": self.author_name,
            "author_url": self.author_url,
            "author_id": self.author_id,
            "created_at": _iso(self.created_at),
            "edited_at": _iso(self.edited_at),
            "text": self.text,
            "text_truncated": self.text_truncated,
            "text_resolved": self.text_resolved,
            "media": [m.to_dict() for m in self.media],
            "links": [link.to_dict() for link in self.links],
            "reaction_count": self.reaction_count,
            "comment_count": self.comment_count,
            "share_count": self.share_count,
            "shared_post": self.shared_post.to_dict() if self.shared_post is not None else None,
            "source": self.source,
            "captured_at": _iso(self.captured_at),
        }


def _find_pinned(story: dict) -> bool:
    for node in parse.iter_story_dicts(story, exclude_keys=parse.SHARE_EXCLUDE):
        for key, value in node.items():
            key_lower = key.lower()
            if value is True and key_lower in {"is_pinned", "is_pinned_story", "is_featured"}:
                return True
    return False


def _find_edited_time(story: dict) -> int | None:
    for node in parse.iter_story_dicts(story, exclude_keys=parse.SHARE_EXCLUDE):
        for key, value in node.items():
            key_lower = key.lower()
            if isinstance(value, int) and "edit" in key_lower and "time" in key_lower:
                return value
    return None


def _find_count(story: dict, key: str, subkey: str) -> int | None:
    feedback = story.get("feedback")
    if not isinstance(feedback, dict):
        return None
    value = feedback.get(key)
    if isinstance(value, dict):
        inner = value.get(subkey)
        return inner if type(inner) is int and inner >= 0 else None
    return value if type(value) is int and value >= 0 else None


def _find_comment_count(story: dict) -> int | None:
    """Confirmed via live capture: comment count lives at
    ``feedback.comment_rendering_instance.comments.total_count`` — NOT a
    ``comment_count`` key (that name doesn't exist on a real story; only
    ``reaction_count``/``share_count`` matched their originally-guessed shape).
    """
    feedback = story.get("feedback")
    if not isinstance(feedback, dict):
        return None
    instance = feedback.get("comment_rendering_instance")
    if not isinstance(instance, dict):
        return None
    comments = instance.get("comments")
    if not isinstance(comments, dict):
        return None
    total = comments.get("total_count")
    return total if type(total) is int and total >= 0 else None


def _classify_type(story: dict, media: list[dict], links: list[dict], has_shared: bool) -> str:
    for node in parse.iter_story_dicts(story, exclude_keys=parse.SHARE_EXCLUDE):
        for key in node:
            key_lower = key.lower()
            if "reel" in key_lower:
                return "reel"
            if "life_event" in key_lower or "lifeevent" in key_lower:
                return "life_event"
    if has_shared:
        return "shared"
    if any(m["kind"] == "video" for m in media):
        return "video"
    if any(m["kind"] == "image" for m in parse.find_media(story, exclude_link_thumbnails=True)):
        return "photo"
    if links:
        return "link"
    if parse.find_message_text(story):
        return "status"
    return "unknown"


#: Every key a Post record can carry, as "JSON type — meaning". Nested shapes are listed as media[].kind and so on;
#: shared_post is itself a Post. Kept beside the dataclass so a field change edits one file.
FIELDS = {
    "id": "string — stable identity of the post; dedupe on this, never on captured_at",
    "url": "string | null — permalink; the post command's argument",
    "type": "string — status | photo | video | shared | link | reel | life_event | unknown",
    "pinned": "boolean — pinned to the top of its timeline or group, so it can be old; passes any date window",
    "sponsored": "boolean — an advertisement; feed skips these unless --include-sponsored",
    "undated": "boolean — Facebook sent no usable creation time; passes any date window",
    "incomplete": "boolean — part of this post arrived in a piece that could not be merged; fields may be missing",
    "author_name": "string | null — display name of the author",
    "author_url": "string | null — the author's profile URL; the profile and about commands' argument",
    "author_id": "string | null — numeric id of the author; matches about's profile_id",
    "created_at": "string | null — ISO-8601 UTC time the post was created",
    "edited_at": "string | null — ISO-8601 UTC time of the last edit; null when Facebook sent none",
    "text": "string — the body as received; empty if the post has none",
    "text_truncated": "boolean — Facebook marked the received body as cut; the rest is not known",
    "text_resolved": "boolean — a later request recovered the full body of a cut post",
    "media": "array<object> — photos and videos of the post itself, in order",
    "media[].kind": "string — image | video",
    "media[].url": "string — signed, expiring, viewer-scoped; share only when the user needs the media",
    "media[].width": "integer | null — pixels",
    "media[].height": "integer | null — pixels",
    "links": "array<object> — external links the post shares",
    "links[].url": "string — the link target",
    "links[].title": "string | null — the link preview's title",
    "links[].description": "string | null — the link preview's description",
    "reaction_count": "integer | null — reactions; null when not sent",
    "comment_count": "integer | null — comments; null when not sent",
    "share_count": "integer | null — shares; null when not sent",
    "shared_post": "object | null — the post this one shares, itself a post record; shares can nest",
    "source": "string — where it was read: newsfeed | timeline | group | search | permalink",
    "captured_at": "string — ISO-8601 UTC time this tool received it; changes every run",
}


def build_post(story: dict, *, captured_at: datetime, source: str) -> Post:
    """Normalize one deep-merged story dict (from ``parse.parse_story_nodes``) into a ``Post``.

    The caller owns any follow-up request for truncated text and sets
    text/text_resolved only after recovering the full body.
    """
    actors = parse.find_actors(story)
    author = actors[0] if actors else {}
    author_id = author.get("id")

    raw_media = parse.find_media(story)
    raw_links = parse.find_links(story)

    attached = parse.find_attached_story(story)
    has_attached = isinstance(attached, dict)
    identifiable = has_attached and isinstance(attached.get("feedback"), dict) and attached["feedback"].get("id") is not None
    shared_post = (
        build_post(attached, captured_at=captured_at, source=source)
        if identifiable
        else None
    )

    creation_time = parse.find_creation_time(story)
    edited_time = _find_edited_time(story)

    return Post(
        id=str(story["feedback"]["id"]),
        url=parse.find_permalink(story),
        type=_classify_type(story, raw_media, raw_links, has_attached),
        pinned=_find_pinned(story),
        author_name=author.get("name") if isinstance(author.get("name"), str) else None,
        author_url=author.get("url") if isinstance(author.get("url"), str) else None,
        author_id=str(author_id) if author_id is not None else None,
        created_at=timestamp(creation_time),
        edited_at=timestamp(edited_time),
        text=parse.find_message_text(story) or "",
        text_truncated=has_truncation_marker(story),
        text_resolved=False,
        media=[
            Media(kind=m["kind"], url=m["url"], width=m.get("width"), height=m.get("height"))
            for m in raw_media
        ],
        links=[
            LinkAttachment(
                url=link["url"], title=link.get("title"), description=link.get("description")
            )
            for link in raw_links
        ],
        reaction_count=_find_count(story, "reaction_count", "count"),
        comment_count=_find_comment_count(story),
        share_count=_find_count(story, "share_count", "count"),
        shared_post=shared_post,
        source=source,
        captured_at=captured_at,
        sponsored=_find_sponsored(story),
        incomplete=bool(story.get("incomplete")) or (has_attached and not identifiable)
        or bool(shared_post and shared_post.incomplete),
    )


def has_truncation_marker(story: dict) -> bool:
    """Ignore the universal display line-limit and shared/comment content."""
    for node in parse.iter_story_dicts(story, exclude_keys=parse.SHARE_EXCLUDE):
        for key, value in node.items():
            if key == "message_truncation_line_limit":
                continue
            if value and any(marker in key.lower() for marker in ("truncat", "preferred_body", "see_more")):
                return True
    return False


def _find_sponsored(story: dict) -> bool:
    return any(node.get("is_sponsored") is True or isinstance(node.get("sponsored_data"), dict)
               or bool(node.get("ad_id"))
               for node in parse.iter_story_dicts(story, exclude_keys=parse.SHARE_EXCLUDE))


def posts_from_raw(raw, source, captured_at=None):
    parsed = parse.parse_story_nodes([raw])
    return [build_post(parsed.stories[key], source=source, captured_at=captured_at or datetime.now().astimezone()
                       ).to_dict() for key in parsed.top_level_ids()]


def requested_story(raw):
    """The permalink's own root story, never a decoy story elsewhere in the response; None when absent."""
    parsed = parse.parse_story_nodes([raw])
    for chunk in parse.iter_json_objects([raw]):
        if chunk.get('path'):
            continue
        data = chunk.get('data')
        if isinstance(data, dict):
            root = data.get('node_v2') or data.get('node') or data.get('story')
            if isinstance(root, dict):
                identity = (root.get('feedback') or {}).get('id')
                if identity is not None and str(identity) in parsed.stories:
                    return parsed.stories[str(identity)]
    return None
