"""Analyst estimates, revisions, recommendations and rating actions."""
from yfinance_skill.registry import COUNT, CURRENCY, PER_SHARE, RATE, SYMBOLS, group, leaf

group("analysts", "Estimates, revisions, recommendations and rating actions")


def getter(method):
    def fetch(ticker, args, context, warnings):
        return getattr(ticker, method)()
    return fetch


def analyst(name, purpose, method, **spec):
    leaf("analysts", name, purpose, args=[SYMBOLS], ticker=True, **spec)(getter(method))


RELATIVE = "0q, +1q, 0y and +1y are relative periods, not dates."
ANALYST_COUNTS = {"strongBuy": COUNT, "buy": COUNT, "hold": COUNT, "sell": COUNT, "strongSell": COUNT}

analyst("targets", "Current analyst price target range.", "get_analyst_price_targets", narrow=["--fields"], exportable=False,
        units={"current": CURRENCY, "high": CURRENCY, "low": CURRENCY, "mean": CURRENCY, "median": CURRENCY},
        interpretation={"currency": "Targets are in the quote currency.", "current": "current is the live price the targets are being compared against, not a target."})

analyst("recommendations", "Analyst recommendation counts by month.", "get_recommendations", narrow=["--fields", "--limit"],
        units=ANALYST_COUNTS,
        interpretation={"periods": "period 0m is the current month and -1m, -2m, -3m are earlier months, so rows are relative, not dated."})

analyst("summary", "Analyst recommendation summary by month.", "get_recommendations_summary", narrow=["--fields", "--limit"],
        units=ANALYST_COUNTS,
        interpretation={"periods": "period 0m is the current month; earlier months are relative offsets."})

analyst("upgrades", "Rating upgrade and downgrade actions with their firms and dates.", "get_upgrades_downgrades",
        limit=20, narrow=["--fields", "--limit"],
        interpretation={"order": "Actions arrive newest first, so a limit keeps the most recent ones.",
                        "history": "The full history reaches back more than a decade; the default keeps one screen of the newest actions and coverage reports how many were received."})

analyst("earnings-estimate", "EPS estimates for the current and next quarter and year.", "get_earnings_estimate", narrow=["--fields"],
        units={"growth": RATE, "avg": PER_SHARE, "low": PER_SHARE, "high": PER_SHARE, "yearAgoEps": PER_SHARE, "numberOfAnalysts": COUNT},
        interpretation={"periods": RELATIVE})

analyst("revenue-estimate", "Revenue estimates for the current and next quarter and year.", "get_revenue_estimate", narrow=["--fields"],
        units={"growth": RATE, "avg": CURRENCY, "low": CURRENCY, "high": CURRENCY, "yearAgoRevenue": CURRENCY, "numberOfAnalysts": COUNT},
        interpretation={"periods": RELATIVE})

analyst("history", "Reported EPS against the estimate for past quarters.", "get_earnings_history",
        recent=True, narrow=["--fields", "--limit"],
        units={"epsActual": PER_SHARE, "epsEstimate": PER_SHARE, "epsDifference": PER_SHARE, "surprisePercent": RATE},
        interpretation={"dates": "The index is the fiscal quarter end, not the announcement date.",
                        "surprise": "surprisePercent is a ratio despite its name: 0.0452 is a 4.52% surprise. calendar earnings reports the same measurement as Surprise(%) on a percent scale, so the two are 100x apart and must not be compared directly."})

analyst("revisions", "Counts of upward and downward EPS estimate revisions.", "get_eps_revisions", narrow=["--fields"],
        units={"upLast7days": COUNT, "upLast30days": COUNT, "downLast7Days": COUNT, "downLast30days": COUNT},
        interpretation={"periods": "0q, +1q, 0y and +1y are relative periods.",
                        "counts": "These are analyst counts, not magnitudes; a revision's size is not reported here."})

analyst("trend", "How the consensus EPS estimate moved over the last 90 days.", "get_eps_trend", narrow=["--fields"],
        units={"current": PER_SHARE, "7daysAgo": PER_SHARE, "30daysAgo": PER_SHARE, "60daysAgo": PER_SHARE, "90daysAgo": PER_SHARE},
        interpretation={"periods": "Rows are relative periods and columns are how long ago the estimate was current."})

analyst("growth", "Expected growth for this instrument against its index.", "get_growth_estimates", narrow=["--fields"],
        units={"stockTrend": RATE, "indexTrend": RATE},
        interpretation={"periods": "0q, +1q, 0y, +1y and LTG are relative periods; LTG is a long-term annualised expectation."})
