"""Quotes, and bars and corporate actions with explicit adjustment and date semantics."""
import pandas as pd

from yfinance_skill.envelope import within_dates
from yfinance_skill.yahoo.datasets import Dataset
from yfinance_skill.yahoo.info import CURRENCY_SPLIT, INFO_UNITS, QUOTE_TIME, info, info_time
from yfinance_skill.yahoo.refusals import is_rate_limited

QUOTE_FIELDS = ("symbol", "shortName", "quoteType", "currency", "financialCurrency", "marketState", "exchange", "fullExchangeName", "exchangeTimezoneName",
                "regularMarketPrice", "regularMarketChange", "regularMarketChangePercent", "regularMarketTime", "regularMarketOpen", "regularMarketDayHigh",
                "regularMarketDayLow", "regularMarketPreviousClose", "regularMarketVolume", "bid", "ask", "bidSize", "askSize",
                "postMarketPrice", "postMarketChangePercent", "postMarketTime", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyTwoWeekChangePercent",
                "fiftyDayAverage", "twoHundredDayAverage", "averageDailyVolume10Day", "averageDailyVolume3Month", "marketCap", "sharesOutstanding",
                "trailingPE", "forwardPE", "epsTrailingTwelveMonths", "dividendYield", "dividendRate", "exDividendDate", "beta")


def dates_applied(encoded, args, context):
    """Judge --start/--end from the rows themselves rather than from the arguments that were sent."""
    if not (args.start or args.end):
        return {}
    end = args.end
    if end:
        end = (pd.Timestamp(end) - pd.Timedelta(days=1)).date().isoformat()  # end is exclusive here, so the last row it can contain is the day before
    found = within_dates(encoded, "index", args.start, end)
    return {"dates": found} if found else {}


# 성진: 원천 정밀도가 실측된 열만 7자리로 표기한다 — 비조정 OHLC 6,270값 전부 float32 정확값(2026-09-24 AAPL 5y).
# 옵션 체인은 52%만 float32라 선언하지 않는다; 새 열을 여기 넣으려면 같은 측정이 먼저다.
PRICE_COLUMNS = ("Open", "High", "Low", "Close", "Adj Close")
PRECISION = "Prices print to 7 significant digits, the precision Yahoo serves; the saved observation and --out keep every digit."


def bars(ticker, args, context, warnings):
    frame = ticker.history(period=args.period, start=args.start, end=args.end, interval=args.interval, auto_adjust=args.adjust == "auto", back_adjust=args.adjust == "back", repair=args.repair, actions=True, keepna=True, prepost=args.prepost, timeout=args.timeout)
    if not frame.empty:
        timezone = getattr(frame.index, "tz", None)
        if args.start:
            frame = frame.loc[frame.index >= pd.Timestamp(args.start, tz=timezone)]
        if args.end:
            frame = frame.loc[frame.index < pd.Timestamp(args.end, tz=timezone)]
    context.update(adjustment=args.adjust, repair=args.repair, currency=None, timezone=str(frame.index.tz) if hasattr(frame.index, "tz") else None)
    try:
        metadata = ticker.get_history_metadata()
        context.update(currency=metadata.get("currency"), timezone=metadata.get("exchangeTimezoneName") or context["timezone"])
    except Exception as exc:
        warnings.append(f"History metadata unavailable; price data retained: {exc}")
        if is_rate_limited(exc):
            context["rate_limited"] = True
    if context["currency"] is None:
        warnings.append("Source currency is unconfirmed.")
    return frame


def history(ticker, args, context, warnings):
    return bars(ticker, args, context, warnings)


def actions(ticker, args, context, warnings):
    frame = bars(ticker, args, context, warnings)
    if not frame.empty:
        columns = [c for c in ("Dividends", "Stock Splits", "Capital Gains") if c in frame.columns]
        frame = frame.loc[(frame[columns].fillna(0) != 0).any(axis=1), columns]
    return frame


DATASETS = {
    "prices.quote": Dataset(
        info, ticker=True, shares_info=True, source_time=info_time, fields=QUOTE_FIELDS, units=INFO_UNITS,
        interpretation={"sibling": "company profile selects the business side of this same assembled response; --from reuses the observation rather than requesting it again.",
                        "timing": QUOTE_TIME, "currency": CURRENCY_SPLIT,
                        "assembly": "yfinance assembles this response from several endpoints, so its fields do not all share one timestamp; where a field has its own time field, that one governs."},
        gotchas=["An instrument that did not trade in the current session still returns regularMarket fields from the last session it did."]),
    "prices.history": Dataset(
        history, ticker=True, conditions=dates_applied, precise=PRICE_COLUMNS, recent=True,
        interpretation={"dates": "start is inclusive and end is exclusive. A naive date is read in the exchange's timezone.",
                        "adjustment": "--adjust decides what Close means; adding dividends to an already adjusted return counts them twice.",
                        "repair": "--repair is a transformation with its own limits, not proof that a value equals the original trade.",
                        "precision": PRECISION},
        limits={"1m": "8 days per request", "2m/5m/15m/30m/90m": "the range must fall within the last 60 days",
                "60m/1h": "no range limit known; a year of 1h bars is far above the default budget",
                "note": "A request past these fails upstream rather than returning less."},
        gotchas=["A 30m request is resampled from 15m, so Yahoo's refusal for it names 15m, not the interval asked for."]),
    "prices.actions": Dataset(
        actions, ticker=True, conditions=dates_applied, recent=True,
        interpretation={"dates": "start is inclusive and end is exclusive; rows appear only on dates carrying an action.",
                        "empty": "The default period is one month, in which most instruments have no action at all. An empty return here is normal and is not evidence that the instrument pays nothing."}),
}
