"""Quotes, and bars and corporate actions with explicit adjustment and date semantics."""
import pandas as pd

from envelope import within_dates
from registry import PERCENT, RATE, SYMBOLS, Arg, dates, group, leaf

group("prices", "Quotes, historical bars and corporate actions")

QUOTE_FIELDS = ("symbol", "shortName", "quoteType", "currency", "financialCurrency", "marketState", "exchange", "fullExchangeName", "exchangeTimezoneName",
                "regularMarketPrice", "regularMarketChange", "regularMarketChangePercent", "regularMarketTime", "regularMarketOpen", "regularMarketDayHigh",
                "regularMarketDayLow", "regularMarketPreviousClose", "regularMarketVolume", "bid", "ask", "bidSize", "askSize",
                "postMarketPrice", "postMarketChangePercent", "postMarketTime", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyTwoWeekChangePercent",
                "fiftyDayAverage", "twoHundredDayAverage", "averageDailyVolume10Day", "averageDailyVolume3Month", "marketCap", "sharesOutstanding",
                "trailingPE", "forwardPE", "epsTrailingTwelveMonths", "dividendYield", "dividendRate", "exDividendDate", "beta")

# 성진: 여기 있는 것은 전부 값만 보고는 판정할 수 없는 스케일이다. marketCap이 통화라는 것처럼 이름이 이미 말하는
# 사실은 싣지 않는다 — 그런 항목이 표를 키우면 정작 판정 불가능한 항목이 그 안에 묻힌다.
# 첫 세 줄이 같은 리프 안의 100배 충돌이다(실측 AAPL: dividendYield 0.32 = 0.32%인데
# trailingAnnualDividendYield 0.0031 = 0.31%, fiftyTwoWeekChangePercent 31.26 옆에 52WeekChange 0.3126).
INFO_UNITS = {"dividendYield": PERCENT, "fiveYearAvgDividendYield": PERCENT, "trailingAnnualDividendYield": RATE,
              "fiftyTwoWeekChangePercent": PERCENT, "52WeekChange": RATE, "SandP52WeekChange": RATE,
              "regularMarketChangePercent": PERCENT, "postMarketChangePercent": PERCENT, "debtToEquity": PERCENT,
              "payoutRatio": RATE, "heldPercentInsiders": RATE, "heldPercentInstitutions": RATE,
              "profitMargins": RATE, "grossMargins": RATE, "operatingMargins": RATE, "ebitdaMargins": RATE,
              "revenueGrowth": RATE, "earningsGrowth": RATE, "earningsQuarterlyGrowth": RATE,
              "returnOnAssets": RATE, "returnOnEquity": RATE,
              "shortPercentOfFloat": RATE, "sharesPercentSharesOut": RATE}

CURRENCY_SPLIT = "currency prices this instrument's quote; financialCurrency is what its financial statements are reported in. They differ for foreign listings and ADRs (measured: TM quotes in USD and reports in JPY), so a ratio mixing a price with a statement figure is wrong by the exchange rate."
QUOTE_TIME = "regularMarketTime is when the market last priced this instrument; observed_at is when this CLI received the response. After the close they differ by hours."

# 성진: quote가 싣는 시각 필드. 원천이 말하는 시각과 CLI 관측시각은 장 마감 후 몇 시간 벌어진다.
SOURCE_TIME_FIELDS = ("regularMarketTime", "postMarketTime")

FROM = Arg("--from", dest="from_id", help="Read this saved observation instead of making a new request. prices quote and company profile select different sides of the same assembled response, so the second one costs nothing.")


def info_time(info):
    if not isinstance(info, dict):
        return None
    for field in SOURCE_TIME_FIELDS:
        value = info.get(field)
        if value:
            return value
    return None


def info(ticker, args, context, warnings):
    """quote and profile are two sides of one assembled response, so they share this fetch and --from."""
    data = ticker.get_info()
    context.update(currency=data.get("currency"), financial_currency=data.get("financialCurrency"))
    return data


leaf("prices", "quote", "Current price, trading session and market-capitalisation fields for one instrument.",
     args=[SYMBOLS, FROM], ticker=True, shares_info=True, source_time=info_time, exportable=False,
     fields=QUOTE_FIELDS, narrow=["--fields"], units=INFO_UNITS,
     interpretation={"sibling": "company profile selects the business side of this same assembled response; --from reuses the observation rather than requesting it again.",
                     "timing": QUOTE_TIME, "currency": CURRENCY_SPLIT,
                     "assembly": "yfinance assembles this response from several endpoints, so its fields do not all share one timestamp; where a field has its own time field, that one governs."},
     gotchas=["An instrument that did not trade in the current session still returns regularMarket fields from the last session it did."])(info)


