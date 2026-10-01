"""Earnings, economic, IPO and split events by date."""
from datetime import date, timedelta

import yfinance as yf

from yfinance_skill.envelope import condition, within_dates
from yfinance_skill.yahoo.datasets import CURRENCY, PER_SHARE, PERCENT, Dataset

CALENDARS = {"earnings": "get_earnings_calendar", "economic": "get_economic_events_calendar", "ipo": "get_ipo_info_calendar", "splits": "get_splits_calendar"}
DATE_FIELDS = {"earnings": "Event Start Date", "economic": "Event Time", "ipo": "Date", "splits": "Payable On"}
CALENDAR_DATES = "conditions.dates reports whether the rows returned fall inside the range asked for."


def dates_applied(encoded, args, context):
    if getattr(args, "symbol", None):
        return {}
    if args.leaf == "ipo":
        return {"dates": condition({"start": args.start, "end": args.end}, "unverified",
                                   {"reason": "a row matches on any of three date fields, so a returned row's Date can lie outside the requested range"})}
    found = within_dates(encoded, DATE_FIELDS[args.leaf], args.start, args.end)
    return {"dates": found} if found else {}


def market_wide(args, context, warnings, rows):
    """--start and --end are inclusive here.

    Yahoo's own range excludes the end date, so a caller asking for one day received nothing while the CLI declared
    the boundary inclusive and the validator explicitly allowed start == end. Sending the following day makes the
    declaration true; the conditions field then checks it against the rows that came back.
    """
    native_end = (date.fromisoformat(args.end) + timedelta(days=1)).isoformat()
    native = yf.Calendars(start=args.start, end=native_end)
    requested = rows
    context["requested"] = requested
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


def one_company(args, context, rows):
    requested = rows
    batch = 25 if requested <= 25 else 50 if requested <= 50 else 100
    context.update(native_batch_size=batch, scope="single_symbol")
    context["requested"] = requested
    data = yf.Ticker(args.symbol).get_earnings_dates(limit=requested, offset=args.offset)
    if data is not None and data.index.hasnans:
        raise ValueError("Upstream earnings date/value alignment is unreliable after missing dates were parsed; use market earnings with a bounded date window instead.")
    displayed = min(0 if data is None else len(data), requested)
    if displayed:
        context["next_offset"] = args.offset + displayed
    return data


def earnings(target, args, context, warnings, rows):
    return one_company(args, context, rows) if args.symbol else market_wide(args, context, warnings, rows)


def events(target, args, context, warnings, rows):
    return market_wide(args, context, warnings, rows)


ZERO_LOSS = "yfinance converts zero to null in the numeric columns, so a null actual or expected can be a real zero."


def calendar(fetch, **spec):
    return Dataset(fetch, counted=True, conditions=dates_applied, **spec)


DATASETS = {
    "calendar.earnings": calendar(
        earnings,
        units={"Surprise(%)": PERCENT, "Marketcap": CURRENCY, "EPS Estimate": PER_SHARE, "Reported EPS": PER_SHARE},
        interpretation={"dates": CALENDAR_DATES,
                        "two_modes": "With a SYMBOL this returns that company's own earnings history and upcoming dates, paged by --limit and --offset with no date filter, newest first. Without one it returns market-wide US earnings inside the date range.",
                        "surprise": "Surprise(%) is in percent (33.33 is 33.33%); analysts history reports the same measurement as surprisePercent, a ratio, 100x apart.",
                        "zero_loss": "Market-wide, yfinance turns zero into null in the estimate, actual and surprise columns, so a null can be a real zero; a single symbol's history keeps its zeros."}),
    "calendar.economic": calendar(
        events,
        interpretation={"dates": CALENDAR_DATES,
                        "scope": "The universe is not US-only; the Region column says which economy each row belongs to.",
                        "zero_loss": ZERO_LOSS}),
    "calendar.ipo": calendar(
        events,
        interpretation={"dates": "A row matches when any of its listing Date, Filing Date or Amended Date falls in the range, so a returned row's Date can sit outside it and conditions reports the range as unverified.",
                        "zero_loss": "yfinance converts zero to null in the price and share columns."}),
    "calendar.splits": calendar(
        events,
        interpretation={"dates": CALENDAR_DATES + " The date matched is the payable date, not the announcement or ex-date."}),
}
