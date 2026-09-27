"""What Yahoo's own failure messages say, read as the prescription they carry."""
import re

# Two different limits: a span one request may cover, and how far back a granularity is served at all.
CONSTRAINTS = (
    (re.compile(r"[Oo]nly (\d+) days? worth of (\S+) granularity"), "span"),
    (re.compile(r"must be within the last (\d+) days"), "reach"),
)


def is_rate_limited(exc):
    return "429" in str(exc) or "RateLimit" in type(exc).__name__


def upstream_fix(message, item, args):
    """When the source's own refusal carries the constraint, that constraint is the prescription.

    Every upstream failure used to receive the same sentence about verifying the symbol, so a message that said
    plainly how many days were allowed was answered with advice to doubt the ticker.
    """
    text = str(message)
    for pattern, kind in CONSTRAINTS:
        found = pattern.search(text)
        if not found:
            continue
        days = int(found.group(1))
        interval = getattr(args, "interval", None)
        asked = getattr(args, "period", None) or f"{getattr(args, 'start', '')}..{getattr(args, 'end', '')}"
        coarser = f"; beyond that, a coarser --interval than {interval} (schema prices history lists the limits known)." if interval else "."
        if kind == "span":
            return (f"The source serves at most {days} days of this granularity per request, and {asked} is longer. "
                    f"Retry with --period {days}d or a --start/--end span of at most {days} days" + coarser)
        return (f"The source serves this granularity only for the last {days} days, and {asked} reaches further back. "
                f"Retry with --period {days}d or a --start inside the last {days} days" + coarser)
    if "No data found" in text or "may be delisted" in text or "symbol may be delisted" in text:
        return "The source has no data for this symbol and dataset. Confirm the symbol with search, which reports the exchange and instrument type, or choose a dataset this instrument type reports."
    return f"Retry later, or confirm the symbol and dataset with search and schema {item.path if item else ''}".rstrip() + "; use --timeout SECONDS if the target timed out."
