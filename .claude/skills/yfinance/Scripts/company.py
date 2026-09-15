"""Explicit purpose-to-public-API adapters; no reflection-based API exposure."""
from output import InputError, select

ANALYSTS = {"targets": "get_analyst_price_targets", "recommendations": "get_recommendations", "summary": "get_recommendations_summary", "upgrades": "get_upgrades_downgrades", "earnings-estimate": "get_earnings_estimate", "revenue-estimate": "get_revenue_estimate", "history": "get_earnings_history", "revisions": "get_eps_revisions", "trend": "get_eps_trend", "growth": "get_growth_estimates"}
HOLDERS = {"major": "get_major_holders", "institutional": "get_institutional_holders", "fund": "get_mutualfund_holders", "insider-purchases": "get_insider_purchases", "insider-transactions": "get_insider_transactions", "insider-roster": "get_insider_roster_holders"}
FUNDS = {"overview": "fund_overview", "description": "description", "holdings": "top_holdings", "asset-classes": "asset_classes", "sector-weights": "sector_weightings", "equity": "equity_holdings", "bond": "bond_holdings", "rating": "bond_ratings", "operations": "fund_operations"}
STATEMENTS = {"income": "get_income_stmt", "balance": "get_balance_sheet", "cashflow": "get_cash_flow"}


def fetch(ticker, args, context, warnings):
    if args.group == "financials" and args.leaf in STATEMENTS:
        frame = getattr(ticker, STATEMENTS[args.leaf])(freq=args.frequency, pretty=False)
        context.update(currency=None, date_meaning="fiscal_period_end", orientation="period_rows", periods_available=len(frame.columns))
        warnings.append("Source statement currency is unconfirmed; no quote currency is substituted. yfinance may have converted source numbers to floating point.")
        return frame.iloc[:, :args.periods].T
    if (args.group, args.leaf) in {("company", "profile"), ("prices", "quote")}:
        data = ticker.get_info()
        context.update(currency=data.get("currency"), financial_currency=data.get("financialCurrency"), as_of="Per-field timestamps when supplied; observed_at is retrieval time, not quote time.")
        return data
    if args.group == "analysts":
        context.update(currency=None, units="Native values; currency is unconfirmed unless supplied in data.")
        return getattr(ticker, ANALYSTS[args.leaf])()
    if args.group == "holders":
        context.update(currency=None, units="Native values; no percentage or currency conversion.")
        return getattr(ticker, HOLDERS[args.leaf])()
    if args.group == "fund":
        context.update(currency=None, units="Native values; weights and percentages are not rescaled.")
        if args.leaf == "holdings":
            context["coverage"] = "top_reported_holdings"
        return getattr(ticker.get_funds_data(), FUNDS[args.leaf])
    if args.group == "options":
        if args.leaf == "expirations":
            return list(ticker.options)
        expirations = list(ticker.options)
        if args.date and args.date not in expirations:
            raise InputError(f"Expiration {args.date} unavailable; use options expirations {ticker.ticker}")
        expiry = args.date or (expirations[0] if expirations else None)
        context.update(expiration=expiry, last_trade_timezone="UTC", currency="Per-contract currency field")
        if not expirations:
            return None
        chain = ticker.option_chain(date=expiry)
        underlying = chain.underlying or {}
        context["underlying"] = {key: underlying.get(key) for key in ("symbol", "regularMarketPrice", "regularMarketTime", "currency", "exchangeTimezoneName")}
        context["underlying_detail"] = "prices quote SYMBOL returns the full underlying quote."
        sides = ["calls", "puts"] if args.side == "both" else [args.side]
        data = {}
        for side in sides:
            selection = {}
            data[side] = select(getattr(chain, side), args, selection)
            context[side] = selection
        return data
    if args.group == "company" and args.leaf == "news":
        return ticker.get_news(count=args.limit, tab=args.tab)
    if args.group == "company" and args.leaf == "filings":
        return ticker.get_sec_filings()
    if args.group == "company" and args.leaf == "shares":
        context.update(unit="shares", date_meaning="Yahoo observation timestamp, localized by yfinance", range="Omitted --end defaults to now and omitted --start to 548 days (about 18 months) earlier; observation timestamps are rounded to whole days")
        return ticker.get_shares_full(start=args.start, end=args.end)
    if args.group == "company" and args.leaf == "sustainability":
        return ticker.get_sustainability()
    if args.group == "financials" and args.leaf == "valuation":
        context.update(currency=None, date_meaning="Current is latest trailing snapshot; other labels are native period dates", orientation="period_rows")
        return ticker.get_valuation_measures(freq=args.frequency, periods=args.periods).T
    raise InputError("Command not implemented")
