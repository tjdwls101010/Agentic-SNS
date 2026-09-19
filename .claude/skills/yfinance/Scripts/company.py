"""Explicit purpose-to-public-API adapters; no reflection-based API exposure.

An adapter returns what the library gave and states what it observed. It does not echo an argument back as though the
response had confirmed it, and it does not decline to report a value it could have looked up: `currency: null` on a
statement read as "unconfirmable" when it only meant "this leaf never asked".
"""
import leaves
from output import InputError

ANALYSTS = {"targets": "get_analyst_price_targets", "recommendations": "get_recommendations", "summary": "get_recommendations_summary", "upgrades": "get_upgrades_downgrades", "earnings-estimate": "get_earnings_estimate", "revenue-estimate": "get_revenue_estimate", "history": "get_earnings_history", "revisions": "get_eps_revisions", "trend": "get_eps_trend", "growth": "get_growth_estimates"}
HOLDERS = {"major": "get_major_holders", "institutional": "get_institutional_holders", "fund": "get_mutualfund_holders", "insider-purchases": "get_insider_purchases", "insider-transactions": "get_insider_transactions", "insider-roster": "get_insider_roster_holders"}
FUNDS = {"overview": "fund_overview", "description": "description", "holdings": "top_holdings", "asset-classes": "asset_classes", "sector-weights": "sector_weightings", "equity": "equity_holdings", "operations": "fund_operations"}
STATEMENTS = {"income": "get_income_stmt", "balance": "get_balance_sheet", "cashflow": "get_cash_flow"}
INFO_LEAVES = {("company", "profile"), ("prices", "quote")}

# 성진: quote가 싣는 시각 필드. 원천이 말하는 시각과 CLI 관측시각은 장 마감 후 몇 시간 벌어진다.
SOURCE_TIME_FIELDS = ("regularMarketTime", "postMarketTime")


def source_time(info):
    for field in SOURCE_TIME_FIELDS:
        value = info.get(field)
        if value:
            return value
    return None


def statement_currency(ticker, context, warnings):
    """Report the currency the statements are reported in, which is not the currency the share price is quoted in.

    Reading a price in one currency against a profit in another is wrong by the exchange rate — measured, about 150x
    for a JPY reporter quoted in USD — and the value is one lookup away, so declining to report it was not caution.
    """
    try:
        info = ticker.get_info()
    except Exception as exc:  # the statement is still the answer; the currency is what could not be confirmed
        warnings.append(f"Statement currency could not be read, so the reported figures carry no confirmed currency: {exc}")
        context["currency"] = None
        return
    context["currency"] = info.get("financialCurrency")
    context["quote_currency"] = info.get("currency")
    if context["currency"] is None:
        warnings.append("The source reported no financialCurrency for this company, so the statement's currency is unconfirmed.")


def fetch(ticker, args, context, warnings):
    if args.group == "financials" and args.leaf in STATEMENTS:
        frame = getattr(ticker, STATEMENTS[args.leaf])(freq=args.frequency, pretty=False)
        context.update(periods_available=len(frame.columns))
        statement_currency(ticker, context, warnings)
        return frame.iloc[:, :args.periods].T
    if (args.group, args.leaf) in INFO_LEAVES:
        data = ticker.get_info()
        context.update(currency=data.get("currency"), financial_currency=data.get("financialCurrency"))
        return data
    if args.group == "analysts":
        return getattr(ticker, ANALYSTS[args.leaf])()
    if args.group == "holders":
        return getattr(ticker, HOLDERS[args.leaf])()
    if args.group == "fund":
        return getattr(ticker.get_funds_data(), FUNDS[args.leaf])
    if args.group == "options":
        return options(ticker, args, context)
    if args.group == "company" and args.leaf == "news":
        context["upstream_requested"] = leaves.effective_limit(args, leaves.get("company", "news")) or 10
        return ticker.get_news(count=context["upstream_requested"], tab=args.tab)
    if args.group == "company" and args.leaf == "filings":
        return ticker.get_sec_filings()
    if args.group == "company" and args.leaf == "shares":
        return ticker.get_shares_full(start=args.start, end=args.end)
    if args.group == "financials" and args.leaf == "valuation":
        return ticker.get_valuation_measures(freq=args.frequency, periods=args.periods).T
    raise InputError("Command not implemented")


def options(ticker, args, context):
    if args.leaf == "expirations":
        return list(ticker.options)
    expirations = list(ticker.options)
    if args.date and args.date not in expirations:
        raise InputError(f"Expiration {args.date} is not listed for this underlying; list them with options expirations {ticker.ticker}")
    if not expirations:
        return None
    expiry = args.date or expirations[0]
    chain = ticker.option_chain(date=expiry)
    underlying = chain.underlying or {}
    context["expiration"] = expiry
    context["underlying"] = {key: underlying.get(key) for key in ("symbol", "regularMarketPrice", "regularMarketTime", "currency", "exchangeTimezoneName")}
    sides = ["calls", "puts"] if args.side == "both" else [args.side]
    return {side: getattr(chain, side) for side in sides}
