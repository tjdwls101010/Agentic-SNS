"""Earnings, economic, IPO and split events by date."""
from datetime import date, timedelta

import yfinance as yf

from yfinance_skill.envelope import condition, within_dates
from yfinance_skill.yahoo.datasets import CURRENCY, PER_SHARE, PERCENT, Dataset, asked

CALENDARS = {"earnings": "get_earnings_calendar", "economic": "get_economic_events_calendar", "ipo": "get_ipo_info_calendar", "splits": "get_splits_calendar"}
DATE_FIELDS = {"earnings": "Event Start Date", "economic": "Event Time", "ipo": "Date", "splits": "Payable On"}
CALENDAR_DATES = "--start and --end are both inclusive. Yahoo's own range excludes the end date, so this CLI sends the day after --end; the conditions field reports whether the rows it returned actually fall inside the range you asked for."


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
    requested = asked(args, DATASETS["calendar." + args.leaf]) or 10
    context["upstream_requested"] = requested
    kwargs = {"limit": requested, "offset": args.offset}
    if args.leaf == "earnings":
        kwargs["filter_most_active"] = args.most_active
    data = getattr(native, CALENDARS[args.leaf])(**kwargs)
    context.update(scope="US" if args.leaf == "earnings" else "native calendar universe; each row names its own region or exchange")
    if args.leaf != "splits":
        warnings.append("yfinance converts zero to null in the numeric estimate, actual, surprise and price columns; the zero/missing distinction is already lost upstream of this CLI.")
    displayed = min(len(data), requested)
    if displayed and len(data) >= requested:
        context["next_offset"] = args.offset + displayed
    return data


def one_company(args, context):
    requested = asked(args, DATASETS["calendar.earnings"]) or 10
    batch = 25 if requested <= 25 else 50 if requested <= 50 else 100
    context.update(native_batch_size=batch, scope="single_symbol")
    context["upstream_requested"] = requested
    data = yf.Ticker(args.symbol).get_earnings_dates(limit=requested, offset=args.offset)
    if data is not None and data.index.hasnans:
        raise ValueError("Upstream earnings date/value alignment is unreliable after missing dates were parsed; use market earnings with a bounded date window instead.")
    displayed = min(0 if data is None else len(data), requested)
    if displayed:
        context["next_offset"] = args.offset + displayed
    return data


def earnings(target, args, context, warnings):
    return one_company(args, context) if args.symbol else market_wide(args, context, warnings)


def events(target, args, context, warnings):
    return market_wide(args, context, warnings)


ZERO_LOSS = "yfinance converts zero to null in the numeric columns, so a null actual or expected can be a real zero."


def calendar(fetch, **spec):
    return Dataset(fetch, rows=12, conditions=dates_applied, **spec)


DATASETS = {
    "calendar.earnings": calendar(
        earnings,
        units={"Surprise(%)": PERCENT, "Marketcap": CURRENCY, "EPS Estimate": PER_SHARE, "Reported EPS": PER_SHARE},
        interpretation={"dates": CALENDAR_DATES,
                        "two_modes": "With a SYMBOL this returns that company's own earnings history and upcoming dates, paged by --limit and --offset with no date filter, newest first. Without one it returns market-wide US earnings inside the date range.",
                        "surprise": "Surprise(%) is on a percent scale: 33.33 means 33.33%. analysts history reports the same measurement as surprisePercent on a ratio scale, so the two are 100x apart.",
                        "zero_loss": "yfinance converts zero to null in the estimate, actual and surprise columns, so a null there can be a real zero and the distinction is already lost upstream of this CLI."}),
    "calendar.economic": calendar(
        events,
        interpretation={"dates": CALENDAR_DATES,
                        "scope": "The universe is not US-only; the Region column says which economy each row belongs to.",
                        "zero_loss": ZERO_LOSS}),
    "calendar.ipo": calendar(
        events,
        interpretation={"dates": "A row matches when any of its listing Date, Filing Date or Amended Date falls in the range, so a returned row's Date can sit outside it.",
                        "zero_loss": "yfinance converts zero to null in the price and share columns."},
        gotchas=["Because three different date fields can match, the range cannot be confirmed from the returned rows the way the other calendars' can; conditions reports it as unverified rather than claiming it was applied."]),
    "calendar.splits": calendar(
        events,
        interpretation={"dates": CALENDAR_DATES + " The date matched is the payable date, not the announcement or ex-date."}),
}
