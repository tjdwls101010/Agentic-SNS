"""Small readers shared by the record builders: Reddit's loose types become strict ones or None."""
import math
import unicodedata
from datetime import datetime, timezone

BASE = 'https://www.reddit.com'


def text(value):
    return value if isinstance(value, str) else ''


def optional(value):
    """A string with something visible in it, else None (Reddit sends flairs made of a zero-width space)."""
    if not isinstance(value, str):
        return None
    return value if any(not c.isspace() and unicodedata.category(c) != 'Cf' for c in value) else None


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def timestamp(value):
    if number(value) is None:
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def absolute(value):
    value = text(value)
    return BASE + value if value.startswith('/') and not value.startswith('//') else value


def fullname(data, kind):
    name = text(data.get('name'))
    return name if name.startswith(kind + '_') else kind + '_' + text(data.get('id'))


def images(metadata, order=None):
    """[{url, caption}] from a media_metadata map: in `order` ([(media_id, caption)]) when given, else as sent;
    an item that is marked deleted or has no source is skipped."""
    metadata = metadata if isinstance(metadata, dict) else {}
    keys = order if order is not None else [(key, '') for key in metadata]
    found = []
    for media_id, caption in keys:
        source = (metadata.get(media_id) or {}).get('s') or {}
        url = text(source.get('u') or source.get('gif') or source.get('mp4'))
        if url:
            found.append({'url': url, 'caption': text(caption)})
    return found
