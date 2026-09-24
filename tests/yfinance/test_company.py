import pytest


def test_financial_periods_and_native_line_items_keep_missing_values(cli):
    payload = {"timeseries": {"result": [{"meta": {"type": ["annualTotalRevenue"]}, "timestamp": [1703980800, 1735603200], "annualTotalRevenue": [{"asOfDate": "2023-12-31", "reportedValue": {"raw": 0}}, {"asOfDate": "2024-12-31", "reportedValue": {"raw": 120}}]}, {"meta": {"type": ["annualNetIncome"]}, "timestamp": [1735603200], "annualNetIncome": [{"asOfDate": "2024-12-31", "reportedValue": {"raw": 30}}]}], "error": None}}
    proc, doc = cli("financials", "income", "AAPL", "--fields", "TotalRevenue,NetIncome", "--periods", "2", routes=[{"path": "/timeseries/AAPL", "json": payload}] + [r for r in info_routes() if "timeseries" not in r["path"]])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    r = doc["results"][0]
    assert r["data"]["columns"] == ["TotalRevenue", "NetIncome"]
    assert r["data"]["index"] == ["2024-12-31", "2023-12-31"]
    assert r["data"]["data"] == [[120, 30], [0, None]]
    assert r["context"]["currency"] == "USD", "the statement currency is looked up rather than declined"
    assert r["context"]["quote_currency"] == "USD"


def info_routes():
    return [{"path": "/quoteSummary/AAPL", "json": {"quoteSummary": {"result": [{"assetProfile": {"sector": "Technology", "fullTimeEmployees": 10}, "financialData": {"financialCurrency": "USD"}}], "error": None}}}, {"path": "/v7/finance/quote", "json": {"quoteResponse": {"result": [{"symbol": "AAPL", "currency": "USD", "regularMarketPrice": 100, "marketCap": 9007199254740993}], "error": None}}}, {"path": "/timeseries/AAPL", "json": {"timeseries": {"result": [], "error": None}}}]


@pytest.mark.parametrize("group,leaf,fields,expected", [("company", "profile", "sector,fullTimeEmployees", {"sector": "Technology", "fullTimeEmployees": 10}), ("prices", "quote", "regularMarketPrice,marketCap", {"regularMarketPrice": 100, "marketCap": 9007199254740993})])
def test_profile_and_quote_query_real_info_and_select_fields(cli, group, leaf, fields, expected):
    proc, doc = cli(group, leaf, "AAPL", "--fields", fields, routes=info_routes())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"] == expected
    assert doc["results"][0]["context"]["currency"] == "USD"


@pytest.mark.parametrize("leaf,module,payload,index,column,value", [
    ("recommendations", "recommendationTrend", {"trend": [{"period": "0m", "strongBuy": 7}]}, 0, "strongBuy", 7),
    ("summary", "recommendationTrend", {"trend": [{"period": "0m", "strongBuy": 7}]}, 0, "strongBuy", 7),
    ("upgrades", "upgradeDowngradeHistory", {"history": [{"epochGradeDate": 1704067200, "firm": "Example", "toGrade": "Buy", "fromGrade": "Hold", "action": "up"}]}, "2024-01-01", "ToGrade", "Buy"),
    ("earnings-estimate", "earningsTrend", {"trend": [{"period": "0q", "earningsEstimate": {"avg": {"raw": 2.5}, "earningsCurrency": "USD"}}]}, "0q", "avg", 2.5),
    ("revenue-estimate", "earningsTrend", {"trend": [{"period": "0q", "revenueEstimate": {"avg": {"raw": 200}, "revenueCurrency": "USD"}}]}, "0q", "avg", 200),
    ("trend", "earningsTrend", {"trend": [{"period": "0q", "epsTrend": {"current": {"raw": 2.5}}}]}, "0q", "current", 2.5),
    ("revisions", "earningsTrend", {"trend": [{"period": "0q", "epsRevisions": {"upLast7days": {"raw": 0}}}]}, "0q", "upLast7days", 0),
    ("history", "earningsHistory", {"history": [{"quarter": {"fmt": "2024-03-31"}, "epsActual": {"raw": 3}}]}, "2024-03-31", "epsActual", 3),
])
def test_analyst_datasets_parse_yahoo_modules(cli, leaf, module, payload, index, column, value):
    proc, doc = cli("analysts", leaf, "AAPL", "--fields", column, routes=[{"path": "/quoteSummary/AAPL", "params": {"modules": module}, "json": {"quoteSummary": {"result": [{module: payload}]}}}])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["index"] == [index]
    assert doc["results"][0]["data"]["data"] == [[value]]


def test_holder_breakdown_preserves_both_axis_names(cli):
    proc, doc = cli("holders", "major", "AAPL", routes=[{"path": "/quoteSummary/AAPL", "json": {"quoteSummary": {"result": [{"majorHoldersBreakdown": {"maxAge": 1, "insidersPercentHeld": 0.025, "institutionsPercentHeld": 0.75}}]}}}])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    table = doc["results"][0]["data"]
    assert table["index"] == ["insidersPercentHeld", "institutionsPercentHeld"]
    assert table["column_names"] == ["Breakdown"]
    assert table["data"] == [[0.025], [0.75]]


