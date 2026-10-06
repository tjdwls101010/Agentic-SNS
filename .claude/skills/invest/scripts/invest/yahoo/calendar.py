"""Earnings, economic, IPO and split events by date, and one company's earnings dates."""
from datetime import date, timedelta

import yfinance as yf

from invest.receipts import Failure
from invest.yahoo.conditions import condition, within_dates
from invest.yahoo.datasets import Dataset
from invest.yahoo.encode import encode
from invest.yahoo.units import (COUNT, DATETIME, MONEY_UNCONFIRMED, PER_SHARE_UNCONFIRMED, PERCENT, RATIO, SHARES, TEXT, UNVERIFIED, u)

CALENDARS = {"earnings": "get_earnings_calendar", "economic": "get_economic_events_calendar", "ipo": "get_ipo_info_calendar", "splits": "get_splits_calendar"}
DATE_FIELDS = {"earnings": "Event Start Date", "economic": "Event Time", "ipo": "Date", "splits": "Payable On"}
PAGING = "A page is read at the moment it is asked for; rows can move between pages, and total is Yahoo's own claim."


def dates_applied(frame, args, kind):
    if kind == "ipo":
        return {"dates": condition({"start": args.start, "end": args.end}, "unverified",
                                   {"reason": "a row matches on any of its Date, Filing Date or Amended Date, so its Date can lie outside the range"})}
    field = DATE_FIELDS[kind]
    values = [encode(v) for v in frame[field]] if frame is not None and field in getattr(frame, "columns", []) else []
    found = within_dates(values, field, args.start, args.end)
    return {"dates": found} if found else {}


def market_wide(kind):
    """--start and --end are inclusive: Yahoo's own range excludes its end, so the day after --end is sent."""
    def fetch(target, args, context):
        native = yf.Calendars(start=args.start, end=(date.fromisoformat(args.end) + timedelta(days=1)).isoformat())
        options = {"limit": args.limit, "offset": args.offset}
        if kind == "earnings":
            options["filter_most_active"] = args.most_active
        frame = getattr(native, CALENDARS[kind])(**options)
        received = 0 if frame is None else len(frame)
        context.coverage.update(requested=args.limit, offset=args.offset)
        if received >= args.limit:
            context.coverage["next_offset"] = args.offset + received
            context.warn("pages_move", PAGING)
        if kind != "splits" and received:
            context.warn("zero_as_null", "yfinance turns zero into null in this calendar's numeric columns, so a null can be a real zero.")
        context.conditions.update(dates_applied(frame, args, kind))
        if frame is not None and not frame.empty and frame.index.name is None:
            frame = frame.reset_index(drop=True)
        return frame
    return fetch


def company_earnings(ticker, args, context):
    frame = ticker.get_earnings_dates(limit=args.limit, offset=args.offset)
    if frame is not None and frame.index.hasnans:
        raise Failure("Yahoo returned an earnings row without a date, after which yfinance cannot keep dates and values aligned.",
                      "Use market-wide calendar earnings with a bounded --start/--end instead.", code="upstream")
    received = 0 if frame is None else len(frame)
    context.coverage.update(requested=args.limit, offset=args.offset)
    if received >= args.limit:
        context.coverage["next_offset"] = args.offset + received
    return frame


class Calendar(Dataset):
    """calendar earnings reads one company's dates when a SYMBOL is given, and the market-wide calendar otherwise."""

    def __init__(self, kind, **spec):
        super().__init__(market_wide(kind), ticker=False, counted=True, **spec)
        self.kind = kind

    def reader(self, args, target):
        if self.kind == "earnings" and getattr(args, "symbol", None):
            return company_earnings, yf.Ticker(args.symbol)
        return self.fetch, target


EARNINGS_UNITS = {"Event Start Date": u(DATETIME), "Earnings Date": u(DATETIME), "Symbol": u(TEXT), "Company": u(TEXT),
                  "Marketcap": u(MONEY_UNCONFIRMED), "EPS Estimate": u(PER_SHARE_UNCONFIRMED), "Reported EPS": u(PER_SHARE_UNCONFIRMED),
                  "Surprise(%)": u(RATIO, PERCENT, evidence="Surprise(%) = surprisePercent x 100 for the same quarter (AAPL)")}
OWN_CURRENCY = "Amounts are in each company's own currency, which the calendar does not state."
DATASETS = {
    "calendar.earnings": Calendar(
        "earnings", units=EARNINGS_UNITS, coverage="Yahoo's US earnings calendar for the range, or one company's earnings dates newest first",
        notes=(OWN_CURRENCY, "With a SYMBOL the rows are that company's own past and upcoming dates; without one, market-wide US earnings in the range."),
        possible=("zero_as_null", "pages_move")),
    "calendar.economic": Calendar(
        "economic", units={"Event Time": u(DATETIME), "Actual": u(UNVERIFIED), "Expected": u(UNVERIFIED), "Last": u(UNVERIFIED), "Revised": u(UNVERIFIED)},
        coverage="Yahoo's economic release calendar for the range, every region",
        notes=("The calendar is not US-only; the Region column names each row's economy.",
               "Actual, Expected, Last and Revised carry each release's own unit, which the calendar does not state."),
        possible=("zero_as_null", "pages_move")),
    "calendar.ipo": Calendar(
        "ipo", units={"Date": u(DATETIME), "Filing Date": u(DATETIME), "Amended Date": u(DATETIME), "Price From": u(MONEY_UNCONFIRMED),
                      "Price To": u(MONEY_UNCONFIRMED), "Price": u(MONEY_UNCONFIRMED), "Shares": u(SHARES)},
        coverage="Yahoo's IPO calendar: rows whose listing, filing or amendment date falls in the range",
        notes=(OWN_CURRENCY,), possible=("zero_as_null", "pages_move")),
    "calendar.splits": Calendar(
        "splits", units={"Payable On": u(DATETIME), "Old Share Worth": u(COUNT), "Share Worth": u(COUNT)},
        coverage="Yahoo's split calendar for the range, matched on the payable date",
        notes=("Old Share Worth becomes Share Worth: 1 and 4 is a four-for-one split.",), possible=("pages_move",)),
}
