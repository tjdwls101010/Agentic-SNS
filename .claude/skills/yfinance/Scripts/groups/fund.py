"""ETF and mutual fund composition, weights and operations."""
from registry import CURRENCY, MULTIPLE, RATE, SYMBOLS, WEIGHT, group, leaf

group("fund", "ETF and mutual fund composition, weights and operations")


def fund(name, purpose, attribute, **spec):
    def fetch(ticker, args, context, warnings):
        return getattr(ticker.get_funds_data(), attribute)
    leaf("fund", name, purpose, args=[SYMBOLS], ticker=True, **spec)(fetch)


fund("overview", "Fund family, category and legal type.", "fund_overview", narrow=["--fields"], exportable=False)

# 성진: 반환값이 문자열 하나라 --fields도 --limit도 줄이지 못한다. 줄일 수 없는 리프는 줄이는 법을 선언하지 않는다 —
# 선언하면 fix가 그 인자를 권하고, 따라간 결과가 같은 크기로 다시 실패한다.
fund("description", "The fund's own investment objective text.", "description", narrow=(), sliceable=False, exportable=False,
     interpretation={"shape": "One text value. It cannot be narrowed by fields or rows; raise --max-chars or read the saved observation."})

fund("holdings", "Largest reported holdings and their weights.", "top_holdings",
     limit=20, narrow=["--fields", "--limit"], units={"Holding Percent": WEIGHT},
     interpretation={"coverage": "These are the top reported holdings only, so the weights do not sum to one and the rest of the portfolio is not described here."})

fund("asset-classes", "Allocation across cash, stock, bond, preferred and convertible.", "asset_classes", narrow=["--fields"], exportable=False,
     units={"cashPosition": WEIGHT, "stockPosition": WEIGHT, "bondPosition": WEIGHT, "preferredPosition": WEIGHT,
            "convertiblePosition": WEIGHT, "otherPosition": WEIGHT})

fund("sector-weights", "Portfolio weight by sector.", "sector_weightings", narrow=["--fields"], exportable=False,
     units={"*": WEIGHT},
     interpretation={"keys": "Sector keys here use underscores (consumer_cyclical); market sector takes hyphenated keys (consumer-cyclical)."})

fund("equity", "Valuation multiples and growth for the fund's equity holdings.", "equity_holdings", narrow=["--fields"],
     units={"Price/Earnings": dict(MULTIPLE, inverted=True), "Price/Book": dict(MULTIPLE, inverted=True),
            "Price/Sales": dict(MULTIPLE, inverted=True), "Price/Cashflow": dict(MULTIPLE, inverted=True),
            "Median Market Cap": CURRENCY, "3 Year Earnings Growth": RATE},
     interpretation={"inverted": "All four price multiples arrive as their reciprocals: the Price/Earnings row holds an earnings yield, so a P/E is 1 divided by the value. Measured across SPY, QQQ, VTI, IWM and VOO, the reciprocals matched each index's known multiple, so reporting the value as printed is wrong by that inversion."},
     gotchas=["The Category Average column is often empty, and where it is populated it has been observed equal to the fund's own value, so it cannot be relied on as a peer comparison."])

fund("operations", "Expense ratio, turnover and reported net assets.", "fund_operations", narrow=["--fields"],
     units={"Annual Report Expense Ratio": RATE, "Annual Holdings Turnover": RATE,
            "Total Net Assets": {"kind": "currency", "scale": "unverified"}},
     interpretation={"expense": "The expense ratio is a ratio, not a percent: 0.000945 is 0.0945%."},
     gotchas=["Total Net Assets has no declared unit and does not reconcile: SPY reported 513,975.7 here while the same fund's totalAssets was 811,937,038,336, so it is neither the raw amount nor that amount in millions. Cite it only with the fund's own reporting.",
              "The Category Average column has been observed holding an exact copy of the fund's own value, so a difference of zero there is not evidence of being at the peer average."])
