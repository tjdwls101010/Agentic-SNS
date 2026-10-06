"""Expirations and option chains."""
from invest.receipts import Invalid
from invest.yahoo.conditions import condition
from invest.yahoo.datasets import COUNT, CURRENCY, PERCENT, RATE, Dataset


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
        raise Invalid(f"Expiration {args.date} is not listed for this underlying; list them with options expirations {ticker.ticker}")
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
        interpretation={"use": "Pass one to options chain --date."}),
    "options.chain": Dataset(
        chain, ticker=True, conditions=date_applied,
        units={"strike": CURRENCY, "lastPrice": CURRENCY, "bid": CURRENCY, "ask": CURRENCY, "change": CURRENCY,
               "percentChange": PERCENT, "impliedVolatility": RATE, "volume": COUNT, "openInterest": COUNT},
        interpretation={"staleness": "lastTradeDate is when that contract last traded, which for a thin strike can be days before the chain's most recent trades. A contract's lastPrice is only as recent as its lastTradeDate.",
                        "timezone": "lastTradeDate is UTC."},
        gotchas=["Contracts are ordered by strike, so a limit keeps the lowest strikes rather than the ones nearest the money."]),
}
