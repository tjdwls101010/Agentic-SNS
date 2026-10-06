"""Company, financials, analysts, holders, fund and options datasets read through yfinance into the long file: native field names kept, missing values kept missing, zeros kept zero, and the source's order kept.

Routes here are synthetic examples of each Yahoo module's shape; their literals are the expectation.
"""
import pytest

from conftest import recorded


def summary(symbol, module, payload, params=None):
    route = {"path": f"/quoteSummary/{symbol}", "json": {"quoteSummary": {"result": [{module: payload}], "error": None}}}
    if params:
        route["params"] = params
    return route


INFO = [summary("AAPL", "financialData", {"financialCurrency": "USD"}),
        {"path": "/v7/finance/quote", "json": {"quoteResponse": {"result": [{"symbol": "AAPL", "currency": "USD", "regularMarketPrice": 100, "marketCap": 9007199254740993}], "error": None}}},
        {"path": "/timeseries/AAPL", "params": {"type": "trailingPegRatio"}, "json": {"timeseries": {"result": [], "error": None}}}]


def test_statement_periods_keep_zero_and_missing_line_items(cli):
    payload = {"timeseries": {"result": [{"meta": {"type": ["annualTotalRevenue"]}, "timestamp": [1703980800, 1735603200],
                                          "annualTotalRevenue": [{"asOfDate": "2023-12-31", "reportedValue": {"raw": 0}}, {"asOfDate": "2024-12-31", "reportedValue": {"raw": 120}}]},
                                         {"meta": {"type": ["annualNetIncome"]}, "timestamp": [1735603200],
                                          "annualNetIncome": [{"asOfDate": "2024-12-31", "reportedValue": {"raw": 30}}]}], "error": None}}
    run = cli("financials", "income", "AAPL", routes=[{"path": "/timeseries/AAPL", "json": payload}] + INFO)
    assert run.code == 0, run
    rows = [(r["Date"][:10], r["TotalRevenue"], r["NetIncome"]) for r in run.rows]
    assert rows == [("2024-12-31", "120.0", "30.0"), ("2023-12-31", "0.0", "")], "newest first; zero kept, a missing item left empty"
    assert run.result()["financial_currency"] == "USD"


@pytest.mark.parametrize("kind,item,frequency,prefix", [("balance", "TotalAssets", "quarterly", "quarterly"), ("cashflow", "OperatingCashFlow", "trailing", "trailing"),
                                                        ("income", "TotalRevenue", "quarterly", "quarterly")])
def test_the_statement_and_frequency_asked_for_are_the_ones_read(cli, kind, item, frequency, prefix):
    payload = {"timeseries": {"result": [{"timestamp": [1735603200], prefix + item: [{"asOfDate": "2024-12-31", "reportedValue": {"raw": 99}}]}]}}
    run = cli("financials", kind, "AAPL", "--frequency", frequency, routes=[{"path": "/timeseries/AAPL", "json": payload}] + INFO)
    assert run.code == 0, run
    assert float(run.rows[0][item]) == 99


def test_a_balance_sheet_has_no_trailing_form(cli):
    run = cli("financials", "balance", "AAPL", "--frequency", "trailing", routes=[])
    assert run.code == 2 and "yearly, quarterly" in run.result()["error"]["message"], run


def test_valuation_keeps_current_apart_from_the_periods(cli):
    payload = {"timeseries": {"result": [{"meta": {"type": ["trailingPeRatio"]}, "trailingPeRatio": [{"asOfDate": "2025-01-01", "reportedValue": {"raw": 30}}]},
                                         {"meta": {"type": ["quarterlyPeRatio"]}, "quarterlyPeRatio": [{"asOfDate": "2024-12-31", "reportedValue": {"raw": 25}}]}]}}
    run = cli("financials", "valuation", "AAPL", "--periods", "1", routes=[{"path": "/timeseries/AAPL", "json": payload}] + INFO)
    assert run.code == 0, run
    assert [(r["Date"], r["Trailing P/E"]) for r in run.rows] == [("Current", "30.0"), ("12/31/2024", "25.0")]


def test_quote_and_profile_read_one_response_and_each_saves_all_of_it(cli):
    quote = cli("quote", "AAPL", routes=INFO)
    profile = cli("company", "profile", "AAPL", routes=INFO)
    assert quote.code == 0 and profile.code == 0, (quote, profile)
    assert quote.records[0]["data"]["marketCap"] == 9007199254740993
    assert profile.records[0]["data"]["marketCap"] == 9007199254740993, "the profile's file holds the quote's fields too"
    assert any("same response" in n for n in quote.doc["notes"])


