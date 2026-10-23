"""Facebook's integer unix times → ISO-8601 UTC strings."""
from datetime import UTC, datetime


def timestamp(value):
    """A datetime for an integer unix time; anything else (a string, a float, out of range) is unknown."""
    if type(value) is not int:
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace('+00:00', 'Z')
