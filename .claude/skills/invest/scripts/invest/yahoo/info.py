"""Yahoo's assembled info response, which quote and company profile both read: every numeric field's unit, its currency role, and its source times.

The scales are the source's and differ inside one response: dividendYield 0.32 means 0.32% while trailingAnnualDividendYield 0.0031 means 0.31%. Each declaration with evidence names the relation that settles it, which tests/invest/test_live.py measures again.
"""
from invest.receipts import Failure
from invest.yahoo.units import (COUNT, DATE, DATETIME, EPOCH, EPOCH_MS, MONEY_FINANCIAL, MONEY_QUOTE, MULTIPLE, PER_SHARE_FINANCIAL,
                                PER_SHARE_QUOTE, PERCENT, RANK, RATIO, SHARES, UNVERIFIED, converted, u)

PRICE = u(PER_SHARE_QUOTE)
PRICES = ("allTimeHigh", "allTimeLow", "ask", "bid", "currentPrice", "dayHigh", "dayLow", "fiftyDayAverage", "fiftyDayAverageChange",
          "fiftyTwoWeekHigh", "fiftyTwoWeekHighChange", "fiftyTwoWeekLow", "fiftyTwoWeekLowChange", "open", "previousClose",
          "regularMarketChange", "regularMarketDayHigh", "regularMarketDayLow", "regularMarketOpen", "regularMarketPreviousClose",
          "regularMarketPrice", "postMarketChange", "postMarketPrice", "preMarketChange", "preMarketPrice", "fulldayChange", "fulldayPrice",
          "twoHundredDayAverage", "twoHundredDayAverageChange", "navPrice", "lastCapGain", "lastDividendValue", "targetHighPrice",
          "targetLowPrice", "targetMeanPrice", "targetMedianPrice")
TIMES = ("regularMarketTime", "postMarketTime", "preMarketTime", "earningsTimestamp", "earningsTimestampStart", "earningsTimestampEnd",
         "earningsCallTimestampStart", "earningsCallTimestampEnd", "startDate", "expireDate")
DATES = ("dividendDate", "exDividendDate", "lastDividendDate", "lastFiscalYearEnd", "nextFiscalYearEnd", "mostRecentQuarter", "lastSplitDate",
         "governanceEpochDate", "compensationAsOfEpochDate", "dateShortInterest", "sharesShortPreviousMonthDate", "fundInceptionDate")
SHARE_COUNTS = ("averageDailyVolume10Day", "averageDailyVolume3Month", "averageVolume", "averageVolume10days", "regularMarketVolume", "volume",
                "floatShares", "sharesOutstanding", "impliedSharesOutstanding", "sharesShort", "sharesShortPriorMonth")
COUNTS = ("askSize", "bidSize", "fullTimeEmployees", "numberOfAnalystOpinions", "openInterest", "maxAge", "priceHint", "sourceInterval",
          "exchangeDataDelayedBy", "gmtOffSetMilliseconds", "blockNumber", "blockReward", "circulatingSupply", "maxSupply", "totalSupply")
MULTIPLES = ("beta", "beta3Year", "currentRatio", "quickRatio", "enterpriseToEbitda", "enterpriseToRevenue", "forwardPE", "trailingPE",
             "pegRatio", "trailingPegRatio", "priceToSalesTrailing12Months", "shortRatio")
RANKS = ("auditRisk", "boardRisk", "compensationRisk", "shareHolderRightsRisk", "overallRisk", "recommendationMean",
         "morningStarOverallRating", "morningStarRiskRating")
RATIOS = ("heldPercentInsiders", "heldPercentInstitutions", "shortPercentOfFloat", "operatingMargins", "revenueGrowth", "earningsGrowth",
          "earningsQuarterlyGrowth", "returnOnAssets", "returnOnEquity", "SandP52WeekChange", "threeYearAverageReturn", "fiveYearAverageReturn",
          "annualReportExpenseRatio", "annualHoldingsTurnover")
STATEMENT_MONEY = ("totalRevenue", "ebitda", "totalCash", "totalDebt", "grossProfits", "freeCashflow", "operatingCashflow", "netIncomeToCommon")

