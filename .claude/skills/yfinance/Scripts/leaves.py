"""One declaration per leaf: what it answers, how much of it a first call returns, and the contracts a value cannot be read without.

Leaf knowledge used to live in three places — the parser's if-chain, the adapter's if-chain and a COMMANDS dict — so a
recovery sentence could name a narrowing the leaf does not have. Here selection, recovery and schema all read the same
declaration, and a test fails when a parser leaf has none.

`units` carries scale and direction per field instead of prose, because a warning list only protects the fields someone
thought to list: the fund multiples below were all found inverted, so a fund field nobody probed is suspect too, and a
reader who sees the contract beside the value generalises where a reader who memorised six warnings does not.
"""

RATE = {"scale": "ratio", "kind": "rate"}  # 0.0452 means 4.52%
PERCENT = {"scale": "percent", "kind": "rate"}  # 33.33 means 33.33%
WEIGHT = {"scale": "ratio", "kind": "weight"}
CURRENCY = {"kind": "currency"}
MULTIPLE = {"kind": "multiple"}
COUNT = {"kind": "count"}
SHARES = {"kind": "shares"}


class Leaf:
    """A leaf's contract. `recent` is the one field that cannot be guessed: it says the source publishes oldest first,
    so a limit has to keep the tail. Declaring it per leaf rather than per group is not fussiness — measured, the
    direction differs inside `analysts` and inside `calendar`, and a single flip would silently break the other half."""

    def __init__(self, group, name, purpose, *, limit=None, fields=(), recent=False, date_field=None, narrow=(),
                 units=None, interpretation=None, limits=None, gotchas=(), conditions=(), sliceable=True, shares_info=False):
        self.group, self.name, self.purpose = group, name, purpose
        self.limit, self.fields, self.recent, self.date_field = limit, tuple(fields), recent, date_field
        self.narrow, self.gotchas, self.conditions = tuple(narrow), tuple(gotchas), tuple(conditions)
        self.units, self.interpretation, self.limits = units or {}, interpretation or {}, limits or {}
        self.sliceable, self.shares_info = sliceable, shares_info

    @property
    def path(self):
        return self.group + (" " + self.name if self.name else "")

    def limit_keeps(self):
        return "the newest rows of a series the source publishes oldest first" if self.recent else "the first rows in source order"


LEAVES = {}


def leaf(group, name, purpose, **spec):
    LEAVES[group, name] = Leaf(group, name, purpose, **spec)


def get(group, name):
    return LEAVES.get((group, name))


def effective_limit(args, item):
    """The row count in force: an explicit --limit, else this leaf's own default window.

    Adapters that pass a count upstream need the same number local selection will use, or the window a caller sees is
    cut from a batch that was never sized for it.
    """
    explicit = getattr(args, "limit", None)
    return explicit if explicit is not None else (item.limit if item else None)


# ---- shared interpretation contracts -----------------------------------------------------------------------------

NATIVE_ORDER = "Rows are returned in the source's own order; the coverage field names which end a limit kept."
STATEMENT_DATES = "Column labels are fiscal period end dates, not announcement dates."
QUOTE_TIME = "regularMarketTime is when the market last priced this instrument; observed_at is when this CLI received the response. After the close they differ by hours."

# ---- search ------------------------------------------------------------------------------------------------------

leaf("search", "", "Find instrument candidates by name, symbol or keyword.",
     limit=10, narrow=["--limit", "--type", "--dataset"],
     interpretation={"identity": "Candidates are search matches, not a confirmed identity: an equity, its depositary receipt and a similarly named fund appear together.",
                     "coverage": "Only the first Lookup page is available; a symbol absent here is not proof it does not exist."},
     gotchas=["--type filters --dataset quotes only; the other datasets ignore it."])

# ---- prices ------------------------------------------------------------------------------------------------------

