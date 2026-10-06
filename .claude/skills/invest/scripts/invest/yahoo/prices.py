"""The quote, and price bars with their adjustment, dates and whether the last bar is final."""
from zoneinfo import ZoneInfo

import pandas as pd

from invest.yahoo import timing
from invest.yahoo.conditions import within_dates
from invest.yahoo.datasets import Dataset
from invest.yahoo.encode import encode
from invest.yahoo.info import ASSEMBLED, INFO_UNITS, QUOTE_FIELDS, SIBLING, info
from invest.yahoo.refusals import is_rate_limited
from invest.yahoo.units import DATETIME, MULTIPLE, PER_SHARE_QUOTE, SHARES, TEXT, u

PRICE = u(PER_SHARE_QUOTE)
BAR_UNITS = {"Open": PRICE, "High": PRICE, "Low": PRICE, "Close": PRICE, "Adj Close": PRICE, "Volume": u(SHARES),
             "Dividends": PRICE, "Stock Splits": u(MULTIPLE), "Capital Gains": PRICE, "Repaired?": u(TEXT), "Date": u(DATETIME), "Datetime": u(DATETIME)}
# 성진: 원천 정밀도가 실측된 열만 인라인에서 7자리로 보인다(Yahoo는 가격을 float32로 준다). 파일은 언제나 받은 자릿수 전부다.
PRICE_COLUMNS = ("Open", "High", "Low", "Close", "Adj Close")
ACTIONS = ("Dividends", "Stock Splits", "Capital Gains")
ADJUSTMENT = {
    "auto": "Prices are adjusted for splits and dividends (--adjust auto), so a return from Close already includes dividends.",
    "back": "Close is as traded while Open, High and Low are scaled by the adjustment ratio (--adjust back).",
    "none": "Prices are as traded, adjusted only for splits as Yahoo serves them; Adj Close adds the dividend adjustment (--adjust none).",
}


def session(metadata):
    """The (start, end) of the regular session Yahoo reports as current, and the exchange's time zone; None for what it did not report."""
    period = (metadata or {}).get("currentTradingPeriod") or {}
    regular = period.get("regular") if isinstance(period, dict) else None
    name = (metadata or {}).get("exchangeTimezoneName")
    zone = None
    if name:
        try:
            zone = ZoneInfo(name)
        except (KeyError, ValueError):
            zone = None
    if isinstance(regular, dict) and regular.get("start") is not None and regular.get("end") is not None:
        return (regular["start"], regular["end"]), zone
    return None, zone


def bars(ticker, args, context):
    frame = ticker.history(period=args.period, start=args.start, end=args.end, interval=args.interval, auto_adjust=args.adjust == "auto",
                           back_adjust=args.adjust == "back", repair=args.repair, actions=True, keepna=True, prepost=args.prepost, timeout=args.timeout)
    context.observed_at = timing.now()
    if not frame.empty:
        zone = getattr(frame.index, "tz", None)
        if args.start:
            frame = frame.loc[frame.index >= pd.Timestamp(args.start, tz=zone)]
        if args.end:
            frame = frame.loc[frame.index < pd.Timestamp(args.end, tz=zone)]
    metadata = {}
    try:
        metadata = ticker.get_history_metadata() or {}
    except Exception as exc:  # the bars are still the answer; what could not be read is when the session ends
        if is_rate_limited(exc):
            context.rate_limited = True
            context.warn("secondary_rate_limited", "Yahoo rate-limited the session lookup after the bars arrived; the bars are kept and the remaining targets were not attempted.")
        context.receipt["metadata_error"] = str(exc)
    context.currency = metadata.get("currency")
    zone_name = metadata.get("exchangeTimezoneName") or (str(frame.index.tz) if getattr(frame.index, "tz", None) else None)
    context.as_of["timezone"] = zone_name
    if not frame.empty:
        judge_last_bar(frame, args, metadata, context)
    context.conditions.update(dates_applied(frame, args))
    context.note(ADJUSTMENT[args.adjust])
    context.note("A bar's date is in the exchange's time zone (as_of.timezone).")
    if args.interval not in ("1d", "5d", "1wk", "1mo", "3mo") and args.period == "max":
        context.note("With an intraday --interval, --period max is the longest span Yahoo serves for that interval, not the whole history.")
    return frame


def judge_last_bar(frame, args, metadata, context):
    observed = context.observed_at
    span, zone = session(metadata)
    last = frame.index[-1]
    status, reason = timing.last_bar(last, args.interval, observed, span, zone)
    context.as_of.update(last_bar=encode(last), last_bar_status=status, reason=reason)
    if span:
        context.as_of["session"] = {"start": encode(timing.stamp(span[0])), "end": encode(timing.stamp(span[1]))}
    if metadata.get("regularMarketTime") is not None:
        context.as_of["regularMarketTime"] = encode(timing.stamp(metadata["regularMarketTime"]))
    if status == "provisional":
        context.warn("last_bar_provisional", f"The last bar ({encode(last)[:10]}) is still forming: {reason}. It is not a close.")
    elif status == "unknown":
        context.warn("last_bar_unknown", f"Whether the last bar is final is unknown: {reason}. Do not call it a close.")


def dates_applied(frame, args):
    """--start and --end judged from the rows themselves; --end is exclusive, so the last row it allows is the day before."""
    if not (args.start or args.end):
        return {}
    end = (pd.Timestamp(args.end) - pd.Timedelta(days=1)).date().isoformat() if args.end else None
    found = within_dates([encode(i) for i in frame.index], frame.index.name or "Date", args.start, end)
    return {"dates": found} if found else {}


def history(ticker, args, context):
    frame = bars(ticker, args, context)
    if args.actions and not frame.empty:
        columns = [c for c in ACTIONS if c in frame.columns]
        frame = frame.loc[(frame[columns].fillna(0) != 0).any(axis=1), columns]
        context.note("Only dates carrying a dividend, split or capital gain are rows (--actions); a window without one is empty, which does not mean the instrument pays nothing.")
    return frame


def quote(ticker, args, context):
    data = info(ticker, args, context)
    context.observed_at = timing.now()
    return data


DATASETS = {
    "quote": Dataset(
        quote, form="records", units=INFO_UNITS, fields=QUOTE_FIELDS,
        coverage="Yahoo's info response for the symbol: every field it carries is in result.json",
        notes=(ASSEMBLED, SIBLING, "An instrument that did not trade this session still carries regularMarket fields from the last session it did."),
        possible=("cross_currency_fields",)),
    "history": Dataset(
        history, units=BAR_UNITS, precise=PRICE_COLUMNS,
        coverage="the bars Yahoo serves for this range and interval",
        possible=("last_bar_provisional", "last_bar_unknown", "inverse_of_zero")),
}