BAR_NAMES = {"1d": "daily", "5d": "five-day", "1wk": "weekly", "1mo": "monthly", "3mo": "quarterly"}
COARSER = {"1d": "1wk", "5d": "1wk", "1wk": "1mo", "1mo": "3mo"}


def coarser_bars(args):
    """The next interval up, for a window too long to read row by row; intraday bars step up to daily."""
    step = COARSER.get(args.interval) or (None if args.interval == "3mo" else "1d")
    if step is None:
        return None
    was = BAR_NAMES.get(args.interval, args.interval)
    return f"--interval {step}", f"{BAR_NAMES[step]} bars, not a slice of these {was} ones"


def period_unless_dates(args):
    if args.period is None and not (args.start or args.end):
        args.period = "1mo"


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

BAR_ARGS = [SYMBOLS, *dates("ISO date YYYY-MM-DD; inclusive.", "ISO date YYYY-MM-DD; exclusive, so the last bar returned is the day before."),
            Arg("--period", help="Relative range such as 5d, 1mo, 1y, ytd or max; default 1mo only when start/end are absent."),
            Arg("--interval", choices=["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"], default="1d", help="Bar size. Intraday intervals carry range limits the source enforces; schema prices history reports the measured values."),
            Arg("--adjust", choices=["none", "auto", "back"], default="auto", help="none: unadjusted OHLC as supplied plus Adj Close; auto: Open/High/Low/Close scaled for splits and dividends, Adj Close removed; back: Close kept raw while Open/High/Low are scaled by the adjustment ratio, Adj Close removed."),
            Arg("--repair", action="store_true", help="Opt into yfinance price repair; OFF by default."),
            Arg("--prepost", action="store_true", help="Include pre/post-market data where available.")]


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
        if "429" in str(exc) or "RateLimit" in type(exc).__name__:
            context["rate_limited"] = True
    if context["currency"] is None:
        warnings.append("Source currency is unconfirmed.")
    return frame


@leaf("prices", "history", "OHLCV bars, dividends and splits over a date range or relative period.",
      args=BAR_ARGS, ticker=True, end_exclusive=True, defaults=period_unless_dates, conditions=dates_applied, precise=PRICE_COLUMNS, coarser=coarser_bars,
      recent=True, narrow=["--fields", "--limit", "--period", "--start/--end", "--interval"],
      interpretation={"dates": "start is inclusive and end is exclusive. A naive date is read in the exchange's timezone.",
                      "adjustment": "--adjust decides what Close means; adding dividends to an already adjusted return counts them twice.",
                      "repair": "--repair is a transformation with its own limits, not proof that a value equals the original trade."},
      limits={"1m": "8 days per request", "2m/5m/15m/30m/90m": "the range must fall within the last 60 days",
              "60m/1h": "no range limit measured; a year of 1h bars is far above the default budget",
              "note": "These come from Yahoo's own refusals; a request past them fails upstream rather than returning less."},
      gotchas=["A 30m request is resampled from 15m, and Yahoo's refusal message for it names 15m rather than the interval that was asked for."])
def history(ticker, args, context, warnings):
    return bars(ticker, args, context, warnings)


@leaf("prices", "actions", "Dividends, splits and capital gains within a date range or relative period.",
      args=BAR_ARGS, ticker=True, end_exclusive=True, defaults=period_unless_dates, conditions=dates_applied, precise=PRICE_COLUMNS,
      recent=True, narrow=["--limit", "--period", "--start/--end"],
      interpretation={"dates": "start is inclusive and end is exclusive; rows appear only on dates carrying an action.",
                      "empty": "The default period is one month, in which most instruments have no action at all. An empty return here is normal and is not evidence that the instrument pays nothing."})
def actions(ticker, args, context, warnings):
    frame = bars(ticker, args, context, warnings)
    if not frame.empty:
        columns = [c for c in ("Dividends", "Stock Splits", "Capital Gains") if c in frame.columns]
        frame = frame.loc[(frame[columns].fillna(0) != 0).any(axis=1), columns]
    return frame