QUOTE_FIELDS = ("symbol", "shortName", "quoteType", "currency", "financialCurrency", "marketState", "exchange", "fullExchangeName", "exchangeTimezoneName",
                "regularMarketPrice", "regularMarketChange", "regularMarketChangePercent", "regularMarketTime", "regularMarketOpen", "regularMarketDayHigh",
                "regularMarketDayLow", "regularMarketPreviousClose", "regularMarketVolume", "bid", "ask", "bidSize", "askSize",
                "postMarketPrice", "postMarketChangePercent", "postMarketTime", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyTwoWeekChangePercent",
                "fiftyDayAverage", "twoHundredDayAverage", "averageDailyVolume10Day", "averageDailyVolume3Month", "marketCap", "sharesOutstanding",
                "trailingPE", "forwardPE", "epsTrailingTwelveMonths", "dividendYield", "dividendRate", "exDividendDate", "beta")

PROFILE_FIELDS = ("symbol", "longName", "quoteType", "currency", "financialCurrency", "sector", "sectorKey", "industry", "industryKey",
                  "country", "state", "city", "address1", "zip", "phone", "website", "irWebsite", "fullTimeEmployees", "longBusinessSummary",
                  "auditRisk", "boardRisk", "compensationRisk", "shareHolderRightsRisk", "overallRisk", "governanceEpochDate",
                  "heldPercentInsiders", "heldPercentInstitutions", "lastFiscalYearEnd", "mostRecentQuarter", "lastSplitDate", "lastSplitFactor")

# 성진: 여기 있는 것은 전부 값만 보고는 판정할 수 없는 스케일이다. marketCap이 통화라는 것처럼 이름이 이미 말하는
# 사실은 싣지 않는다 — 그런 항목이 표를 키우면 정작 판정 불가능한 항목이 그 안에 묻힌다.
# 첫 세 줄이 같은 리프 안의 100배 충돌이다(실측 AAPL: dividendYield 0.32 = 0.32%인데
# trailingAnnualDividendYield 0.0031 = 0.31%, fiftyTwoWeekChangePercent 31.26 옆에 52WeekChange 0.3126).
INFO_UNITS = {"dividendYield": PERCENT, "fiveYearAvgDividendYield": PERCENT, "trailingAnnualDividendYield": RATE,
              "fiftyTwoWeekChangePercent": PERCENT, "52WeekChange": RATE, "SandP52WeekChange": RATE,
              "regularMarketChangePercent": PERCENT, "postMarketChangePercent": PERCENT, "debtToEquity": PERCENT,
              "payoutRatio": RATE, "heldPercentInsiders": RATE, "heldPercentInstitutions": RATE,
              "profitMargins": RATE, "grossMargins": RATE, "operatingMargins": RATE, "ebitdaMargins": RATE,
              "revenueGrowth": RATE, "earningsGrowth": RATE, "earningsQuarterlyGrowth": RATE,
              "returnOnAssets": RATE, "returnOnEquity": RATE,
              "shortPercentOfFloat": RATE, "sharesPercentSharesOut": RATE}

CURRENCY_SPLIT = "currency prices this instrument's quote; financialCurrency is what its financial statements are reported in. They differ for foreign listings and ADRs (measured: TM quotes in USD and reports in JPY), so a ratio mixing a price with a statement figure is wrong by the exchange rate."

leaf("prices", "quote", "Current price, trading session and market-capitalisation fields for one instrument.",
     fields=QUOTE_FIELDS, narrow=["--fields"], units=INFO_UNITS,
     interpretation={"sibling": "company profile selects the business side of this same assembled response; --from reuses the observation rather than requesting it again.",
                     "timing": QUOTE_TIME, "currency": CURRENCY_SPLIT,
                     "assembly": "yfinance assembles this response from several endpoints, so its fields do not all share one timestamp; where a field has its own time field, that one governs."},
     gotchas=["An instrument that did not trade in the current session still returns regularMarket fields from the last session it did."])

