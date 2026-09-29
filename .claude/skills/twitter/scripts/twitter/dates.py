"""Date parsing shared by argument checks and record building; nothing site-specific."""
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


def moment(value):
    """A Unix time read from local state, or None when it is not a finite number."""
    try:
        return float(value) if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value)) else None
    except OverflowError:
        return None


def timestamp(value):
    if not value:
        return None
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00')) if 'T' in value and '-' in value else parsedate_to_datetime(value)
        return date.replace(tzinfo=date.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None
