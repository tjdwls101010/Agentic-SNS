"""Prices and corporate actions with explicit adjustment and date semantics."""

import pandas as pd

import output


def fetch(ticker, args, context, warnings):
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
    if args.leaf == "actions" and not frame.empty:
        columns = [c for c in ("Dividends", "Stock Splits", "Capital Gains") if c in frame.columns]
        frame = frame.loc[(frame[columns].fillna(0) != 0).any(axis=1), columns]
    return frame


def dates_applied(encoded, args):
    """Judge --start/--end from the rows themselves rather than from the arguments that were sent."""
    if not (args.start or args.end):
        return {}
    end = args.end
    if end and args.leaf in ("history", "actions"):
        end = (pd.Timestamp(end) - pd.Timedelta(days=1)).date().isoformat()  # end is exclusive here, so the last row it can contain is the day before
    found = output.within_dates(encoded, "index", args.start, end)
    return {"dates": found} if found else {}