leaf("prices", "history", "OHLCV bars, dividends and splits over a date range or relative period.",
     recent=True, date_field="index", narrow=["--fields", "--limit", "--period", "--start/--end", "--interval"],
     conditions=["start", "end"],
     interpretation={"dates": "start is inclusive and end is exclusive. A naive date is read in the exchange's timezone.",
                     "adjustment": "--adjust decides what Close means: none leaves OHLC as supplied and adds Adj Close, auto scales OHLC for splits and dividends, back keeps Close raw and scales OHL. Adding dividends to an already adjusted return counts them twice.",
                     "repair": "--repair is a transformation with its own limits, not proof that a value equals the original trade."},
     limits={"1m": "8 days per request", "2m/5m/15m/30m/90m": "the range must fall within the last 60 days",
             "60m/1h": "no range limit measured; a year of 1h bars is far above the default budget",
             "note": "These come from Yahoo's own refusals; a request past them fails upstream rather than returning less."},
     gotchas=["A 30m request is resampled from 15m, and Yahoo's refusal message for it names 15m rather than the interval that was asked for."])

leaf("prices", "actions", "Dividends, splits and capital gains within a date range or relative period.",
     recent=True, date_field="index", narrow=["--limit", "--period", "--start/--end"], conditions=["start", "end"],
     interpretation={"dates": "start is inclusive and end is exclusive; rows appear only on dates carrying an action.",
                     "empty": "The default period is one month, in which most instruments have no action at all. An empty return here is normal and is not evidence that the instrument pays nothing."})

# ---- company -----------------------------------------------------------------------------------------------------

leaf("company", "profile", "Business description, sector, governance risk and headquarters for one company.",
     fields=PROFILE_FIELDS, narrow=["--fields"], units=INFO_UNITS,
     interpretation={"sibling": "prices quote selects the price side of this same assembled response; --from reuses the observation rather than requesting it again.",
                     "currency": CURRENCY_SPLIT,
                     "governance": "The risk fields are Yahoo's 1-10 decile ranks within the peer group, where 1 is the lowest measured risk; they are ranks, not scores out of ten."},
     gotchas=["companyOfficers and executiveTeam are omitted from the default projection because they are large; ask for them by name."])

leaf("company", "shares", "Shares outstanding as Yahoo observed it over a date range.",
     recent=True, date_field="index", narrow=["--limit", "--start/--end"],
     units={"value": SHARES},
     interpretation={"dates": "Each row is a Yahoo observation timestamp rounded to a whole day, not a filing or record date.",
                     "range": "An omitted --end means now and an omitted --start means about 18 months earlier."})

NEWS_FIELDS = ("content.title", "content.pubDate", "content.provider.displayName", "content.canonicalUrl.url", "content.summary")

leaf("company", "news", "Recent article and press-release entries referencing this company.",
     limit=10, fields=NEWS_FIELDS, narrow=["--fields", "--limit", "--tab"],
     interpretation={"payload": "Each entry nests its article under content, so a field path is dotted: content.title, content.provider.displayName.",
                     "not_the_article": "Entries locate sources; the text here is a summary, not the article. Read the article itself with a web reader."},
     gotchas=["The default projection leaves out thumbnail and storyline, which measured together as over half the payload.",
              "Entries are not strictly ordered by pubDate: measured, a later item carried a newer timestamp than an earlier one, so the first entry is not reliably the most recent."])

leaf("company", "filings", "SEC filing entries with their Yahoo EDGAR links.",
     limit=20, fields=("date", "type", "title", "edgarUrl"), date_field="date",
     narrow=["--fields", "--limit"],
     interpretation={"dates": "date is the filing date. Entries arrive newest first.",
                     "not_the_filing": "These are links and metadata. Read the original filing with the sec skill."},
     gotchas=["exhibits holds a link map per filing and measured as the majority of this payload; it is outside the default projection and has to be asked for by name."])

# ---- financials --------------------------------------------------------------------------------------------------