@pytest.mark.parametrize("kind,module,payload,column,value", [
    ("recommendations", "recommendationTrend", {"trend": [{"period": "0m", "strongBuy": 7}]}, "strongBuy", "7"),
    ("eps-estimate", "earningsTrend", {"trend": [{"period": "0q", "earningsEstimate": {"avg": {"raw": 2.5}, "earningsCurrency": "USD"}}]}, "avg", "2.5"),
    ("revenue-estimate", "earningsTrend", {"trend": [{"period": "0q", "revenueEstimate": {"avg": {"raw": 200}, "revenueCurrency": "USD"}}]}, "avg", "200"),
    ("trend", "earningsTrend", {"trend": [{"period": "0q", "epsTrend": {"current": {"raw": 2.5}}}]}, "current", "2.5"),
    ("revisions", "earningsTrend", {"trend": [{"period": "0q", "epsRevisions": {"upLast7days": {"raw": 0}}}]}, "upLast7days", "0"),
    ("eps-history", "earningsHistory", {"history": [{"quarter": {"fmt": "2024-03-31"}, "epsActual": {"raw": 3}}]}, "epsActual", "3"),
])
def test_analyst_modules_keep_their_native_columns_and_zeros(cli, kind, module, payload, column, value):
    run = cli("analysts", kind, "AAPL", routes=[summary("AAPL", module, payload, {"modules": module})])
    assert run.code == 0, run
    assert run.rows[0][column].removesuffix(".0") == value


def test_analyst_targets_are_one_row_in_the_quote_currency(cli):
    routes = [summary("AAPL", "financialData", {"targetMeanPrice": 120, "currentPrice": 100}, {"modules": "financialData"}),
              {"path": "/v8/finance/chart/AAPL", "json": {"chart": {"result": [{"meta": {"currency": "USD", "exchangeTimezoneName": "America/New_York"}}], "error": None}}}]
    run = cli("analysts", "targets", "AAPL", routes=routes)
    assert run.code == 0, run
    assert (float(run.rows[0]["mean"]), float(run.rows[0]["current"])) == (120, 100)
    assert run.result()["currency"] == "USD" and run.receipt["units"]["mean"] == "per_share:quote"


def test_holder_breakdown_becomes_metric_rows_with_their_own_units(cli):
    routes = [summary("AAPL", "majorHoldersBreakdown", {"maxAge": 1, "insidersPercentHeld": 0.025, "institutionsPercentHeld": 0.75, "institutionsCount": 6000})]
    run = cli("holders", "major", "AAPL", routes=routes)
    assert run.code == 0, run
    rows = {r["metric"]: (float(r["value"]), r["unit"]) for r in run.rows}
    assert rows["insidersPercentHeld"] == (0.025, "ratio") and rows["institutionsCount"] == (6000, "count")


def test_insider_purchases_keep_a_zero_count_and_tell_percent_rows_from_share_rows(cli):
    routes = [summary("AAPL", "netSharePurchaseActivity", {"period": "6m", "buyInfoShares": 0, "buyInfoCount": 0, "buyPercentInsiderShares": 0.01})]
    run = cli("holders", "insider-purchases", "AAPL", routes=routes)
    assert run.code == 0, run
    purchases = {(r["metric"], r["source_column"]): (r["value"], r["unit"]) for r in run.rows}
    assert purchases["Purchases", "Shares"][1] == "shares" and float(purchases["Purchases", "Shares"][0]) == 0, "a zero count stays zero, not missing"
    assert purchases["Purchases", "Trans"][1] == "count" and float(purchases["Purchases", "Trans"][0]) == 0
    assert purchases["% Buy Shares", "Shares"][1] == "ratio"


def fund_routes():
    return [summary("SPY", "topHoldings", None) | {"json": {"quoteSummary": {"result": [{
        "quoteType": {"quoteType": "ETF"}, "summaryProfile": {"longBusinessSummary": "Tracks an index."},
        "topHoldings": {"holdings": [{"symbol": "AAPL", "holdingName": "Apple", "holdingPercent": 0.071}], "stockPosition": {"raw": 0.99},
                        "sectorWeightings": [{"technology": 0.3}], "bondRatings": [{"aaa": 0.1}]},
        "fundProfile": {"categoryName": "Large Blend", "family": "Example", "legalType": "Exchange Traded Fund"}}]}}}]


