"""Major, institutional and fund holders, and insider purchases, transactions and roster."""
from invest.yahoo.datasets import Dataset
from invest.yahoo.units import COUNT, DATETIME, MONEY_QUOTE, RATIO, SHARES, TEXT, u


def holder(method):
    def fetch(ticker, args, context):
        return getattr(ticker, method)()
    return fetch


def reported(method):
    """Institutional or fund holders: the newest reported quarter end goes to as_of, and Value's pricing goes to warnings."""
    def fetch(ticker, args, context):
        frame = getattr(ticker, method)()
        if frame is not None and not frame.empty and "Date Reported" in frame.columns:
            context.as_of["date_reported"] = str(frame["Date Reported"].max())[:10]
            context.warn("value_at_current_quote", "Value prices the reported shares at the current quote, not at Date Reported.")
        return frame
    return fetch


def major_unit(metric, column):
    return u(COUNT) if metric == "institutionsCount" else u(RATIO)


def purchase_unit(metric, column):
    """insider-purchases mixes units down one column: the % rows are ratios, the rest share counts, and Trans counts transactions."""
    if column == "Trans":
        return u(COUNT)
    return u(RATIO) if str(metric).startswith("%") else u(SHARES)


HOLDER_UNITS = {"Date Reported": u(DATETIME), "Holder": u(TEXT), "pctHeld": u(RATIO), "Shares": u(SHARES), "Value": u(MONEY_QUOTE), "pctChange": u(RATIO)}
DATASETS = {
    "holders.major": Dataset(
        holder("get_major_holders"), form="mixed", mixed=major_unit,
        coverage="Yahoo's ownership breakdown for the whole company",
        notes=("institutionsPercentHeld is of shares outstanding, institutionsFloatPercentHeld of the float.",)),
    "holders.institutional": Dataset(
        reported("get_institutional_holders"), units=HOLDER_UNITS, coverage="the largest institutional holders Yahoo lists, not every holder",
        notes=("Date Reported is the quarter end the position is reported as of.",), possible=("value_at_current_quote",)),
    "holders.funds": Dataset(
        reported("get_mutualfund_holders"), units=HOLDER_UNITS, coverage="the largest mutual fund holders Yahoo lists, not every holder",
        notes=("Date Reported is the quarter end the position is reported as of.",), possible=("value_at_current_quote",)),
    "holders.insider-purchases": Dataset(
        holder("get_insider_purchases"), form="mixed", mixed=purchase_unit, label="Insider Purchases Last 6m",
        coverage="Yahoo's six-month summary of insider purchases and sales"),
    "holders.insider-transactions": Dataset(
        holder("get_insider_transactions"), units={"Shares": u(SHARES), "Value": u(MONEY_QUOTE), "Start Date": u(DATETIME)},
        coverage="Yahoo's recent insider transactions, newest first, not every filing",
        notes=("Value is empty where the source reports no price, including rows whose Text is empty: a missing price, not a zero-value transfer.",)),
    "holders.insider-roster": Dataset(
        holder("get_insider_roster_holders"),
        units={"Shares Owned Directly": u(SHARES), "Shares Owned Indirectly": u(SHARES), "Latest Transaction Date": u(DATETIME), "Position Direct Date": u(DATETIME),
               "Position Indirect Date": u(DATETIME)},
        coverage="the insiders Yahoo lists with their direct holdings",
        notes=("Shares Owned Directly excludes holdings through trusts and partnerships.", "Each row is current as of its own Latest Transaction Date.")),
}