STATEMENT_INTERPRETATION = {
    "dates": STATEMENT_DATES,
    "currency": "The reported currency is in context.currency, read from the same company's financialCurrency. It can differ from the currency the share price is quoted in.",
    "orientation": "Rows are periods and columns are native line items, so --fields selects line items.",
    "scale": "One statement mixes measurements: a rate such as TaxRateForCalcs sits in the same row as a currency amount such as NormalizedEBITDA. The label is the only thing distinguishing them, so read a line item's name before comparing its magnitude to another's.",
}
STATEMENT_UNITS = {"TaxRateForCalcs": RATE, "TaxEffectOfUnusualItems": CURRENCY, "BasicEPS": {"kind": "per_share"}, "DilutedEPS": {"kind": "per_share"},
                   "BasicAverageShares": SHARES, "DilutedAverageShares": SHARES, "ShareIssued": SHARES, "OrdinarySharesNumber": SHARES, "TreasurySharesNumber": SHARES}

for _leaf, _what in [("income", "Income statement"), ("balance", "Balance sheet"), ("cashflow", "Cash flow statement")]:
    leaf("financials", _leaf, _what + " line items by fiscal period, as reported.",
         narrow=["--fields", "--periods", "--frequency"], units=STATEMENT_UNITS,
         interpretation=dict(STATEMENT_INTERPRETATION, frequency=("Balance sheet frequencies are yearly and quarterly only." if _leaf == "balance" else "trailing returns TTM, which is a rolling twelve months and not a completed fiscal period.")))

leaf("financials", "valuation", "Valuation multiples and market-size measures by period.",
     narrow=["--fields", "--periods", "--frequency"],
     units={"Market Cap": CURRENCY, "Enterprise Value": CURRENCY, "Trailing P/E": MULTIPLE, "Forward P/E": MULTIPLE,
            "PEG Ratio (5yr expected)": MULTIPLE, "Price/Sales": MULTIPLE, "Price/Book": MULTIPLE,
            "Enterprise Value/Revenue": MULTIPLE, "Enterprise Value/EBITDA": MULTIPLE},
     interpretation={"dates": "Labels other than Current are native period dates; Current is the latest trailing snapshot, not a completed fiscal period.",
                     "periods": "--periods is sent upstream here rather than applied locally; 0 returns Current only."})

# ---- analysts ----------------------------------------------------------------------------------------------------

leaf("analysts", "targets", "Current analyst price target range.", narrow=["--fields"],
     units={"current": CURRENCY, "high": CURRENCY, "low": CURRENCY, "mean": CURRENCY, "median": CURRENCY},
     interpretation={"currency": "Targets are in the quote currency.", "current": "current is the live price the targets are being compared against, not a target."})

leaf("analysts", "recommendations", "Analyst recommendation counts by month.", narrow=["--fields", "--limit"],
     units={"strongBuy": COUNT, "buy": COUNT, "hold": COUNT, "sell": COUNT, "strongSell": COUNT},
     interpretation={"periods": "period 0m is the current month and -1m, -2m, -3m are earlier months, so rows are relative, not dated."})

leaf("analysts", "summary", "Analyst recommendation summary by month.", narrow=["--fields", "--limit"],
     units={"strongBuy": COUNT, "buy": COUNT, "hold": COUNT, "sell": COUNT, "strongSell": COUNT},
     interpretation={"periods": "period 0m is the current month; earlier months are relative offsets."})

leaf("analysts", "upgrades", "Rating upgrade and downgrade actions with their firms and dates.",
     limit=20, date_field="index", narrow=["--fields", "--limit"],
     interpretation={"order": "Actions arrive newest first, so a limit keeps the most recent ones.",
                     "history": "The full history reaches back more than a decade; the default keeps one screen of the newest actions and coverage reports how many were received."})

leaf("analysts", "earnings-estimate", "EPS estimates for the current and next quarter and year.", narrow=["--fields"],
     units={"growth": RATE, "avg": {"kind": "per_share"}, "low": {"kind": "per_share"}, "high": {"kind": "per_share"},
            "yearAgoEps": {"kind": "per_share"}, "numberOfAnalysts": COUNT},
     interpretation={"periods": "0q, +1q, 0y and +1y are relative periods, not dates."})

