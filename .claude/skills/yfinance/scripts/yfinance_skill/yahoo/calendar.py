"""Earnings, economic, IPO and split events by date."""
from datetime import date, timedelta

import yfinance as yf

from yfinance_skill.envelope import InputError, condition, within_dates
from yfinance_skill.registry import CURRENCY, PER_SHARE, PERCENT, Arg, dates, effective_limit, group, leaf, get

group("calendar", "Earnings, economic, IPO and split events by date")

CALENDARS = {"earnings": "get_earnings_calendar", "economic": "get_economic_events_calendar", "ipo": "get_ipo_info_calendar", "splits": "get_splits_calendar"}
DATE_FIELDS = {"earnings": "Event Start Date", "economic": "Event Time", "ipo": "Date", "splits": "Payable On"}
CALENDAR_DATES = "--start and --end are both inclusive. Yahoo's own range excludes the end date, so this CLI sends the day after --end; the conditions field reports whether the rows it returned actually fall inside the range you asked for."

RANGE = [*dates("ISO date YYYY-MM-DD; inclusive. Defaults to today for market-wide calendars.", "ISO date YYYY-MM-DD; inclusive, so --start D --end D returns that day. Defaults to seven days after --start."),
         Arg("--offset", type=int, default=0, help="Remote row offset; next_offset advances by displayed rows, not native batch size.")]


def week_from_today(args):
    if not getattr(args, "symbol", None):
        args.start = args.start or date.today().isoformat()
        args.end = args.end or (date.fromisoformat(args.start) + timedelta(days=7)).isoformat()


def check(args):
    if args.limit and args.limit > 100:
        raise InputError("Calendar --limit cannot exceed Yahoo's 100-row cap")
    if getattr(args, "symbol", None):
        if args.start or args.end or args.most_active:
            raise InputError("Single-symbol earnings supports --limit/--offset, not date or most-active filters; omit SYMBOL for market dates")
    if getattr(args, "most_active", False) and args.offset:
        raise InputError("Native most-active filter is unavailable with --offset; remove --most-active")


def dates_applied(encoded, args, context):
    if getattr(args, "symbol", None):
        return {}
    if args.leaf == "ipo":
        return {"dates": condition({"start": args.start, "end": args.end}, "unverified",
                                   {"reason": "a row matches on any of three date fields, so a returned row's Date can lie outside the requested range"})}
    found = within_dates(encoded, DATE_FIELDS[args.leaf], args.start, args.end)
    return {"dates": found} if found else {}


def market_wide(args, context, warnings):
    """--start and --end are inclusive here.

    Yahoo's own range excludes the end date, so a caller asking for one day received nothing while the CLI declared
    the boundary inclusive and the validator explicitly allowed start == end. Sending the following day makes the
    declaration true; the conditions field then checks it against the rows that came back.
    """
    native_end = (date.fromisoformat(args.end) + timedelta(days=1)).isoformat()
    native = yf.Calendars(start=args.start, end=native_end)
    asked = effective_limit(args, get("calendar", args.leaf)) or 10
    context["upstream_requested"] = asked
    kwargs = {"limit": asked, "offset": args.offset}
    if args.leaf == "earnings":
        kwargs["filter_most_active"] = args.most_active
    data = getattr(native, CALENDARS[args.leaf])(**kwargs)
    context.update(scope="US" if args.leaf == "earnings" else "native calendar universe; each row names its own region or exchange")
    if args.leaf != "splits":
        warnings.append("yfinance converts zero to null in the numeric estimate, actual, surprise and price columns; the zero/missing distinction is already lost upstream of this CLI.")
    displayed = min(len(data), asked)
    if displayed and len(data) >= asked:
        context["next_offset"] = args.offset + displayed
    return data


def one_company(args, context):
    asked = effective_limit(args, get("calendar", "earnings")) or 10
    batch = 25 if asked <= 25 else 50 if asked <= 50 else 100
    context.update(native_batch_size=batch, scope="single_symbol")
    context["upstream_requested"] = asked
    data = yf.Ticker(args.symbol).get_earnings_dates(limit=asked, offset=args.offset)
    if data is not None and data.index.hasnans:
        raise ValueError("Upstream earnings date/value alignment is unreliable after missing dates were parsed; use market earnings with a bounded date window instead.")
    displayed = min(0 if data is None else len(data), asked)
    if displayed:
        context["next_offset"] = args.offset + displayed
    return data


ZERO_LOSS = "yfinance converts zero to null in the numeric columns, so a null actual or expected can be a real zero."
COMMON = dict(limit=12, narrow=["--fields", "--limit", "--start/--end", "--offset"], conditions=dates_applied, defaults=week_from_today, check=check)


@leaf("calendar", "earnings", "Earnings events, market-wide over a date range or one company's history.",
      args=[*RANGE, Arg("symbol", nargs="?", help="Optional single symbol; omit for market-wide US earnings."),
            Arg("--most-active", action="store_true", help="Opt into native most-active filter; only market earnings at offset 0.")],
      forbidden=lambda args: ["--start/--end"] if getattr(args, "symbol", None) else [],
      units={"Surprise(%)": PERCENT, "Marketcap": CURRENCY, "EPS Estimate": PER_SHARE, "Reported EPS": PER_SHARE},
      interpretation={"dates": CALENDAR_DATES,
                      "two_modes": "With a SYMBOL this returns that company's own earnings history and upcoming dates, paged by --limit and --offset with no date filter, newest first. Without one it returns market-wide US earnings inside the date range.",
                      "surprise": "Surprise(%) is on a percent scale: 33.33 means 33.33%. analysts history reports the same measurement as surprisePercent on a ratio scale, so the two are 100x apart.",
                      "zero_loss": "yfinance converts zero to null in the estimate, actual and surprise columns, so a null there can be a real zero and the distinction is already lost upstream of this CLI."},
      **COMMON)
def earnings(target, args, context, warnings):
    return one_company(args, context) if args.symbol else market_wide(args, context, warnings)


@leaf("calendar", "economic", "Scheduled economic releases over a date range.",
      args=RANGE,
      interpretation={"dates": CALENDAR_DATES,
                      "scope": "The universe is not US-only; the Region column says which economy each row belongs to.",
                      "zero_loss": ZERO_LOSS},
      **COMMON)
def economic(target, args, context, warnings):
    return market_wide(args, context, warnings)


@leaf("calendar", "ipo", "IPO listings, filings and amendments over a date range.",
      args=RANGE,
      interpretation={"dates": "A row matches when any of its listing Date, Filing Date or Amended Date falls in the range, so a returned row's Date can sit outside it.",
                      "zero_loss": "yfinance converts zero to null in the price and share columns."},
      gotchas=["Because three different date fields can match, the range cannot be confirmed from the returned rows the way the other calendars' can; conditions reports it as unverified rather than claiming it was applied."],
      **COMMON)
def ipo(target, args, context, warnings):
    return market_wide(args, context, warnings)


@leaf("calendar", "splits", "Split events payable over a date range.",
      args=RANGE,
      interpretation={"dates": CALENDAR_DATES + " The date matched is the payable date, not the announcement or ex-date."},
      **COMMON)
def splits(target, args, context, warnings):
    return market_wide(args, context, warnings)
