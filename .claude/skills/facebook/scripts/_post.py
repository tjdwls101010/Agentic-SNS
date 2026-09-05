"""Output schema (plan §6). Decided pre-1.0: additive fields later are a minor
bump, but reinterpreting an existing field's meaning is a breaking change.

No field defaults except ``Post.raw`` (opt-in, PII-heavy) — the parser must
decide every field explicitly rather than silently defaulting a forgotten one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import _parse as parse
from _schema import _iso, build_schema_fields, build_json_schema, timestamp


@dataclass
class Media:
    kind: str  # "image" | "video" | "unknown"
    #: scontent/fbcdn URL — SIGNED, EXPIRES, viewer-scoped. Treat as sensitive
    #: (plan §17 G-media-expiry, §21) — never printed unredacted in diagnostics.
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
    is_pinned: bool
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
    raw: dict | None = None  # only populated when include_raw=True
    sponsored: bool = False
    incomplete: bool = False

    @property
    def pinned(self) -> bool:
        return self.is_pinned

    @property
    def undated(self) -> bool:
        return self.created_at is None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "url": self.url,
            "type": self.type,
            "is_pinned": self.is_pinned,
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
            **({"raw": self.raw} if self.raw is not None else {}),
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


#: One entry per key ``Post.to_dict()`` can emit: (JSON type, one-line meaning).
#: Co-located with the dataclass so a field rename/addition is edited in the
#: same file as the field itself, not in a separate skill repo (plan §10a).
#: Types are the JSON shape a consumer of the output file sees, NOT the
#: Python dataclass annotation — e.g. ``created_at`` is ``datetime | None``
#: in Python but serializes to ``string | null`` via ``_iso()``.
FIELD_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "sponsored": ("boolean", "The post carries an explicit advertising marker."),
    "pinned": ("boolean", "Pinned post; alias of is_pinned."),
    "undated": ("boolean", "No usable creation timestamp was received."),
    "incomplete": ("boolean", "A response fragment could not be merged or decoded."),
    "id": (
        "string",
        "Stable identity/dedup key for this post — dedupe on this, never on captured_at.",
    ),
    "url": ("string | null", "Permalink to the post, or null if one could not be located."),
    "type": (
        "string",
        "One of status | photo | video | shared | link | reel | life_event | unknown.",
    ),
    "is_pinned": (
        "boolean",
        "True for a pinned post; date-window handling belongs to the caller.",
    ),
    "author_name": ("string | null", "Display name of the post's author."),
    "author_url": ("string | null", "Profile URL of the post's author."),
    "author_id": ("string | null", "Numeric id of the post's author."),
    "created_at": (
        "string | null",
        "ISO-8601 UTC timestamp with a 'Z' suffix; null if it could not be located.",
    ),
    "edited_at": (
        "string | null",
        "ISO-8601 UTC timestamp of the last edit; null if never edited.",
    ),
    "text": ("string", "Full post body, truncation-resolved when possible; empty string if none."),
    "text_truncated": (
        "boolean",
        "The captured payload carried a truncation marker, regardless of whether it was resolved.",
    ),
    "text_resolved": ("boolean", "A follow-up permalink fetch recovered the full truncated text."),
    "media": (
        "array<object>",
        "List of {kind, url, width, height}. url is a signed, expiring, viewer-scoped "
        "fbcdn/scontent link — treat as sensitive, never print unredacted.",
    ),
    "links": ("array<object>", "List of {url, title, description} for shared external links."),
    "reaction_count": ("integer | null", "Reaction count, or null if unavailable."),
    "comment_count": ("integer | null", "Comment count, or null if unavailable."),
    "share_count": ("integer | null", "Share count, or null if unavailable."),
    "shared_post": (
        "object | null",
        "A nested post for an attached/shared story, or null. Can itself have a "
        "non-null shared_post on a share-of-a-share — nesting isn't capped at one level.",
    ),
    "source": (
        "string",
        "Which surface this post came from: timeline | newsfeed | group | search | "
        "permalink ('permalink' means it was addressed directly by URL, so its "
        "original surface is unknown). Lets outputs from different commands be "
        "merged without losing their provenance.",
    ),
    "captured_at": (
        "string",
        "ISO-8601 UTC timestamp of when this tool captured the response. Changes every "
        "run — never a dedup key.",
    ),
    "raw": (
        "object",
        "Present only when include_raw=True. The unredacted captured story node.",
    ),
}


def _schema_representative_post() -> Post:
    """A fully-populated ``Post`` (including ``raw``) purely so ``to_dict()``
    emits every possible key — the source of truth for ``schema_fields()``.

    Deliberately NOT ``dataclasses.fields(Post)``: that returns 20 names
    including ``raw`` unconditionally, but ``to_dict()`` only emits ``raw``
    when it is populated (i.e. only under ``--raw``), so fields() would
    mis-document it as always-present.
    """
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Post(
        id="1",
        url=None,
        type="status",
        is_pinned=False,
        author_name=None,
        author_url=None,
        author_id=None,
        created_at=now,
        edited_at=None,
        text="",
        text_truncated=False,
        text_resolved=False,
        media=[],
        links=[],
        reaction_count=None,
        comment_count=None,
        share_count=None,
        shared_post=None,
        source="timeline",
        captured_at=now,
        raw={},
    )


def schema_fields() -> list[dict]:
    """Ordered field descriptors for every key ``Post.to_dict()`` can emit.

    Each entry: ``name``, ``type`` (JSON type, not the Python annotation),
    ``description``, and ``always_present`` (False only for ``raw``).
    """
    return build_schema_fields(
        _schema_representative_post().to_dict(), FIELD_DESCRIPTIONS, optional={"raw"}
    )


#: Maps this module's JSON-type labels to JSON Schema (draft 2020-12) type
#: constraints. Kept as an explicit table, not derived from the dataclass
#: annotations, for the same reason ``schema_fields`` avoids ``dataclasses.
#: fields`` — the Python type and the JSON type are not the same thing here.
def json_schema() -> dict:
    """The fetch output object as JSON Schema (draft 2020-12)."""
    return build_json_schema(
        "Post",
        "One element of the fetch output array (or one NDJSON line).",
        schema_fields(),
    )


def build_post(
    story: dict, *, captured_at: datetime, source: str, include_raw: bool = False
) -> Post:
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
        build_post(attached, captured_at=captured_at, source=source, include_raw=include_raw)
        if identifiable
        else None
    )

    creation_time = parse.find_creation_time(story)
    edited_time = _find_edited_time(story)

    return Post(
        id=str(story["feedback"]["id"]),
        url=parse.find_permalink(story),
        type=_classify_type(story, raw_media, raw_links, has_attached),
        is_pinned=_find_pinned(story),
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
        raw=story if include_raw else None,
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
