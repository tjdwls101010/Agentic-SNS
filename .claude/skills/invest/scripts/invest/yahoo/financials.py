"""Financial statements and valuation measures by period, in the currency each is reported in."""
from invest.yahoo.datasets import Dataset
from invest.yahoo.refusals import is_rate_limited
from invest.yahoo.units import DATETIME, MONEY_FINANCIAL, MONEY_QUOTE, MULTIPLE, PER_SHARE_FINANCIAL, RATIO, SHARES, TEXT, u

STATEMENTS = {"income": "get_income_stmt", "balance": "get_balance_sheet", "cashflow": "get_cash_flow"}
# Every line item is an amount in the reporting currency except these, which name a per-share amount, a share count or a rate.
STATEMENT_UNITS = {"*": u(MONEY_FINANCIAL), "Date": u(DATETIME),
                   "TaxRateForCalcs": u(RATIO), "BasicEPS": u(PER_SHARE_FINANCIAL), "DilutedEPS": u(PER_SHARE_FINANCIAL),
                   "BasicAverageShares": u(SHARES), "DilutedAverageShares": u(SHARES), "ShareIssued": u(SHARES),
                   "OrdinarySharesNumber": u(SHARES), "TreasurySharesNumber": u(SHARES), "PreferredSharesNumber": u(SHARES)}
VALUATION_UNITS = {"Date": u(TEXT), "Market Cap": u(MONEY_QUOTE), "Enterprise Value": u(MONEY_QUOTE), "Trailing P/E": u(MULTIPLE),
                   "Forward P/E": u(MULTIPLE), "PEG Ratio (5yr expected)": u(MULTIPLE), "Price/Sales": u(MULTIPLE), "Price/Book": u(MULTIPLE),
                   "Enterprise Value/Revenue": u(MULTIPLE), "Enterprise Value/EBITDA": u(MULTIPLE)}


def currencies(ticker, context):
    """The reporting and quote currencies, a second request: a rate limit here keeps the statement and stops the remaining targets."""
    try:
        info = ticker.get_info() or {}
    except Exception as exc:
        if is_rate_limited(exc):
            context.rate_limited = True
            context.warn("secondary_rate_limited", "Yahoo rate-limited the currency lookup after the statement arrived; the statement is kept and the remaining targets were not attempted.")
        context.receipt["currency_error"] = str(exc)
        return
    context.financial_currency, context.currency = info.get("financialCurrency"), info.get("currency")


def statement(method):
    def fetch(ticker, args, context):
        frame = getattr(ticker, method)(freq=args.frequency, pretty=False)
        currencies(ticker, context)
        if frame is None or frame.empty:
            return frame
        frame = frame.T.sort_index(ascending=False)
        frame.index.name = "Date"
        return frame
    return fetch


def valuation(ticker, args, context):
    frame = ticker.get_valuation_measures(freq=args.frequency, periods=args.periods)
    currencies(ticker, context)
    if frame is None or frame.empty:
        return frame
    frame = frame.T
    frame.index.name = "Date"
    return frame


DATED = "Date is the fiscal period end, not the day the figures were announced."
DATASETS = {
    f"financials.{name}": Dataset(statement(method), units=STATEMENT_UNITS, coverage="every period Yahoo lists for this frequency, newest first",
                                  notes=(DATED, "trailing rows are a rolling twelve months, not a completed fiscal year."))
    for name, method in STATEMENTS.items()
} | {
    "financials.valuation": Dataset(
        valuation, units=VALUATION_UNITS, coverage="the periods asked for with --periods, plus Current",
        notes=("Current is the latest trailing snapshot, not a completed period; the other rows are period dates.",)),
}
