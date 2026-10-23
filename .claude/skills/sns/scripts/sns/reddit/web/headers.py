"""Reddit's rate-limit headers in the skill's terms. Reddit reports a bucket's window in three headers on each .json
answer: x-ratelimit-used and -remaining (counts) and -reset (seconds until the window resets). Only a set of three finite,
non-negative numbers is a usable statement; anything else leaves the bucket's state unknown."""
import math

from sns.limits import Fact


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def limit_fact(ratelimit, now):
    """The limits.Fact the headers state (limit = used + remaining, reset as the epoch `now` + seconds), or None when
    the answer carried no usable window."""
    ratelimit = ratelimit if isinstance(ratelimit, dict) else {}
    used, remaining, reset = (_number(ratelimit.get(key)) for key in ('used', 'remaining', 'reset'))
    if None in (used, remaining, reset):
        return None
    return Fact(used + remaining, remaining, now + reset)


def reset_seconds(ratelimit):
    """Seconds until the window resets when the headers say so, else None (a 429 then holds for the policy's default)."""
    return _number((ratelimit if isinstance(ratelimit, dict) else {}).get('reset'))