def fund_routes():
    return [{"path": "/quoteSummary/SPY", "json": {"quoteSummary": {"result": [{"quoteType": {"quoteType": "ETF"}, "summaryProfile": {"longBusinessSummary": "Tracks an index."}, "topHoldings": {"holdings": [{"symbol": "AAPL", "holdingName": "Apple", "holdingPercent": 0.071}], "stockPosition": {"raw": 0.99}, "sectorWeightings": [{"technology": 0.3}], "bondRatings": [{"aaa": 0.1}]}, "fundProfile": {"categoryName": "Large Blend", "family": "Example", "legalType": "Exchange Traded Fund"}}]}}}]


def test_fund_holdings_preserve_reported_fraction_and_ticker(cli):
    proc, doc = cli("fund", "holdings", "SPY", routes=fund_routes())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["index"] == ["AAPL"]
    assert doc["results"][0]["data"]["data"] == [["Apple", 0.071]]


def option_routes():
    contract = {"contractSymbol": "AAPL240119C00100000", "lastTradeDate": 1704205800, "strike": 100, "lastPrice": 2, "bid": 0, "ask": 2.1, "volume": 0, "openInterest": 20, "impliedVolatility": 0.2, "inTheMoney": True, "contractSize": "REGULAR", "currency": "USD"}
    return [{"path": "/v7/finance/options/AAPL", "json": {"optionChain": {"result": [{"expirationDates": [1705622400], "quote": {"symbol": "AAPL", "regularMarketPrice": 100}, "options": [{"calls": [contract], "puts": []}]}], "error": None}}}]


def test_options_expiration_then_selected_side_and_fields(cli):
    proc, doc = cli("options", "expirations", "AAPL", routes=option_routes())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    expiration = doc["results"][0]["data"][0]
    assert expiration == "2024-01-19"
    proc, doc = cli("options", "chain", "AAPL", "--date", expiration, "--side", "calls", "--fields", "contractSymbol,lastTradeDate,bid", routes=option_routes())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["calls"]["data"] == [["AAPL240119C00100000", "2024-01-02T14:30:00+00:00", 0]]
    assert "puts" not in doc["results"][0]["data"]


@pytest.mark.parametrize("leaf,payload,fields,expected", [
    ("news", {"data": {"tickerStream": {"stream": [{"id": "story-1", "content": {"title": "Quarterly result"}}, {"ad": ["sponsored"]}]}}}, "id", [{"id": "story-1"}]),
    ("filings", {"quoteSummary": {"result": [{"secFilings": {"filings": [{"date": "2024-01-01", "epochDate": 1704067200, "type": "10-K", "title": "Annual", "edgarUrl": "https://www.sec.gov/example", "exhibits": []}]}}]}}, "type", [{"type": "10-K"}]),
])
def test_company_news_and_filing_links(cli, leaf, payload, fields, expected):
    path = "/xhr/ncp" if leaf == "news" else "/quoteSummary/AAPL"
    proc, doc = cli("company", leaf, "AAPL", "--fields", fields, routes=[{"path": path, "json": payload}])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"] == expected


def test_shares_full_preserves_integer_series(cli):
    routes = [{"path": "/v8/finance/chart/AAPL", "json": {"chart": {"result": [{"meta": {"exchangeTimezoneName": "America/New_York"}}], "error": None}}}, {"path": "/timeseries/AAPL", "json": {"timeseries": {"result": [{"timestamp": [1704067200], "shares_out": [9007199254740993]}]}}}]
    proc, doc = cli("company", "shares", "AAPL", "--start", "2024-01-01", "--end", "2024-02-01", routes=routes)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["data"] == [[9007199254740993]]
    assert doc["results"][0]["data"]["index"] == ["2024-01-01T00:00:00-05:00"]





def test_valuation_distinguishes_current_and_periods(cli):
    payload = {"timeseries": {"result": [{"meta": {"type": ["trailingPeRatio"]}, "trailingPeRatio": [{"asOfDate": "2025-01-01", "reportedValue": {"raw": 30}}]}, {"meta": {"type": ["quarterlyPeRatio"]}, "quarterlyPeRatio": [{"asOfDate": "2024-12-31", "reportedValue": {"raw": 25}}]}]}}
    proc, doc = cli("financials", "valuation", "AAPL", "--periods", "1", "--fields", "Trailing P/E", routes=[{"path": "/timeseries/AAPL", "json": payload}])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["index"] == ["Current", "12/31/2024"]
    assert doc["results"][0]["data"]["data"] == [[30], [25]]


def test_empty_option_sides_are_empty_not_success(cli):
    routes = [{"path": "/v7/finance/options/AAPL", "json": {"optionChain": {"result": [{"expirationDates": [1705622400], "quote": {}, "options": [{"calls": [], "puts": []}]}]}}}]
    proc, doc = cli("options", "chain", "AAPL", routes=routes)
    assert proc.returncode == 7, proc.stdout + proc.stderr
    assert doc["status"] == "empty"
    assert doc["results"][0]["warnings"]


