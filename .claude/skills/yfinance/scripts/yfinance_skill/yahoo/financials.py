"""Statements and valuation measures by period."""
from yfinance_skill.yahoo.datasets import CURRENCY, MULTIPLE, PER_SHARE, RATE, SHARES, Dataset

STATEMENT_DATES = "Column labels are fiscal period end dates, not announcement dates."
STATEMENT_INTERPRETATION = {
    "dates": STATEMENT_DATES,
    "currency": "The reported currency is in context.currency, read from the same company's financialCurrency. It can differ from the currency the share price is quoted in.",
    "orientation": "Rows are periods and columns are native line items, so --fields selects line items.",
    "scale": "One statement mixes measurements: a rate such as TaxRateForCalcs sits in the same row as a currency amount such as NormalizedEBITDA. The label is the only thing distinguishing them, so read a line item's name before comparing its magnitude to another's.",
}
STATEMENT_UNITS = {"TaxRateForCalcs": RATE, "TaxEffectOfUnusualItems": CURRENCY, "BasicEPS": PER_SHARE, "DilutedEPS": PER_SHARE,
                   "BasicAverageShares": SHARES, "DilutedAverageShares": SHARES, "ShareIssued": SHARES, "OrdinarySharesNumber": SHARES, "TreasurySharesNumber": SHARES}
STATEMENTS = {"income": "get_income_stmt", "balance": "get_balance_sheet", "cashflow": "get_cash_flow"}


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


def statement(method):
    def fetch(ticker, args, context, warnings):
        frame = getattr(ticker, method)(freq=args.frequency, pretty=False)
        context.update(periods_available=len(frame.columns))
        statement_currency(ticker, context, warnings)
        return frame.iloc[:, :args.periods].T
    return fetch


def valuation(ticker, args, context, warnings):
    return ticker.get_valuation_measures(freq=args.frequency, periods=args.periods).T


DATASETS = {
    f"financials.{name}": Dataset(
        statement(method), ticker=True, units=STATEMENT_UNITS,
        interpretation=dict(STATEMENT_INTERPRETATION, frequency=("Balance sheet frequencies are yearly and quarterly only." if name == "balance" else "trailing returns TTM, which is a rolling twelve months and not a completed fiscal period.")))
    for name, method in STATEMENTS.items()
} | {
    "financials.valuation": Dataset(
        valuation, ticker=True,
        units={"Market Cap": CURRENCY, "Enterprise Value": CURRENCY, "Trailing P/E": MULTIPLE, "Forward P/E": MULTIPLE,
               "PEG Ratio (5yr expected)": MULTIPLE, "Price/Sales": MULTIPLE, "Price/Book": MULTIPLE,
               "Enterprise Value/Revenue": MULTIPLE, "Enterprise Value/EBITDA": MULTIPLE},
        interpretation={"dates": "Labels other than Current are native period dates; Current is the latest trailing snapshot, not a completed fiscal period.",
                        "periods": "--periods is sent upstream here rather than applied locally; 0 returns Current only."}),
}
