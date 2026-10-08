"""ETF and mutual fund overview, objective, holdings, allocations and the fund's reported equity statistics and operations."""
from invest.yahoo.datasets import Dataset
from invest.yahoo.refusals import not_applicable
from invest.yahoo.units import INVERSE, MONEY_QUOTE, MULTIPLE, PERCENT, RATIO, TEXT, UNVERIFIED, u

FUNDS = ("ETF", "MUTUALFUND")


def fund(attribute, what):
    """One part of Yahoo's fund data. A stock has none: yfinance raises KeyError 'topHoldings' after reading the quoteType, which says why."""
    def fetch(ticker, args, context):
        data = ticker.get_funds_data()
        try:
            found = getattr(data, attribute)
        except KeyError:
            raise not_applicable(confirmed_type(data), FUNDS, what) from None
        context.quote_type = data.quote_type()
        return found
    return fetch


def confirmed_type(data):
    """The quoteType yfinance read before the missing part raised, or None when the response did not carry one either."""
    try:
        return data.quote_type()
    except Exception:
        return None


MULTIPLE_ROWS = ("Price/Earnings", "Price/Book", "Price/Sales", "Price/Cashflow")


def equity_unit(metric, column):
    """The four price multiples arrive as reciprocals (an earnings yield), in the fund's column and the Category Average alike."""
    if metric in MULTIPLE_ROWS:
        return u(MULTIPLE, INVERSE)
    if metric == "Median Market Cap":
        return u(MONEY_QUOTE)
    if metric == "3 Year Earnings Growth":
        return u(RATIO, PERCENT)
    return u(UNVERIFIED)


def operations_unit(metric, column):
    if metric in ("Annual Report Expense Ratio", "Annual Holdings Turnover"):
        return u(RATIO)
    return u(UNVERIFIED)


DATASETS = {
    "fund.overview": Dataset(fund("fund_overview", "fund overviews"), form="row", units={"*": u(TEXT)}, coverage="Yahoo's fund profile"),
    "fund.description": Dataset(fund("description", "fund descriptions"), form="records", coverage="the fund's own objective text"),
    "fund.holdings": Dataset(
        fund("top_holdings", "fund holdings"), units={"Symbol": u(TEXT), "Name": u(TEXT), "Holding Percent": u(RATIO)},
        coverage="the top holdings Yahoo lists, which need not cover the whole portfolio"),
    "fund.asset-classes": Dataset(fund("asset_classes", "asset allocations"), form="row", units={"*": u(RATIO)}, coverage="the fund's allocation across asset classes"),
    "fund.sectors": Dataset(
        fund("sector_weightings", "sector weights"), form="row", units={"*": u(RATIO)}, coverage="the fund's weight in each sector",
        notes=("Sector keys use underscores here (consumer_cyclical); market sector takes hyphens (consumer-cyclical).",)),
    "fund.equity": Dataset(
        fund("equity_holdings", "equity statistics"), form="mixed", mixed=equity_unit,
        coverage="the valuation and growth statistics the fund reports for its equity holdings",
        notes=("The four price multiples are the fund-reported figures for its holdings, converted from the reciprocal Yahoo serves; the Category Average column is often empty.",),
        possible=("inverse_of_zero",)),
    "fund.operations": Dataset(
        fund("fund_operations", "fund operations"), form="mixed", mixed=operations_unit,
        coverage="the fund's expense ratio, turnover and reported net assets",
        notes=("Total Net Assets is unverified: it does not reconcile with the quote's totalAssets as an amount or in millions, so do not compute with it.",
               "The Category Average column can repeat the fund's own value, so a zero difference is not evidence of being at the average.")),
}
