"""What Yahoo's failures say, read into the skill's failure codes, on evidence the response itself carries.

`not_found` needs Yahoo to deny the symbol: its quoteSummary answers HTTP 404 with "Quote not found for symbol". A chart 404 ("No data found, symbol may be delisted") does not deny it, because a delisted symbol Yahoo still knows (TWTR, quoteType NONE) gets the same answer, and yfinance's own "possibly delisted" is a guess; both are `no_data`. `not_applicable` needs the quoteType confirmed and outside the product kind the dataset serves.
"""
import json
import re

from invest.receipts import Failure

# Two different limits: the span one request may cover, and how far back a granularity is served at all.
CONSTRAINTS = (
    (re.compile(r"[Oo]nly (\d+) days? worth of (\S+) granularity"), "span"),
    (re.compile(r"must be within the last (\d+) days"), "reach"),
)
DENIED = "Quote not found for symbol"
# 429 standing alone: a bare substring test also matched the digits of a timestamp inside a 422 refusal ("endTime=1791264293").
STATUS_429 = re.compile(r"(?<!\d)429(?!\d)|Too Many Requests")


def is_rate_limited(exc):
    return ("RateLimit" in type(exc).__name__ or getattr(getattr(exc, "response", None), "status_code", None) == 429
            or bool(STATUS_429.search(str(exc))))


def source_error(exc):
    """(HTTP status, Yahoo's error description) from the response an HTTPError carries, when it carries one."""
    response = getattr(exc, "response", None)
    if response is None:
        return None, None
    try:
        body = json.loads(response.text or "{}")
    except (ValueError, TypeError):
        return response.status_code, None
    for wrapper in body.values() if isinstance(body, dict) else ():
        error = wrapper.get("error") if isinstance(wrapper, dict) else None
        if isinstance(error, dict):
            return response.status_code, error.get("description")
    return response.status_code, None


def constraint_fix(kind, days, args):
    asked = getattr(args, "period", None) or f"{getattr(args, 'start', None) or ''}..{getattr(args, 'end', None) or ''}"
    if kind == "span":
        return (f"Yahoo serves at most {days} days of this interval per request and {asked} is longer: retry with --period {days}d "
                f"or a --start/--end span of at most {days} days, or a coarser --interval.")
    return (f"Yahoo serves this interval only for the last {days} days and {asked} reaches further back: retry with --period {days}d "
            f"or a --start inside the last {days} days, or a coarser --interval.")


NO_DATA_FIX = ("Yahoo returned no data for this request. Check the dates or --interval against when the instrument traded, "
               "or confirm the symbol with `search`, which reports its exchange and type.")


def refusal(exc, args=None):
    """The skill's failure for an exception from yfinance or Yahoo, keeping the source's own message."""
    if isinstance(exc, Failure):
        return exc
    text = str(exc)
    if is_rate_limited(exc):
        return Failure(text or "Too Many Requests", "Wait and retry with fewer targets; the remaining targets were not attempted.", code="rate_limited")
    status, description = source_error(exc)
    if status == 404 and description and DENIED in description:
        return Failure(f"Yahoo has no symbol {description.split(':')[-1].strip()}: {description}",
                       "Find the right symbol with `search` (an ADR, a share class or an exchange suffix such as .KS or .T may differ).", code="not_found")
    for pattern, kind in CONSTRAINTS:
        found = pattern.search(text) or (description and pattern.search(description))
        if found:
            return Failure(text, constraint_fix(kind, int(found.group(1)), args), code="source_constraint")
    if type(exc).__name__ in ("YFPricesMissingError", "YFTzMissingError", "YFTickerMissingError") or status == 404 \
            or "Data doesn't exist" in text or "No data found" in text or "possibly delisted" in text:
        return Failure(text or description or "no data", NO_DATA_FIX, code="no_data")
    return Failure(text or type(exc).__name__, "Retry later; if it fails again, confirm the symbol with `search` and the arguments with `COMMAND --help`.", code="upstream")


def not_applicable(quote_type, serves, what):
    """A confirmed quoteType outside what this dataset serves; an unconfirmed one is no_data, never a guess."""
    if quote_type and quote_type not in serves:
        return Failure(f"{what} exist only for {' or '.join(serves)}; this symbol's quoteType is {quote_type}.",
                       "Ask this for a fund or ETF symbol, or use the command that reads this instrument type.", code="not_applicable")
    return Failure(f"Yahoo returned no {what} for this symbol.", NO_DATA_FIX, code="no_data")