def test_fund_holdings_keep_the_reported_weight_and_symbol(cli):
    run = cli("fund", "holdings", "SPY", routes=fund_routes())
    assert run.code == 0, run
    assert [(r["Symbol"], r["Name"], float(r["Holding Percent"])) for r in run.rows] == [("AAPL", "Apple", 0.071)]


@pytest.mark.parametrize("kind,column,value", [("overview", "categoryName", "Large Blend"), ("sectors", "technology", "0.3"), ("asset-classes", "stockPosition", "0.99")])
def test_a_fund_mapping_becomes_one_row(cli, kind, column, value):
    run = cli("fund", kind, "SPY", routes=fund_routes())
    assert run.code == 0, run
    assert run.rows[0][column] == value


def test_a_fund_description_is_a_record(cli):
    run = cli("fund", "description", "SPY", routes=fund_routes())
    assert run.code == 0, run
    assert run.records[0]["data"] == "Tracks an index."


def test_a_fund_statistic_table_of_nulls_is_empty(cli):
    run = cli("fund", "equity", "SPY", routes=fund_routes())
    assert run.code == 7 and run.result()["status"] == "empty", run


def option_routes(calls):
    return [{"path": "/v7/finance/options/AAPL", "json": {"optionChain": {"result": [{"expirationDates": [1705622400], "quote": {"symbol": "AAPL", "regularMarketPrice": 100, "currency": "USD"},
                                                                                       "options": [{"calls": calls, "puts": []}]}], "error": None}}}]


def test_expirations_then_one_side_of_the_chain(cli):
    contract = {"contractSymbol": "AAPL240119C00100000", "lastTradeDate": 1704205800, "strike": 100, "lastPrice": 2, "bid": 0, "ask": 2.1, "volume": 0, "openInterest": 20,
                "impliedVolatility": 0.2, "inTheMoney": True, "contractSize": "REGULAR", "currency": "USD"}
    expirations = cli("options", "expirations", "AAPL", routes=option_routes([contract]))
    assert expirations.code == 0, expirations
    assert [r["expiration"] for r in expirations.rows] == ["2024-01-19"]
    chain = cli("options", "chain", "AAPL", "--date", "2024-01-19", "--side", "calls", routes=option_routes([contract]))
    assert chain.code == 0, chain
    row = chain.rows[0]
    assert (row["side"], row["contractSymbol"], row["lastTradeDate"], float(row["bid"])) == ("call", "AAPL240119C00100000", "2024-01-02T14:30:00+00:00", 0.0)
    assert chain.result()["conditions"]["date"]["status"] == "confirmed" and chain.result()["as_of"]["expiration"] == "2024-01-19"


def test_an_empty_chain_is_empty_not_success(cli):
    run = cli("options", "chain", "AAPL", routes=option_routes([]))
    assert run.code == 7 and run.doc["status"] == "empty", run


def test_shares_keep_an_integer_past_two_to_the_53(cli):
    routes = [{"path": "/v8/finance/chart/AAPL", "json": {"chart": {"result": [{"meta": {"exchangeTimezoneName": "America/New_York"}}], "error": None}}},
              {"path": "/timeseries/AAPL", "json": {"timeseries": {"result": [{"timestamp": [1704067200], "shares_out": [9007199254740993]}]}}}]
    run = cli("company", "shares", "AAPL", "--start", "2024-01-01", "--end", "2024-02-01", routes=routes)
    assert run.code == 0, run
    assert [(r["Date"], r["shares"]) for r in run.rows] == [("2024-01-01T00:00:00-05:00", "9007199254740993")]


def test_filings_are_records_with_their_document_map(cli):
    run = cli("company", "filings", "AAPL", routes=recorded("company-filings-aapl"))
    assert run.code == 0, run
    first = run.records[0]["data"][0]
    assert {"date", "type", "title", "exhibits"} <= set(first)
    assert all(url.startswith("https://cdn.yahoofinance.com/prod/sec-filings/") for url in first["exhibits"].values() if url.endswith(".htm"))
    shown = run.result().get("data") or run.result().get("first")
    assert shown, run


def test_holder_lists_keep_their_columns(cli):
    run = cli("holders", "institutional", "AAPL", routes=recorded("holders-institutional-aapl"))
    assert run.code == 0, run
    assert {"Date Reported", "Holder", "pctHeld", "Shares", "Value", "pctChange"} <= set(run.rows[0])
    assert run.result()["as_of"]["date_reported"] == max(r["Date Reported"][:10] for r in run.rows)
