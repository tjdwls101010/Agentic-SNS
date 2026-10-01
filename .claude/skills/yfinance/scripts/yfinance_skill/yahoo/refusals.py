"""What Yahoo's own failure messages say, read into the failures this skill names. Which argument to change is the caller's to say."""
import re

# Two different limits: a span one request may cover, and how far back a granularity is served at all.
CONSTRAINTS = (
    (re.compile(r"[Oo]nly (\d+) days? worth of (\S+) granularity"), "span"),
    (re.compile(r"must be within the last (\d+) days"), "reach"),
)


class SourceFailure(Exception):
    """The source failed for a reason none of the narrower failures names; the message is the source's own."""


class RateLimited(SourceFailure):
    """The source refused because of request volume."""


class SourceConstraint(SourceFailure):
    """The source refused a range and said how far it serves: `kind` is span (days per request) or reach (days back from now)."""

    def __init__(self, message, kind, days):
        super().__init__(message)
        self.kind, self.days = kind, days


class NoData(SourceFailure):
    """The source said it holds no data for this symbol and dataset."""


def is_rate_limited(exc):
    return "429" in str(exc) or "RateLimit" in type(exc).__name__


def refusal(exc):
    """The failure an exception from the library or the source amounts to, keeping its message."""
    text = str(exc)
    if is_rate_limited(exc):
        return RateLimited(text)
    for pattern, kind in CONSTRAINTS:
        found = pattern.search(text)
        if found:
            return SourceConstraint(text, kind, int(found.group(1)))
    if "No data found" in text or "may be delisted" in text:
        return NoData(text)
    return SourceFailure(text)
