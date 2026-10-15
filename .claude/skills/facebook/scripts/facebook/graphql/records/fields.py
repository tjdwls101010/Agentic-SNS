"""UTC serialization shared by every record."""

from datetime import UTC, datetime

def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def timestamp(value) -> datetime | None:
    """Convert an integer Unix timestamp, treating invalid wire values as unknown."""
    if type(value) is not int:
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
