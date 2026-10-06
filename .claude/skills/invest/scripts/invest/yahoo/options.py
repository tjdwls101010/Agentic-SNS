"""Option expirations and one expiration's chain, by side."""
import pandas as pd

from invest.receipts import Invalid
from invest.yahoo.conditions import condition
from invest.yahoo.datasets import Dataset
from invest.yahoo.units import COUNT, DATE, DATETIME, EPOCH, PER_SHARE_QUOTE, PERCENT, RATIO, TEXT, converted, u


def expirations(ticker, args, context):
    return pd.DataFrame({"expiration": list(ticker.options)})


def chain(ticker, args, context):
    listed = list(ticker.options)
    if args.date and args.date not in listed:
        raise Invalid(f"Expiration {args.date} is not listed for {ticker.ticker}",
                      fix=f"Choose one of the expirations `options expirations {ticker.ticker}` lists.")
    if not listed:
        return None
    expiry = args.date or listed[0]
    found = ticker.option_chain(date=expiry)
    underlying = found.underlying or {}
    context.currency = underlying.get("currency")
    context.as_of.update(expiration=expiry, underlying_price=underlying.get("regularMarketPrice"),
                         regularMarketTime=converted(underlying.get("regularMarketTime"), EPOCH) if underlying.get("regularMarketTime") else None)
    if args.date:
        context.conditions["date"] = condition(args.date, "confirmed" if expiry == args.date else "not_applied", {"expiration": expiry})
    sides = ["calls", "puts"] if args.side == "both" else [args.side]
    frames = []
    for side in sides:
        frame = getattr(found, side).copy()
        frame.insert(0, "side", side[:-1])
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else None


CHAIN_UNITS = {"side": u(TEXT), "contractSymbol": u(TEXT), "lastTradeDate": u(DATETIME), "strike": u(PER_SHARE_QUOTE), "lastPrice": u(PER_SHARE_QUOTE),
               "bid": u(PER_SHARE_QUOTE), "ask": u(PER_SHARE_QUOTE), "change": u(PER_SHARE_QUOTE),
               "percentChange": u(RATIO, PERCENT),
               "volume": u(COUNT), "openInterest": u(COUNT), "impliedVolatility": u(RATIO), "inTheMoney": u(TEXT), "contractSize": u(TEXT),
               "currency": u(TEXT)}
DATASETS = {
    "options.expirations": Dataset(expirations, units={"expiration": u(DATE)}, coverage="every expiration Yahoo lists for the underlying",
                                   notes=("Pass one to options chain --date.",)),
    "options.chain": Dataset(
        chain, units=CHAIN_UNITS, coverage="every contract Yahoo lists for one expiration, ordered by strike within each side",
        notes=("lastTradeDate (UTC) is when that contract last traded, which for a thin strike can be days old; lastPrice is only as recent as it.",)),
}
