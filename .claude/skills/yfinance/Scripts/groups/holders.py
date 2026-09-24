"""Institutional, fund and insider ownership."""
from registry import COUNT, CURRENCY, RATE, SHARES, SYMBOLS, group, leaf

group("holders", "Institutional, fund and insider ownership")


def holder(name, purpose, method, **spec):
    def fetch(ticker, args, context, warnings):
        return getattr(ticker, method)()
    leaf("holders", name, purpose, args=[SYMBOLS], ticker=True, **spec)(fetch)


holder("major", "Insider and institutional ownership percentages for the whole company.", "get_major_holders", narrow=["--limit"],
       units={"insidersPercentHeld": RATE, "institutionsPercentHeld": RATE, "institutionsFloatPercentHeld": RATE, "institutionsCount": COUNT},
       interpretation={"float": "institutionsPercentHeld is of shares outstanding while institutionsFloatPercentHeld is of the float, so the second is the larger of the two."})

HOLDER_MIX = "Date Reported is when the position was filed, but Value is that share count priced at the current quote, so it is not the position's worth on its reported date."

for _leaf, _what, _method in [("institutional", "Institutional", "get_institutional_holders"), ("fund", "Mutual fund", "get_mutualfund_holders")]:
    holder(_leaf, _what + " holders with their reported share counts.", _method,
           limit=20, narrow=["--fields", "--limit"],
           units={"pctHeld": RATE, "pctChange": RATE, "Shares": SHARES, "Value": dict(CURRENCY, as_of="current_quote")},
           interpretation={"mixed_times": HOLDER_MIX,
                           "coverage": "These are the largest reported holders, not every holder."})

holder("insider-purchases", "Insider purchase and sale totals over the last six months.", "get_insider_purchases", narrow=["--fields"],
       units={"Shares": SHARES, "Trans": COUNT},
       interpretation={"rows": "The first column labels each row; % rows carry ratios while the others carry share counts, in the same column."})

holder("insider-transactions", "Individual insider transactions with dates, roles and values.", "get_insider_transactions",
       limit=20, narrow=["--fields", "--limit"],
       units={"Shares": SHARES, "Value": CURRENCY},
       interpretation={"order": "The index is a row number and says nothing about time; Start Date does, and rows arrive newest first, so a limit keeps the most recent transactions.",
                       "value": "Value is absent for transactions that report no price, such as gifts and some awards; that is a missing price, not a zero-value transfer."})

holder("insider-roster", "Insiders and the shares they hold directly.", "get_insider_roster_holders",
       limit=20, narrow=["--fields", "--limit"],
       units={"Shares Owned Directly": SHARES},
       interpretation={"direct_only": "Shares Owned Directly excludes indirect holdings through trusts and partnerships, so it understates total control.",
                       "dates": "Latest Transaction Date is that insider's most recent filing, so different rows are current as of different dates."})
