"""Text primitives every platform's record lines use: one-line values, quoting, clipped text with its counts, times
and counts as a person reads them."""
import json
from datetime import UTC, datetime

DEFAULT_CHARS = 180
_BREAKS = ('\r\n', '\n', '\r', ' ', ' ')


def line(value):
    """A value on one line: every line break becomes ⏎."""
    text = str(value)
    for mark in _BREAKS:
        text = text.replace(mark, '⏎')
    return text


def quote(value):
    return json.dumps(line(value), ensure_ascii=False)


def limit_of(chars):
    """--chars as a clipping length: None (default) is DEFAULT_CHARS, 0 is everything."""
    return DEFAULT_CHARS if chars is None else (None if chars == 0 else chars)


def clip(text, chars):
    """(shown, n, m): the first `chars` characters (all when chars is None or 0) with … when cut, and the counts."""
    text = text or ''
    shown = text if not chars else text[:chars]
    return shown + ('…' if len(shown) < len(text) else ''), len(shown), len(text)


def shown(text, chars, label='text'):
    """label[N of M chars shown]: "…" — the reader always knows how much of a text it saw."""
    value, n, m = clip(text, chars)
    return f'{label}[{n} of {m} chars shown]: {quote(value)}'


def count(value):
    return '?' if value is None else str(value)


def time(value):
    """An ISO time as local time to the minute; 'undated' when there is none."""
    if not value:
        return 'undated'
    moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone().isoformat(timespec='minutes')
