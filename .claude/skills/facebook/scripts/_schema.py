"""Shared JSON schema helpers and UTC serialization."""

from datetime import UTC, datetime

def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_schema_fields(
    sample: dict, descriptions: dict[str, tuple[str, str]], *, optional: set[str]
) -> list[dict]:
    """Field descriptors for every key a ``to_dict()`` can emit, in that order.

    Anchored on real ``to_dict()`` output rather than ``dataclasses.fields`` —
    see ``_schema_representative_post``. Shared by ``Post`` and ``Comment`` so
    a second output object cannot drift into a second schema convention.
    """
    return [
        {
            "name": key,
            "type": descriptions[key][0],
            "description": descriptions[key][1],
            "always_present": key not in optional,
        }
        for key in sample
    ]


_JSON_SCHEMA_TYPES: dict[str, dict] = {
    "string": {"type": "string"},
    "string | null": {"type": ["string", "null"]},
    "boolean": {"type": "boolean"},
    "boolean | null": {"type": ["boolean", "null"]},
    "integer": {"type": "integer"},
    "integer | null": {"type": ["integer", "null"]},
    "array<object>": {"type": "array", "items": {"type": "object"}},
    "object | null": {"type": ["object", "null"]},
    "object": {"type": "object"},
}


def build_json_schema(title: str, description: str, fields: list[dict]) -> dict:
    properties = {}
    required = []
    for field in fields:
        prop = dict(_JSON_SCHEMA_TYPES[field["type"]])
        prop["description"] = field["description"]
        properties[field["name"]] = prop
        if field["always_present"]:
            required.append(field["name"])
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": title,
        "description": description,
        "type": "object",
        "properties": properties,
        "required": required,
    }




def timestamp(value) -> datetime | None:
    """Convert an integer Unix timestamp, treating invalid wire values as unknown."""
    if type(value) is not int:
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