leaf("analysts", "revenue-estimate", "Revenue estimates for the current and next quarter and year.", narrow=["--fields"],
     units={"growth": RATE, "avg": CURRENCY, "low": CURRENCY, "high": CURRENCY, "yearAgoRevenue": CURRENCY, "numberOfAnalysts": COUNT},
     interpretation={"periods": "0q, +1q, 0y and +1y are relative periods, not dates."})

leaf("analysts", "history", "Reported EPS against the estimate for past quarters.",
     recent=True, date_field="index", narrow=["--fields", "--limit"],
     units={"epsActual": {"kind": "per_share"}, "epsEstimate": {"kind": "per_share"}, "epsDifference": {"kind": "per_share"}, "surprisePercent": RATE},
     interpretation={"dates": "The index is the fiscal quarter end, not the announcement date.",
                     "surprise": "surprisePercent is a ratio despite its name: 0.0452 is a 4.52% surprise. calendar earnings reports the same measurement as Surprise(%) on a percent scale, so the two are 100x apart and must not be compared directly."})

leaf("analysts", "revisions", "Counts of upward and downward EPS estimate revisions.", narrow=["--fields"],
     units={"upLast7days": COUNT, "upLast30days": COUNT, "downLast7Days": COUNT, "downLast30days": COUNT},
     interpretation={"periods": "0q, +1q, 0y and +1y are relative periods.",
                     "counts": "These are analyst counts, not magnitudes; a revision's size is not reported here."})

leaf("analysts", "trend", "How the consensus EPS estimate moved over the last 90 days.", narrow=["--fields"],
     units={"current": {"kind": "per_share"}, "7daysAgo": {"kind": "per_share"}, "30daysAgo": {"kind": "per_share"},
            "60daysAgo": {"kind": "per_share"}, "90daysAgo": {"kind": "per_share"}},
     interpretation={"periods": "Rows are relative periods and columns are how long ago the estimate was current."})

leaf("analysts", "growth", "Expected growth for this instrument against its index.", narrow=["--fields"],
     units={"stockTrend": RATE, "indexTrend": RATE},
     interpretation={"periods": "0q, +1q, 0y, +1y and LTG are relative periods; LTG is a long-term annualised expectation."})

# ---- holders -----------------------------------------------------------------------------------------------------

leaf("holders", "major", "Insider and institutional ownership percentages for the whole company.", narrow=["--limit"],
     units={"insidersPercentHeld": RATE, "institutionsPercentHeld": RATE, "institutionsFloatPercentHeld": RATE, "institutionsCount": COUNT},
     interpretation={"float": "institutionsPercentHeld is of shares outstanding while institutionsFloatPercentHeld is of the float, so the second is the larger of the two."})

HOLDER_MIX = "Date Reported is when the position was filed, but Value is that share count priced at the current quote, not at the price on the reported date. Measured on AAPL, every row's Value divided by Shares gave the same live price while the filings were months old, so reading Value as a position's worth on its reported date is wrong by the price move since."

for _leaf, _what in [("institutional", "Institutional"), ("fund", "Mutual fund")]:
    leaf("holders", _leaf, _what + " holders with their reported share counts.",
         limit=20, date_field="Date Reported", narrow=["--fields", "--limit"],
         units={"pctHeld": RATE, "pctChange": RATE, "Shares": SHARES, "Value": dict(CURRENCY, as_of="current_quote")},
         interpretation={"mixed_times": HOLDER_MIX,
                         "coverage": "These are the largest reported holders, not every holder."})

leaf("holders", "insider-purchases", "Insider purchase and sale totals over the last six months.", narrow=["--fields"],
     units={"Shares": SHARES, "Trans": COUNT},
     interpretation={"rows": "The first column labels each row; % rows carry ratios while the others carry share counts, in the same column."})

leaf("holders", "insider-transactions", "Individual insider transactions with dates, roles and values.",
     limit=20, date_field="Start Date", narrow=["--fields", "--limit"],
     units={"Shares": SHARES, "Value": CURRENCY},
     interpretation={"order": "The index is a row number, so it says nothing about time; Start Date does, and measured it arrives newest first, so a limit keeps the most recent transactions.",
                     "value": "Value is absent for transactions that report no price, such as gifts and some awards; that is a missing price, not a zero-value transfer."})