INFO_UNITS = {
    **{f: PRICE for f in PRICES}, **{f: u(DATETIME, EPOCH) for f in TIMES}, **{f: u(DATE, EPOCH) for f in DATES},
    **{f: u(SHARES) for f in SHARE_COUNTS}, **{f: u(COUNT) for f in COUNTS}, **{f: u(MULTIPLE) for f in MULTIPLES},
    **{f: u(RANK) for f in RANKS}, **{f: u(RATIO) for f in RATIOS},
    **{f: u(MONEY_FINANCIAL, evidence="TM: trillions against a ~218 billion USD marketCap, so financialCurrency (JPY)") for f in STATEMENT_MONEY},
    "firstTradeDateMilliseconds": u(DATETIME, EPOCH_MS),
    "dividendYield": u(RATIO, PERCENT, evidence="dividendRate / regularMarketPrice x 100 = dividendYield (KO)"),
    "yield": u(RATIO, evidence="yield x 100 = dividendYield (SPY, QQQ)"),
    "fiveYearAvgDividendYield": u(RATIO, PERCENT),
    "trailingAnnualDividendYield": u(RATIO, evidence="trailingAnnualDividendRate / regularMarketPreviousClose = trailingAnnualDividendYield (KO)"),
    "trailingAnnualDividendRate": u(PER_SHARE_FINANCIAL, evidence="TM: 95.0 against a 6.27 USD dividendRate, so the reporting currency (JPY)"),
    "dividendRate": u(PER_SHARE_QUOTE, evidence="dividendRate / regularMarketPrice x 100 = dividendYield (TM, in USD)"),
    "payoutRatio": u(RATIO, evidence="trailingAnnualDividendRate / trailingEps = payoutRatio (KO)"),
    "fiftyTwoWeekChangePercent": u(RATIO, PERCENT, evidence="52WeekChange x 100 = fiftyTwoWeekChangePercent on a stock (AAPL)"),
    "52WeekChange": u(RATIO, evidence="52WeekChange x 100 = fiftyTwoWeekChangePercent on a stock, and equal to it on an index (^GSPC)",
                      by_quote_type={"INDEX": PERCENT}),
    "regularMarketChangePercent": u(RATIO, PERCENT, evidence="regularMarketChange / regularMarketPreviousClose x 100 (AAPL)"),
    "postMarketChangePercent": u(RATIO, PERCENT, evidence="postMarketChange / regularMarketPrice x 100 (AAPL)"),
    "preMarketChangePercent": u(RATIO, PERCENT),
    "fulldayChangePercent": u(RATIO, PERCENT, evidence="fulldayChange / regularMarketPreviousClose x 100 (AAPL)"),
    "fiftyDayAverageChangePercent": u(RATIO, evidence="fiftyDayAverageChange / fiftyDayAverage (AAPL)"),
    "twoHundredDayAverageChangePercent": u(RATIO, evidence="twoHundredDayAverageChange / twoHundredDayAverage (AAPL)"),
    "fiftyTwoWeekHighChangePercent": u(RATIO, evidence="fiftyTwoWeekHighChange / fiftyTwoWeekHigh (AAPL)"),
    "fiftyTwoWeekLowChangePercent": u(RATIO, evidence="fiftyTwoWeekLowChange / fiftyTwoWeekLow (AAPL)"),
    "debtToEquity": u(RATIO, PERCENT, evidence="totalDebt / total equity including minority interest x 100 = debtToEquity (KO)"),
    "sharesPercentSharesOut": u(RATIO, evidence="sharesShort / sharesOutstanding (AAPL)"),
    "profitMargins": u(RATIO, evidence="netIncomeToCommon / totalRevenue (AAPL)"),
    "grossMargins": u(RATIO, evidence="grossProfits / totalRevenue (AAPL)"),
    "ebitdaMargins": u(RATIO, evidence="ebitda / totalRevenue (AAPL)"),
    "netExpenseRatio": u(RATIO, PERCENT, evidence="netExpenseRatio = annualReportExpenseRatio x 100 (VFIAX)"),
    "ytdReturn": u(RATIO, PERCENT),
    "trailingThreeMonthReturns": u(RATIO, PERCENT),
    "trailingThreeMonthNavReturns": u(RATIO, PERCENT),
    "volume24HrMarketCapPercent": u(RATIO, evidence="volume24Hr / marketCap (BTC-USD)"),
    "marketCap": u(MONEY_QUOTE, evidence="regularMarketPrice x sharesOutstanding = marketCap (TM, in USD)"),
    "nonDilutedMarketCap": u(MONEY_QUOTE),
    "enterpriseValue": u(MONEY_FINANCIAL, evidence="enterpriseValue / totalRevenue = enterpriseToRevenue with both in JPY (TM)"),
    "netAssets": u(MONEY_QUOTE), "totalAssets": u(MONEY_QUOTE), "fullyDilutedValue": u(MONEY_QUOTE),
    "volume24Hr": u(UNVERIFIED), "volumeAllCurrencies": u(UNVERIFIED),
    "trailingEps": u(PER_SHARE_QUOTE, evidence="regularMarketPrice / trailingEps = trailingPE (TM, in USD)"),
    "epsTrailingTwelveMonths": u(PER_SHARE_QUOTE, evidence="equal to trailingEps (TM)"),
    "forwardEps": u(PER_SHARE_QUOTE, evidence="regularMarketPrice / forwardEps = forwardPE (TM, in USD)"),
    "epsForward": u(PER_SHARE_QUOTE, evidence="equal to forwardEps (TM)"),
    "epsCurrentYear": u(PER_SHARE_QUOTE, evidence="regularMarketPrice / epsCurrentYear = priceEpsCurrentYear (AAPL)"),
    "priceEpsCurrentYear": u(MULTIPLE),
    "bookValue": u(PER_SHARE_QUOTE, evidence="regularMarketPrice / bookValue = priceToBook (TM)"),
    "priceToBook": u(MULTIPLE),
    "revenuePerShare": u(PER_SHARE_FINANCIAL, evidence="TM: 2530 against a ~184 USD price, so the reporting currency (JPY)"),
    "totalCashPerShare": u(PER_SHARE_FINANCIAL, evidence="TM: 704.6 against a ~184 USD price, so the reporting currency (JPY)"),
}
# Fields whose source formula divides a quote-currency value by a reporting-currency one: meaningless when the two differ (an ADR).
CROSS_CURRENCY = ("priceToSalesTrailing12Months", "trailingAnnualDividendYield")
SOURCE_TIMES = ("regularMarketTime", "postMarketTime", "preMarketTime")

