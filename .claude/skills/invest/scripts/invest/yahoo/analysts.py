"""Analyst price targets, recommendations, rating actions, estimates, revisions and growth."""
from invest.yahoo.datasets import Dataset
from invest.yahoo.units import (COUNT, DATETIME, MONEY_UNCONFIRMED, PER_SHARE_QUOTE, PER_SHARE_UNCONFIRMED, RATIO, TEXT, u)


def getter(method, index_name=None):
    def fetch(ticker, args, context):
        found = getattr(ticker, method)()
        if index_name is not None and hasattr(found, "index"):
            found.index.name = index_name
        return found
    return fetch


RELATIVE = "period 0q, +1q, 0y and +1y are relative to the current fiscal quarter and year, not dates."
ROW_CURRENCY = "Yahoo does not say whether these amounts are in the quote or the reporting currency; the currency column names each row's own."
ESTIMATE = u(PER_SHARE_UNCONFIRMED)
COUNTS = {name: u(COUNT) for name in ("strongBuy", "buy", "hold", "sell", "strongSell", "numberOfAnalysts", "upLast7days", "upLast30days",
                                       "downLast7Days", "downLast30days", "downLast7days")}

DATASETS = {
    "analysts.targets": Dataset(
        getter("get_analyst_price_targets"), form="row",
        units={k: u(PER_SHARE_QUOTE) for k in ("current", "high", "low", "mean", "median")},
        coverage="Yahoo's consensus price target summary",
        notes=("current is the market price the targets are compared against, not a target.",)),
    "analysts.recommendations": Dataset(
        getter("get_recommendations"), units={"period": u(TEXT), **COUNTS}, coverage="analyst recommendation counts for the current and three earlier months",
        notes=("period 0m is the current month and -1m, -2m, -3m the earlier ones.",)),
    "analysts.upgrades": Dataset(
        getter("get_upgrades_downgrades"), units={"GradeDate": u(DATETIME), "currentPriceTarget": u(PER_SHARE_QUOTE), "priorPriceTarget": u(PER_SHARE_QUOTE)},
        coverage="the rating actions Yahoo lists, newest first"),
    "analysts.eps-estimate": Dataset(
        getter("get_earnings_estimate"), units={"period": u(TEXT), "avg": ESTIMATE, "low": ESTIMATE, "high": ESTIMATE, "yearAgoEps": ESTIMATE,
                                                "growth": u(RATIO), "currency": u(TEXT), **COUNTS},
        coverage="the consensus EPS estimate for the current and next quarter and year", notes=(RELATIVE, ROW_CURRENCY)),
    "analysts.revenue-estimate": Dataset(
        getter("get_revenue_estimate"), units={"period": u(TEXT), "avg": u(MONEY_UNCONFIRMED), "low": u(MONEY_UNCONFIRMED), "high": u(MONEY_UNCONFIRMED),
                                               "yearAgoRevenue": u(MONEY_UNCONFIRMED), "growth": u(RATIO), "currency": u(TEXT), **COUNTS},
        coverage="the consensus revenue estimate for the current and next quarter and year", notes=(RELATIVE, ROW_CURRENCY)),
    "analysts.eps-history": Dataset(
        getter("get_earnings_history"), units={"quarter": u(DATETIME), "epsActual": ESTIMATE, "epsEstimate": ESTIMATE, "epsDifference": ESTIMATE,
                                               "surprisePercent": u(RATIO, evidence="(epsActual - epsEstimate) / |epsEstimate| = surprisePercent (AAPL)")},
        coverage="the last four reported quarters",
        notes=("quarter is the fiscal quarter end, not the announcement date.",
               "Yahoo does not say whether the EPS amounts are in the quote or the reporting currency.")),
    "analysts.revisions": Dataset(
        getter("get_eps_revisions"), units={"period": u(TEXT), **COUNTS}, coverage="counts of upward and downward EPS estimate revisions",
        notes=(RELATIVE, "These count analysts, not the size of their revisions.")),
    "analysts.trend": Dataset(
        getter("get_eps_trend"), units={"period": u(TEXT), "current": ESTIMATE, "7daysAgo": ESTIMATE, "30daysAgo": ESTIMATE, "60daysAgo": ESTIMATE,
                                        "90daysAgo": ESTIMATE},
        coverage="how the consensus EPS estimate moved over the last 90 days", notes=(RELATIVE,)),
    "analysts.growth": Dataset(
        getter("get_growth_estimates"), units={"period": u(TEXT), "*": u(RATIO)},
        coverage="expected growth for the symbol beside its industry, sector and index",
        notes=("period LTG is the long-term growth estimate; the others are relative quarters and years.",)),
}
