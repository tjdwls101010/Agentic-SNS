"""Search result shaping (plan §5).

Search is the one surface that returns mixed result types: a "top" search
interleaves posts with people, pages and groups, and only the post-shaped ones
are story-shaped enough for ``parse.py`` (recon §4). Non-post hits become a
light :class:`Entity` instead. A requested vertical resolves Facebook's
ambiguous ``User`` typename, but never overrides an unambiguous ``Group``:
recursive payloads also contain authors, and relabeling one as a group invents
a search result that was never returned.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from _parse import iter_json_objects

from _schema import _iso, build_json_schema, build_schema_fields

#: CLI ``--type`` -> the ``args.experience.type`` that selects that vertical.
#: Captured live; the doc_id is identical across all five.
SEARCH_EXPERIENCE_TYPES = {
    "top": "GLOBAL_SEARCH",
    "posts": "POSTS_TAB",
    "people": "PEOPLE_TAB",
    "pages": "PAGES_TAB",
    "groups": "GROUPS_TAB",
}

#: Which ``--type`` values return entities rather than posts, and as what kind.
#: The requested vertical is authoritative — Facebook returns Pages with
#: ``__typename: "User"`` here, so the payload alone cannot tell a page from a
#: person. ``Group`` remains authoritative in either direction, because unlike
#: User/Page it is unambiguous. Only "top" otherwise guesses from ``__typename``.
_ENTITY_KIND_BY_TYPE = {"people": "person", "pages": "page", "groups": "group"}


@dataclass
class Entity:
    kind: str  # "person" | "page" | "group"
    id: str
    name: str | None
    url: str | None
    verified: bool | None
    captured_at: datetime

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.id,
            "name": self.name,
            "url": self.url,
            "verified": self.verified,
            "captured_at": _iso(self.captured_at),
        }


FIELD_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "kind": (
        "string",
        "person | page | group. Its presence is also what distinguishes an entity from a "
        "Post in mixed search output — Posts carry `source` instead.",
    ),
    "id": ("string", "Numeric id — the handle to chain into `profile` or `about` or `group`."),
    "name": ("string | null", "Display name."),
    "url": ("string | null", "Facebook URL for this person, page, or group."),
    "verified": ("boolean | null", "Verified badge, or null when the payload omits it."),
    "captured_at": (
        "string",
        "ISO-8601 UTC timestamp of when this tool captured the response.",
    ),
}


def _representative() -> Entity:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return Entity(kind="person", id="1", name=None, url=None, verified=None, captured_at=now)


def schema_fields() -> list[dict]:
    return build_schema_fields(_representative().to_dict(), FIELD_DESCRIPTIONS, optional=set())


def json_schema() -> dict:
    return build_json_schema(
        "Entity",
        "A non-post search hit (person, page, or group).",
        schema_fields(),
    )


_ENTITY_TYPENAMES = {"User", "Page", "Group"}


def _is_entity_shaped(obj: Any) -> bool:
    return (
        isinstance(obj, dict)
        and obj.get("__typename") in _ENTITY_TYPENAMES
        and obj.get("id") is not None
        and isinstance(obj.get("name"), str)
        and isinstance(obj.get("url"), str)
    )


def iter_entity_nodes(bodies: Iterable[bytes]) -> Iterator[dict]:
    """Inspect search result roots, never arbitrary authors, admins or members."""
    wrappers = {"node", "result", "entity", "profile", "group", "page", "user",
                "rendering_strategy", "view_model"}

    def result_entity(node: Any) -> Iterator[dict]:
        if not isinstance(node, dict):
            return
        if _is_entity_shaped(node):
            yield node
            return
        if node.get("__typename") in {"Story", "Comment"} or "feedback" in node:
            return
        # 성진: Only known result wrappers are followed; add paths after capture validation.
        for key in node:
            if key not in wrappers:
                continue
            child = node.get(key)
            if isinstance(child, list):
                for item in child:
                    yield from result_entity(item)
            else:
                yield from result_entity(child)

    def connections(obj: Any) -> Iterator[dict]:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key in {"results", "search_results"} and isinstance(value, dict):
                    for edge in value.get("edges") or []:
                        if isinstance(edge, dict):
                            yield from result_entity(edge)
                    for node in value.get("nodes") or []:
                        yield from result_entity(node)
                else:
                    yield from connections(value)
        elif isinstance(obj, list):
            for item in obj:
                yield from connections(item)

    for envelope in iter_json_objects(bodies):
        for chunk in [envelope, *(envelope.get("incremental") or [])]:
            if not isinstance(chunk, dict):
                continue
            path = chunk.get("path") or []
            result_indices = [i for i, key in enumerate(path) if key in ("results", "search_results")]
            if result_indices:
                tail = path[result_indices[-1] + 1:]
                if (len(tail) >= 2 and tail[0] in {"edges", "nodes"}
                        and type(tail[1]) is int
                        and all(type(key) is int or key in wrappers for key in tail[2:])):
                    yield from result_entity(chunk.get("data"))
            elif not path:
                yield from connections(chunk)


def build_entities(
    bodies: Iterable[bytes], *, search_type: str, captured_at: datetime
) -> list[Entity]:
    """De-duplicated entity hits, in first-seen order.

    Group searches skip non-Group nodes because the recursive response also
    contains entity-shaped post authors and members; the vertical cannot turn
    those nested Users into genuine group results.
    """
    default_kind = _ENTITY_KIND_BY_TYPE.get(search_type)
    seen: set[str] = set()
    result: list[Entity] = []
    for node in iter_entity_nodes(bodies):
        typename = node.get("__typename")
        if search_type == "groups" and typename != "Group":
            continue
        entity_id = str(node["id"])
        if entity_id in seen:
            continue
        seen.add(entity_id)
        kind = {"Group": "group", "Page": "page"}.get(typename, default_kind or "person")
        result.append(
            Entity(
                kind=kind,
                id=entity_id,
                name=node.get("name"),
                url=node.get("url"),
                verified=node.get("is_verified")
                if isinstance(node.get("is_verified"), bool)
                else None,
                captured_at=captured_at,
            )
        )
    return result


def returns_entities(search_type: str) -> bool:
    return search_type in _ENTITY_KIND_BY_TYPE