QUOTE_FIELDS = ("symbol", "shortName", "quoteType", "currency", "financialCurrency", "marketState", "exchange", "regularMarketPrice",
                "regularMarketChange", "regularMarketChangePercent", "regularMarketTime", "regularMarketPreviousClose", "regularMarketOpen",
                "regularMarketDayHigh", "regularMarketDayLow", "regularMarketVolume", "postMarketPrice", "postMarketChangePercent", "postMarketTime",
                "preMarketPrice", "preMarketTime", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyTwoWeekChangePercent", "marketCap", "sharesOutstanding",
                "trailingPE", "forwardPE", "trailingEps", "forwardEps", "dividendYield", "dividendRate", "exDividendDate", "beta")
PROFILE_FIELDS = ("symbol", "longName", "quoteType", "currency", "financialCurrency", "sector", "industry", "country", "city", "website",
                  "fullTimeEmployees", "longBusinessSummary", "auditRisk", "boardRisk", "compensationRisk", "shareHolderRightsRisk", "overallRisk",
                  "heldPercentInsiders", "heldPercentInstitutions", "lastFiscalYearEnd", "mostRecentQuarter")

ASSEMBLED = ("This response is assembled from several Yahoo endpoints, so its fields do not share one time; as_of gives each source time it carries, "
             "and observed_at is when this CLI received it.")
SIBLING = "quote and company profile read this same response and each saves all of it, so result.json holds the other's fields too."
RISK = "auditRisk, boardRisk, compensationRisk, shareHolderRightsRisk and overallRisk are ISS governance deciles, 1-10 relative to index and region, 1 the lowest relative risk."


def info(ticker, args, context):
    """The info response, with its currencies, quote type and source times recorded; a mixed-currency field is flagged when the two currencies differ."""
    data = ticker.get_info() or {}
    if data.get("quoteType") == "NONE":
        raise Failure(f"Yahoo knows {data.get('symbol')} but has no quote for it (quoteType NONE), as for a delisted symbol.",
                      "Check the symbol with `search`; a renamed or delisted company may trade under another symbol.", code="no_data")
    context.currency, context.financial_currency = data.get("currency"), data.get("financialCurrency")
    context.quote_type = data.get("quoteType")
    if data.get("marketState") is not None:
        context.as_of["market_state"] = data["marketState"]
    for field in SOURCE_TIMES:
        if data.get(field):
            context.as_of[field] = converted(data[field], EPOCH)
    if context.currency and context.financial_currency and context.currency != context.financial_currency:
        present = [f for f in CROSS_CURRENCY if data.get(f) is not None]
        if present:
            context.warn("cross_currency_fields", f"{', '.join(present)} divide a {context.currency} value by a {context.financial_currency} one here; do not use them.")
    return data