leaf("holders", "insider-roster", "Insiders and the shares they hold directly.",
     limit=20, date_field="Latest Transaction Date", narrow=["--fields", "--limit"],
     units={"Shares Owned Directly": SHARES},
     interpretation={"direct_only": "Shares Owned Directly excludes indirect holdings through trusts and partnerships, so it understates total control.",
                     "dates": "Latest Transaction Date is that insider's most recent filing, so different rows are current as of different dates."})

# ---- fund --------------------------------------------------------------------------------------------------------

leaf("fund", "overview", "Fund family, category and legal type.", narrow=["--fields"])

# 성진: 반환값이 문자열 하나라 --fields도 --limit도 줄이지 못한다. 줄일 수 없는 리프는 줄이는 법을 선언하지 않는다 —
# 선언하면 fix가 그 인자를 권하고, 따라간 결과가 같은 크기로 다시 실패한다.
leaf("fund", "description", "The fund's own investment objective text.", narrow=(), sliceable=False,
     interpretation={"shape": "One text value. It cannot be narrowed by fields or rows; raise --max-chars or read the saved observation."})

leaf("fund", "holdings", "Largest reported holdings and their weights.",
     limit=20, narrow=["--fields", "--limit"], units={"Holding Percent": WEIGHT},
     interpretation={"coverage": "These are the top reported holdings only, so the weights do not sum to one and the rest of the portfolio is not described here."})

leaf("fund", "asset-classes", "Allocation across cash, stock, bond, preferred and convertible.", narrow=["--fields"],
     units={"cashPosition": WEIGHT, "stockPosition": WEIGHT, "bondPosition": WEIGHT, "preferredPosition": WEIGHT,
            "convertiblePosition": WEIGHT, "otherPosition": WEIGHT})

leaf("fund", "sector-weights", "Portfolio weight by sector.", narrow=["--fields"],
     units={"*": WEIGHT},
     interpretation={"keys": "Sector keys here use underscores (consumer_cyclical); market sector takes hyphenated keys (consumer-cyclical)."})

leaf("fund", "equity", "Valuation multiples and growth for the fund's equity holdings.", narrow=["--fields"],
     units={"Price/Earnings": dict(MULTIPLE, inverted=True), "Price/Book": dict(MULTIPLE, inverted=True),
            "Price/Sales": dict(MULTIPLE, inverted=True), "Price/Cashflow": dict(MULTIPLE, inverted=True),
            "Median Market Cap": CURRENCY, "3 Year Earnings Growth": RATE},
     interpretation={"inverted": "All four price multiples arrive as their reciprocals: the Price/Earnings row holds an earnings yield, so a P/E is 1 divided by the value. Measured across SPY, QQQ, VTI, IWM and VOO, the reciprocals matched each index's known multiple, so reporting the value as printed is wrong by that inversion."},
     gotchas=["The Category Average column is often empty, and where it is populated it has been observed equal to the fund's own value, so it cannot be relied on as a peer comparison."])

leaf("fund", "operations", "Expense ratio, turnover and reported net assets.", narrow=["--fields"],
     units={"Annual Report Expense Ratio": RATE, "Annual Holdings Turnover": RATE,
            "Total Net Assets": {"kind": "currency", "scale": "unverified"}},
     interpretation={"expense": "The expense ratio is a ratio, not a percent: 0.000945 is 0.0945%."},
     gotchas=["Total Net Assets has no declared unit and does not reconcile: SPY reported 513,975.7 here while the same fund's totalAssets was 811,937,038,336, so it is neither the raw amount nor that amount in millions. Cite it only with the fund's own reporting.",
              "The Category Average column has been observed holding an exact copy of the fund's own value, so a difference of zero there is not evidence of being at the peer average."])

# ---- options -----------------------------------------------------------------------------------------------------

