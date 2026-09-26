"""ETF and mutual fund composition, weights and operations."""
from yfinance_skill.yahoo.datasets import CURRENCY, MULTIPLE, RATE, WEIGHT, Dataset


def fund(attribute, **spec):
    def fetch(ticker, args, context, warnings):
        return getattr(ticker.get_funds_data(), attribute)
    return Dataset(fetch, ticker=True, **spec)


DATASETS = {
    "fund.overview": fund("fund_overview"),
    # 성진: 반환값이 문자열 하나라 --fields도 --limit도 줄이지 못한다. 줄일 수 없는 리프는 줄이는 법을 선언하지 않는다 —
    # 선언하면 fix가 그 인자를 권하고, 따라간 결과가 같은 크기로 다시 실패한다.
    "fund.description": fund(
        "description", sliceable=False,
        interpretation={"shape": "One text value. It cannot be narrowed by fields or rows; raise --max-chars or read the saved observation."}),
    "fund.holdings": fund(
        "top_holdings", rows=20, units={"Holding Percent": WEIGHT},
        interpretation={"coverage": "These are the top reported holdings only, so the weights do not sum to one and the rest of the portfolio is not described here."}),
    "fund.asset-classes": fund(
        "asset_classes",
        units={"cashPosition": WEIGHT, "stockPosition": WEIGHT, "bondPosition": WEIGHT, "preferredPosition": WEIGHT,
               "convertiblePosition": WEIGHT, "otherPosition": WEIGHT}),
    "fund.sector-weights": fund(
        "sector_weightings", units={"*": WEIGHT},
        interpretation={"keys": "Sector keys here use underscores (consumer_cyclical); market sector takes hyphenated keys (consumer-cyclical)."}),
    "fund.equity": fund(
        "equity_holdings",
        units={"Price/Earnings": dict(MULTIPLE, inverted=True), "Price/Book": dict(MULTIPLE, inverted=True),
               "Price/Sales": dict(MULTIPLE, inverted=True), "Price/Cashflow": dict(MULTIPLE, inverted=True),
               "Median Market Cap": CURRENCY, "3 Year Earnings Growth": RATE},
        interpretation={"inverted": "All four price multiples arrive as their reciprocals: the Price/Earnings row holds an earnings yield, so the P/E is 1 divided by the value."},
        gotchas=["The Category Average column is often empty, and where populated it can equal the fund's own value, so it is not a peer comparison."]),
    "fund.operations": fund(
        "fund_operations",
        units={"Annual Report Expense Ratio": RATE, "Annual Holdings Turnover": RATE,
               "Total Net Assets": {"kind": "currency", "scale": "unverified"}},
        interpretation={"expense": "The expense ratio is a ratio, not a percent: 0.000945 is 0.0945%."},
        gotchas=["Total Net Assets has no declared unit and does not reconcile with the fund's totalAssets as either the raw amount or millions. Cite it only with the fund's own reporting.",
                 "The Category Average column can hold an exact copy of the fund's own value, so a difference of zero there is not evidence of being at the peer average."]),
}
