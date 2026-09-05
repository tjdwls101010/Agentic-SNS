"""Profile About schema and extraction.

About fields stay flat because Facebook adds and renames sections. A fixed
name/work/education model would silently discard any field it did not predict;
the locale-independent ``section`` value preserves Facebook's own vocabulary.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from _parse import iter_json_objects

from _schema import _iso, build_json_schema, build_schema_fields


@dataclass
class ProfileField:
    profile_id: str
    section: str
    collection: str | None
    field_type: str | None
    text: str
    url: str | None
    captured_at: datetime

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "section": self.section,
            "collection": self.collection,
            "field_type": self.field_type,
            "text": self.text,
            "url": self.url,
            "captured_at": _iso(self.captured_at),
        }


FIELD_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "profile_id": (
        "string",
        "Numeric id of the described profile — matches a Post's author_id for joins.",
    ),
    "section": (
        "string",
        "Locale-independent field_section_type, such as directory_work or directory_college.",
    ),
    "collection": (
        "string | null",
        "Localized About sub-tab label for humans; never a stable key to branch on.",
    ),
    "field_type": ("string | null", "The field node's own field_type, when present."),
    "text": ("string", "The rendered About value."),
    "url": (
        "string | null",
        "Facebook link_url when the value points to another object; a chainable handle.",
    ),
    "captured_at": (
        "string",
        "ISO-8601 UTC timestamp of when this tool captured the response.",
    ),
}


def _representative() -> ProfileField:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return ProfileField(
        profile_id="1",
        section="directory_bio",
        collection=None,
        field_type=None,
        text="",
        url=None,
        captured_at=now,
    )


def schema_fields() -> list[dict]:
    return build_schema_fields(_representative().to_dict(), FIELD_DESCRIPTIONS, optional=set())


def json_schema() -> dict:
    return build_json_schema(
        "ProfileField",
        "One element of the about output array (or one NDJSON line).",
        schema_fields(),
    )


def iter_collections(bodies: Iterable[bytes]) -> list[dict[str, str]]:
    """Discover About sub-tabs without depending on their varying outer path."""
    result: list[dict[str, str]] = []
    seen: set[str] = set()

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            collections = obj.get("all_collections")
            if isinstance(collections, dict) and isinstance(collections.get("nodes"), list):
                for node in collections["nodes"]:
                    if not isinstance(node, dict):
                        continue
                    name, collection_id = node.get("name"), node.get("id")
                    if not isinstance(name, str) or not isinstance(collection_id, str):
                        continue
                    if collection_id not in seen:
                        seen.add(collection_id)
                        result.append({"name": name, "id": collection_id})
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    for chunk in iter_json_objects(bodies):
        walk(chunk)
    return result


def _iter_section_nodes(bodies: Iterable[bytes]) -> Iterator[dict]:
    def walk(obj: Any) -> Iterator[dict]:
        if isinstance(obj, dict):
            if isinstance(obj.get("field_section_type"), str):
                yield obj
            for value in obj.values():
                yield from walk(value)
        elif isinstance(obj, list):
            for item in obj:
                yield from walk(item)

    for chunk in iter_json_objects(bodies):
        yield from walk(chunk)


def build_fields(
    bodies: Iterable[bytes],
    *,
    profile_id: str,
    collection_names: Iterable[str | None],
    captured_at: datetime,
) -> list[ProfileField]:
    """Build de-duplicated fields, preserving response and field order."""
    seen: set[tuple[str, str]] = set()
    result: list[ProfileField] = []
    for body, collection in zip(bodies, collection_names, strict=True):
        for section_node in _iter_section_nodes([body]):
            section = section_node["field_section_type"]
            profile_fields = section_node.get("profile_fields")
            if not isinstance(profile_fields, dict):
                continue
            nodes = profile_fields.get("nodes")
            if not isinstance(nodes, list):
                continue
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                title = node.get("title")
                text = title.get("text") if isinstance(title, dict) else None
                if not isinstance(text, str):
                    continue
                key = (section, text)
                if key in seen:
                    continue
                seen.add(key)
                field_type = node.get("field_type")
                link_url = node.get("link_url")
                result.append(
                    ProfileField(
                        profile_id=profile_id,
                        section=section,
                        collection=collection,
                        field_type=field_type if isinstance(field_type, str) else None,
                        text=text,
                        url=link_url if isinstance(link_url, str) else None,
                        captured_at=captured_at,
                    )
                )
    return result