leaf("options", "expirations", "Expiration dates with listed contracts for this underlying.", narrow=["--limit"],
     interpretation={"use": "Pass one of these to options chain --date; an omitted --date selects the nearest."})

leaf("options", "chain", "Option contracts for one expiration, by side.",
     limit=20, narrow=["--fields", "--limit", "--side", "--date"], conditions=["date"],
     units={"strike": CURRENCY, "lastPrice": CURRENCY, "bid": CURRENCY, "ask": CURRENCY, "change": CURRENCY,
            "percentChange": PERCENT, "impliedVolatility": RATE, "volume": COUNT, "openInterest": COUNT},
     interpretation={"sides": "calls and puts are selected separately and each is limited on its own, so a limit of 20 with --side both returns 20 of each.",
                     "staleness": "lastTradeDate is when that contract last traded, which for a thin strike can be days before now while bid and ask are current. A contract's lastPrice is only as recent as its lastTradeDate.",
                     "timezone": "lastTradeDate is UTC."},
     gotchas=["Contracts are ordered by strike, so a limit keeps the lowest strikes rather than the ones nearest the money."])

# ---- screen ------------------------------------------------------------------------------------------------------

leaf("screen", "presets", "Named screeners with the query each one actually runs.", narrow=["--filter", "--type"],
     interpretation={"name_is_not_the_condition": "Each entry carries the query it runs. Describe a preset's results by that query, not by its name: measured, small_cap_gainers screens for small capitalisation sorted by volume and contains no gain condition at all."})

leaf("screen", "fields", "Query fields available for the selected --type.", narrow=["--filter", "--field", "--type"])

leaf("screen", "values", "Enumerated values accepted by query fields of the selected --type.", narrow=["--filter", "--field", "--type"])

SCREEN_FIELDS = ("symbol", "shortName", "regularMarketPrice", "regularMarketChangePercent", "regularMarketVolume",
                 "marketCap", "trailingPE", "fiftyTwoWeekChangePercent", "averageAnalystRating", "fullExchangeName")

leaf("screen", "run", "Run a preset or a JSON query and return matching instruments.",
     limit=25, fields=SCREEN_FIELDS, narrow=["--fields", "--limit", "--query", "--preset", "--offset"],
     conditions=["offset", "limit", "sort"],
     units={"regularMarketChangePercent": PERCENT, "fiftyTwoWeekChangePercent": PERCENT, "marketCap": CURRENCY,
            "trailingPE": MULTIPLE, "regularMarketVolume": COUNT},
     interpretation={"query_scale": "A growth threshold in the query is in percentage points, while the same measurement in a quote is a ratio. Measured: BTWN quarterlyrevenuegrowth.quarterly 20 30 returned companies whose quote revenueGrowth was 0.242 and 0.28, and the same bounds written as 0.20 and 0.30 returned a different set entirely — companies growing a fifth of a percent. Neither call fails, so reusing an output ratio as a query bound screens for something a hundredfold smaller and returns a plausible list.",
                     "matches_not_a_census": "These are the rows matching the query, ordered by the sort field. They are not a verified census of a market, and total is the provider's own claim.",
                     "paging": "--offset continues a query rather than reading an immutable snapshot; rows can move between pages.",
                     "default_fields": "Each row carries far more fields than the default projection; --fields reaches them and --list-fields names them."},
     gotchas=["A preset's name does not state its condition. Describe results by the query that screen presets returns for it."])

# ---- market ------------------------------------------------------------------------------------------------------

leaf("market", "summary", "Benchmark index quotes for a market region.", narrow=["--fields", "--region"],
     interpretation={"shape": "A mapping keyed by exchange, so --fields selects exchanges rather than columns and there are no rows for --limit to cut."})

leaf("market", "sectors", "Sector keys accepted by market sector.", narrow=["--filter"],
     interpretation={"coverage": "These are the known Yahoo sector keys, not a live enumeration of what the source will accept today."})

