"""Expirations and option chains."""
from yfinance_skill.envelope import InputError, condition
from yfinance_skill.yahoo.datasets import COUNT, CURRENCY, PERCENT, RATE, Dataset


def expirations(ticker, args, context, warnings):
    return list(ticker.options)


def date_applied(encoded, args, context):
    if not args.date:
        return {}
    applied = context.get("expiration") == args.date
    return {"date": condition(args.date, "confirmed" if applied else "not_applied", {"expiration": context.get("expiration")})}


def chain(ticker, args, context, warnings):
    listed = list(ticker.options)
    if args.date and args.date not in listed:
        raise InputError(f"Expiration {args.date} is not listed for this underlying; list them with options expirations {ticker.ticker}")
    if not listed:
        return None
    expiry = args.date or listed[0]
    found = ticker.option_chain(date=expiry)
    underlying = found.underlying or {}
    context["expiration"] = expiry
    context["underlying"] = {key: underlying.get(key) for key in ("symbol", "regularMarketPrice", "regularMarketTime", "currency", "exchangeTimezoneName")}
    sides = ["calls", "puts"] if args.side == "both" else [args.side]
    return {side: getattr(found, side) for side in sides}


DATASETS = {
    "options.expirations": Dataset(
        expirations, ticker=True,
        interpretation={"use": "Pass one of these to options chain --date; an omitted --date selects the nearest."}),
    "options.chain": Dataset(
        chain, ticker=True, rows=20, conditions=date_applied,
        units={"strike": CURRENCY, "lastPrice": CURRENCY, "bid": CURRENCY, "ask": CURRENCY, "change": CURRENCY,
               "percentChange": PERCENT, "impliedVolatility": RATE, "volume": COUNT, "openInterest": COUNT},
        interpretation={"sides": "calls and puts are selected separately and each is limited on its own, so a limit of 20 with --side both returns 20 of each.",
                        "staleness": "lastTradeDate is when that contract last traded, which for a thin strike can be days before now while bid and ask are current. A contract's lastPrice is only as recent as its lastTradeDate.",
                        "timezone": "lastTradeDate is UTC."},
        gotchas=["Contracts are ordered by strike, so a limit keeps the lowest strikes rather than the ones nearest the money."]),
}
