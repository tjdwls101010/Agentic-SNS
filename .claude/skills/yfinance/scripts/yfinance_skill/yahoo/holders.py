"""Institutional, fund and insider ownership."""
from yfinance_skill.yahoo.datasets import COUNT, CURRENCY, RATE, SHARES, Dataset


def holder(method, **spec):
    def fetch(ticker, args, context, warnings):
        return getattr(ticker, method)()
    return Dataset(fetch, ticker=True, **spec)


HOLDER_MIX = "Date Reported is when the position was filed, but Value is that share count priced at the current quote, so it is not the position's worth on its reported date."

DATASETS = {
    "holders.major": holder(
        "get_major_holders",
        units={"insidersPercentHeld": RATE, "institutionsPercentHeld": RATE, "institutionsFloatPercentHeld": RATE, "institutionsCount": COUNT},
        interpretation={"float": "institutionsPercentHeld is of shares outstanding while institutionsFloatPercentHeld is of the float, so the second is the larger of the two."}),
} | {
    f"holders.{name}": holder(
        method, rows=20,
        units={"pctHeld": RATE, "pctChange": RATE, "Shares": SHARES, "Value": dict(CURRENCY, as_of="current_quote")},
        interpretation={"mixed_times": HOLDER_MIX,
                        "coverage": "These are the largest reported holders, not every holder."})
    for name, method in [("institutional", "get_institutional_holders"), ("fund", "get_mutualfund_holders")]
} | {
    "holders.insider-purchases": holder(
        "get_insider_purchases", units={"Shares": SHARES, "Trans": COUNT},
        interpretation={"rows": "The first column labels each row; % rows carry ratios while the others carry share counts, in the same column."}),
    "holders.insider-transactions": holder(
        "get_insider_transactions", rows=20, units={"Shares": SHARES, "Value": CURRENCY},
        interpretation={"order": "The index is a row number and says nothing about time; Start Date does, and rows arrive newest first, so a limit keeps the most recent transactions.",
                        "value": "Value is absent for transactions that report no price, such as gifts and some awards; that is a missing price, not a zero-value transfer."}),
    "holders.insider-roster": holder(
        "get_insider_roster_holders", rows=20, units={"Shares Owned Directly": SHARES},
        interpretation={"direct_only": "Shares Owned Directly excludes indirect holdings through trusts and partnerships, so it understates total control.",
                        "dates": "Latest Transaction Date is that insider's most recent filing, so different rows are current as of different dates."}),
}