REGION_INTERPRETATION = {
    "region": "--region takes only the country codes Yahoo actually serves for this dataset. The list is closed because unserved codes were measured returning the United States result with no warning, which is indistinguishable from a real answer.",
    "keys": "Sector keys are hyphenated (consumer-cyclical); fund sector-weights uses underscores.",
}
# 성진: 같은 값을 overview는 market_weight(밑줄), 구성종목 표는 "market weight"(공백)로 부른다. 한쪽만 선언하면
# 다른 쪽이 계약 없이 나간다. ytd return은 특히 위험하다 — 실측 raw 3.654가 원천 표기로 "365.40%"다.
DOMAIN_UNITS = {"market weight": WEIGHT, "market_weight": WEIGHT,
                "ytd return": RATE, "growth estimate": RATE}

REGION_GOTCHA = "Outside the United States the name column arrives null for every row, so a non-US region identifies companies by symbol only. That is a degraded answer, not an empty one."

leaf("market", "sector", "One sector's overview, industries, top companies, funds or research.",
     limit=20, narrow=["--fields", "--limit", "--dataset"], units=DOMAIN_UNITS,
     interpretation=REGION_INTERPRETATION, gotchas=[REGION_GOTCHA])

leaf("market", "industry", "One industry's overview, companies or research.",
     limit=20, narrow=["--fields", "--limit", "--dataset"], units=DOMAIN_UNITS,
     interpretation=REGION_INTERPRETATION, gotchas=[REGION_GOTCHA])

# ---- calendar ----------------------------------------------------------------------------------------------------

CALENDAR_DATES = "--start and --end are both inclusive. Yahoo's own range excludes the end date, so this CLI sends the day after --end; the conditions field reports whether the rows it returned actually fall inside the range you asked for."

leaf("calendar", "earnings", "Earnings events, market-wide over a date range or one company's history.",
     limit=12, date_field="Event Start Date", narrow=["--fields", "--limit", "--start/--end", "--offset"],
     conditions=["start", "end"],
     units={"Surprise(%)": PERCENT, "Marketcap": CURRENCY, "EPS Estimate": {"kind": "per_share"}, "Reported EPS": {"kind": "per_share"}},
     interpretation={"dates": CALENDAR_DATES,
                     "two_modes": "With a SYMBOL this returns that company's own earnings history and upcoming dates, paged by --limit and --offset with no date filter, newest first. Without one it returns market-wide US earnings inside the date range.",
                     "surprise": "Surprise(%) is on a percent scale: 33.33 means 33.33%. analysts history reports the same measurement as surprisePercent on a ratio scale, so the two are 100x apart.",
                     "zero_loss": "yfinance converts zero to null in the estimate, actual and surprise columns, so a null there can be a real zero and the distinction is already lost upstream of this CLI."})

leaf("calendar", "economic", "Scheduled economic releases over a date range.",
     limit=12, date_field="Event Time", narrow=["--fields", "--limit", "--start/--end", "--offset"],
     conditions=["start", "end"],
     interpretation={"dates": CALENDAR_DATES,
                     "scope": "The universe is not US-only; the Region column says which economy each row belongs to.",
                     "zero_loss": "yfinance converts zero to null in the numeric columns, so a null actual or expected can be a real zero."})

leaf("calendar", "ipo", "IPO listings, filings and amendments over a date range.",
     limit=12, date_field="Date", narrow=["--fields", "--limit", "--start/--end", "--offset"], conditions=["start", "end"],
     interpretation={"dates": "A row matches when any of its listing Date, Filing Date or Amended Date falls in the range, so a returned row's Date can sit outside it.",
                     "zero_loss": "yfinance converts zero to null in the price and share columns."},
     gotchas=["Because three different date fields can match, the range cannot be confirmed from the returned rows the way the other calendars' can; conditions reports it as unverified rather than claiming it was applied."])

leaf("calendar", "splits", "Split events payable over a date range.",
     limit=12, date_field="Payable On", narrow=["--fields", "--limit", "--start/--end", "--offset"],
     conditions=["start", "end"],
     interpretation={"dates": CALENDAR_DATES + " The date matched is the payable date, not the announcement or ex-date."})
