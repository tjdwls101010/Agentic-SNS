"""Prices and corporate actions with explicit adjustment and date semantics."""

import pandas as pd


def fetch(ticker, args, context, warnings):
    frame = ticker.history(period=args.period, start=args.start, end=args.end, interval=args.interval, auto_adjust=args.adjust == "auto", back_adjust=args.adjust == "back", repair=args.repair, actions=True, keepna=True, prepost=args.prepost, timeout=args.timeout)
    if not frame.empty:
        timezone = getattr(frame.index, "tz", None)
        if args.start:
            frame = frame.loc[frame.index >= pd.Timestamp(args.start, tz=timezone)]
        if args.end:
            frame = frame.loc[frame.index < pd.Timestamp(args.end, tz=timezone)]
    context.update(start_boundary="inclusive", end_boundary="exclusive", naive_date_timezone="exchange", adjustment=args.adjust, repair=args.repair, currency=None, timezone=str(frame.index.tz) if hasattr(frame.index, "tz") else None)
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
