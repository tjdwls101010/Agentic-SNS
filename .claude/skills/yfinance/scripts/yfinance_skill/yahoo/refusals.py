"""What Yahoo's own failure messages say, read as the prescription they carry."""
import re

CONSTRAINTS = (
    (re.compile(r"[Oo]nly (\d+) days? worth of (\S+) granularity"), "days"),
    (re.compile(r"must be within the last (\d+) days"), "days"),
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
        if found and kind == "days":
            days = int(found.group(1))
            interval = getattr(args, "interval", None)
            asked = getattr(args, "period", None) or f"{getattr(args, 'start', '')}..{getattr(args, 'end', '')}"
            return (f"The source allows {days} days per request at this granularity, and {asked} is longer. "
                    f"Retry with --period {days}d, or give --start and --end inside the last {days} days"
                    + (f"; a longer range needs a coarser --interval than {interval} (1h and 1d have no such limit)." if interval else "."))
    if "No data found" in text or "may be delisted" in text or "symbol may be delisted" in text:
        return "The source has no data for this symbol and dataset. Confirm the symbol with search, which reports the exchange and instrument type, or choose a dataset this instrument type reports."
    return f"Retry later, or confirm the symbol and dataset with search and schema {item.path if item else ''}".rstrip() + "; use --timeout SECONDS if the target timed out."
