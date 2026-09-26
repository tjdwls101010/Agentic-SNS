"""Analyst estimates, revisions, recommendations and rating actions."""
from yfinance_skill.yahoo.datasets import COUNT, CURRENCY, PER_SHARE, RATE, Dataset


def getter(method):
    def fetch(ticker, args, context, warnings):
        return getattr(ticker, method)()
    return fetch


def analyst(method, **spec):
    return Dataset(getter(method), ticker=True, **spec)


RELATIVE = "0q, +1q, 0y and +1y are relative periods, not dates."
ANALYST_COUNTS = {"strongBuy": COUNT, "buy": COUNT, "hold": COUNT, "sell": COUNT, "strongSell": COUNT}

DATASETS = {
    "analysts.targets": analyst(
        "get_analyst_price_targets",
        units={"current": CURRENCY, "high": CURRENCY, "low": CURRENCY, "mean": CURRENCY, "median": CURRENCY},
        interpretation={"currency": "Targets are in the quote currency.", "current": "current is the live price the targets are being compared against, not a target."}),
    "analysts.recommendations": analyst(
        "get_recommendations", units=ANALYST_COUNTS,
        interpretation={"periods": "period 0m is the current month and -1m, -2m, -3m are earlier months, so rows are relative, not dated."}),
    "analysts.summary": analyst(
        "get_recommendations_summary", units=ANALYST_COUNTS,
        interpretation={"periods": "period 0m is the current month; earlier months are relative offsets."}),
    "analysts.upgrades": analyst(
        "get_upgrades_downgrades", rows=20,
        interpretation={"order": "Actions arrive newest first, so a limit keeps the most recent ones.",
                        "history": "The full history reaches back more than a decade; the default keeps one screen of the newest actions and coverage reports how many were received."}),
    "analysts.earnings-estimate": analyst(
        "get_earnings_estimate",
        units={"growth": RATE, "avg": PER_SHARE, "low": PER_SHARE, "high": PER_SHARE, "yearAgoEps": PER_SHARE, "numberOfAnalysts": COUNT},
        interpretation={"periods": RELATIVE}),
    "analysts.revenue-estimate": analyst(
        "get_revenue_estimate",
        units={"growth": RATE, "avg": CURRENCY, "low": CURRENCY, "high": CURRENCY, "yearAgoRevenue": CURRENCY, "numberOfAnalysts": COUNT},
        interpretation={"periods": RELATIVE}),
    "analysts.history": analyst(
        "get_earnings_history", recent=True,
        units={"epsActual": PER_SHARE, "epsEstimate": PER_SHARE, "epsDifference": PER_SHARE, "surprisePercent": RATE},
        interpretation={"dates": "The index is the fiscal quarter end, not the announcement date.",
                        "surprise": "surprisePercent is a ratio despite its name: 0.0452 is a 4.52% surprise. calendar earnings reports the same measurement as Surprise(%) on a percent scale, so the two are 100x apart and must not be compared directly."}),
    "analysts.revisions": analyst(
        "get_eps_revisions",
        units={"upLast7days": COUNT, "upLast30days": COUNT, "downLast7Days": COUNT, "downLast30days": COUNT},
        interpretation={"periods": "0q, +1q, 0y and +1y are relative periods.",
                        "counts": "These are analyst counts, not magnitudes; a revision's size is not reported here."}),
    "analysts.trend": analyst(
        "get_eps_trend",
        units={"current": PER_SHARE, "7daysAgo": PER_SHARE, "30daysAgo": PER_SHARE, "60daysAgo": PER_SHARE, "90daysAgo": PER_SHARE},
        interpretation={"periods": "Rows are relative periods and columns are how long ago the estimate was current."}),
    "analysts.growth": analyst(
        "get_growth_estimates", units={"stockTrend": RATE, "indexTrend": RATE},
        interpretation={"periods": "0q, +1q, 0y, +1y and LTG are relative periods; LTG is a long-term annualised expectation."}),
}