@pytest.mark.parametrize("leaf,expected", [("overview", {"categoryName": "Large Blend", "family": "Example", "legalType": "Exchange Traded Fund"}), ("description", "Tracks an index."), ("sector-weights", {"technology": 0.3})])
def test_remaining_fund_dict_datasets(cli, leaf, expected):
    proc, doc = cli("fund", leaf, "SPY", routes=fund_routes())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"] == expected


@pytest.mark.parametrize("leaf,field", [("equity", "SPY"), ("operations", "SPY"), ("asset-classes", "stockPosition")])
def test_fund_numeric_datasets_keep_native_missing_or_fraction(cli, leaf, field):
    proc, doc = cli("fund", leaf, "SPY", "--fields", field, routes=fund_routes())
    assert proc.returncode == (0 if leaf == "asset-classes" else 7), proc.stdout + proc.stderr
    if leaf != "asset-classes":
        assert doc["status"] == "empty"
        assert doc["results"][0]["warnings"]
    data = doc["results"][0]["data"]
    if leaf == "asset-classes":
        assert data == {"stockPosition": 0.99}
    else:
        assert data["data"] and all(row == [None] for row in data["data"])


@pytest.mark.parametrize("leaf,item,frequency,prefix", [("balance", "TotalAssets", "quarterly", "quarterly"), ("cashflow", "OperatingCashFlow", "trailing", "trailing"), ("income", "TotalRevenue", "quarterly", "quarterly")])
def test_statement_purpose_and_frequency_are_applied(cli, leaf, item, frequency, prefix):
    payload = {"timeseries": {"result": [{"timestamp": [1735603200], prefix + item: [{"asOfDate": "2024-12-31", "reportedValue": {"raw": 99}}]}]}}
    routes = [{"path": "/timeseries/AAPL", "json": payload}] + [r for r in info_routes() if "timeseries" not in r["path"]]
    proc, doc = cli("financials", leaf, "AAPL", "--frequency", frequency, "--fields", item, routes=routes)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["columns"] == [item]
    assert doc["results"][0]["data"]["data"] == [[99]]


@pytest.mark.parametrize("leaf,module,field", [("institutional", "institutionOwnership", "Holder"), ("fund", "fundOwnership", "Holder"), ("insider-transactions", "insiderTransactions", "Insider"), ("insider-roster", "insiderHolders", "Name")])
def test_holder_list_datasets_have_reusable_fields(cli, leaf, module, field):
    payloads = {"institutionOwnership": {"ownershipList": [{"maxAge": 1, "reportDate": 1704067200, "organization": "Example", "position": 123, "value": 246}]}, "fundOwnership": {"ownershipList": [{"maxAge": 1, "reportDate": 1704067200, "organization": "Example", "position": 123, "value": 246}]}, "insiderTransactions": {"transactions": [{"maxAge": 1, "startDate": 1704067200, "filerName": "Example", "shares": 123}]}, "insiderHolders": {"holders": [{"maxAge": 1, "name": "Example", "relation": "Officer", "url": "https://example.com", "transactionDescription": "Purchase"}]}}
    proc, doc = cli("holders", leaf, "AAPL", "--fields", field, routes=[{"path": "/quoteSummary/AAPL", "json": {"quoteSummary": {"result": [{module: payloads[module]}]}}}])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["data"] == [["Example"]]


def test_insider_purchases_preserves_nullable_count(cli):
    proc, doc = cli("holders", "insider-purchases", "AAPL", "--fields", "Shares,Trans", "--limit", "1", routes=[{"path": "/quoteSummary/AAPL", "json": {"quoteSummary": {"result": [{"netSharePurchaseActivity": {"period": "6m", "buyInfoShares": 0, "buyInfoCount": 0}}]}}}])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["data"] == [[0, 0]]


def test_analyst_targets_and_growth(cli):
    routes = [{"path": "/quoteSummary/AAPL", "params": {"modules": "financialData"}, "json": {"quoteSummary": {"result": [{"financialData": {"targetMeanPrice": 120, "currentPrice": 100}}]}}}]
    proc, doc = cli("analysts", "targets", "AAPL", routes=routes)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"] == {"mean": 120, "current": 100}
    routes = [{"path": "/quoteSummary/AAPL", "params": {"modules": "earningsTrend"}, "json": {"quoteSummary": {"result": [{"earningsTrend": {"trend": [{"period": "0q", "growth": {"raw": 0.2}}]}}]}}}, {"path": "/quoteSummary/AAPL", "params": {"modules": "industryTrend,sectorTrend,indexTrend"}, "json": {"quoteSummary": {"result": [{"industryTrend": {"estimates": [{"period": "0q", "growth": 0.1}]}}]}}}]
    proc, doc = cli("analysts", "growth", "AAPL", "--fields", "stockTrend,industryTrend", routes=routes)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["data"] == [[0.2, 0.1]]
