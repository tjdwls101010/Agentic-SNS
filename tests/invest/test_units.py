"""Units: every value leaves on the skill's scale with its unit named, and each currency role is tied to the right currency.

Expected values are the raw values in Yahoo's recorded responses (fixtures/yahoo) or in the synthetic routes here, converted by hand: x / 100 for a percent, 1 / x for a reciprocal, unchanged for a ratio. The relations at the end check the recorded source itself, which is what makes a declaration `verified` rather than carried over.
"""
import json
import math

import pytest

from conftest import recorded, source


def record(run, i=0):
    return run.records[i]["data"]


def test_info_percent_fields_become_ratios_and_ratio_fields_stay(cli):
    run = cli("quote", "KO", routes=recorded("quote-ko"))
    assert run.code == 0, run
    data = record(run)
    assert data["dividendYield"] == pytest.approx(0.0245)           # raw 2.45 (percent)
    assert data["fiveYearAvgDividendYield"] == pytest.approx(0.0284)  # raw 2.84
    assert data["regularMarketChangePercent"] == pytest.approx(0.0100409)  # raw 1.00409
    assert data["fiftyTwoWeekChangePercent"] == pytest.approx(0.2823776)   # raw 28.23776
    assert data["debtToEquity"] == pytest.approx(1.15519)            # raw 115.519
    assert data["52WeekChange"] == pytest.approx(0.2823776)          # raw 0.2823776, a stock: already a ratio
    assert data["trailingAnnualDividendYield"] == pytest.approx(0.024284879)
    assert data["payoutRatio"] == pytest.approx(0.6246)
    assert data["SandP52WeekChange"] == pytest.approx(0.1457566)
    units, status = run.receipt["units"], run.receipt["unit_status"]
    for field in ("dividendYield", "fiveYearAvgDividendYield", "regularMarketChangePercent", "debtToEquity", "52WeekChange", "trailingAnnualDividendYield", "payoutRatio"):
        assert units[field] == "ratio", field
    assert status["dividendYield"] == "verified" and status["debtToEquity"] == "verified" and status["fiveYearAvgDividendYield"] == "declared"
    assert units["marketCap"] == "money:quote" and units["regularMarketPrice"] == "per_share:quote"


def test_epoch_times_become_iso_utc(cli):
    run = cli("quote", "KO", routes=recorded("quote-ko"))
    data = record(run)
    assert data["regularMarketTime"] == "2026-10-05T20:00:02+00:00"  # raw 1791230402
    assert run.receipt["units"]["regularMarketTime"] == "datetime"


def test_an_index_reports_52_week_change_in_percent(cli):
    run = cli("quote", "^GSPC", routes=recorded("quote-gspc"))
    assert run.code == 0, run
    data = record(run)
    assert data["quoteType"] == "INDEX"
    assert data["52WeekChange"] == pytest.approx(0.14575661)          # raw 14.575661 on an index
    assert data["fiftyTwoWeekChangePercent"] == pytest.approx(0.14575661)


def test_quote_and_reporting_currencies_are_each_tied_to_their_fields(cli):
    """TM quotes in USD and reports in JPY: a price field belongs to currency, a statement amount to financial_currency."""
    run = cli("quote", "TM", routes=recorded("quote-tm"))
    assert run.code == 0, run
    result, units = run.result(), run.receipt["units"]
    assert (result["currency"], result["financial_currency"]) == ("USD", "JPY")
    assert units["marketCap"] == "money:quote" and units["regularMarketPrice"] == "per_share:quote" and units["trailingEps"] == "per_share:quote"
    assert units["totalRevenue"] == "money:financial" and units["ebitda"] == "money:financial" and units["enterpriseValue"] == "money:financial"
    assert units["trailingAnnualDividendRate"] == "per_share:financial" and units["revenuePerShare"] == "per_share:financial"
    data = record(run)
    assert data["marketCap"] == 218031849472 and data["totalRevenue"] == 51957024686080
    warning = {w["code"]: w["text"] for w in run.doc["warnings"]}["cross_currency_fields"]
    assert "priceToSalesTrailing12Months" in warning and "trailingAnnualDividendYield" in warning and "USD" in warning and "JPY" in warning


def test_a_statement_is_in_the_reporting_currency(cli):
    run = cli("financials", "income", "TM", routes=recorded("financials-income-tm"))
    assert run.code == 0, run
    assert (run.result()["financial_currency"], run.result()["currency"]) == ("JPY", "USD")
    units = run.receipt["units"]
    assert units["TotalRevenue"] == "money:financial" and units["DilutedEPS"] == "per_share:financial" and units["DilutedAverageShares"] == "shares"
    assert units["TaxRateForCalcs"] == "ratio"


def test_fund_multiples_arrive_as_reciprocals_and_leave_as_multiples(cli):
    run = cli("fund", "equity", "QQQ", routes=recorded("fund-equity-qqq"))
    assert run.code == 0, run
    rows = {(r["metric"], r["source_column"]): r for r in run.rows}
    assert float(rows["Price/Earnings", "QQQ"]["value"]) == pytest.approx(1 / 0.03531)   # raw 0.03531
    assert float(rows["Price/Book", "QQQ"]["value"]) == pytest.approx(1 / 0.11223)
    assert float(rows["Price/Sales", "QQQ"]["value"]) == pytest.approx(1 / 0.15557)
    assert float(rows["Price/Cashflow", "QQQ"]["value"]) == pytest.approx(1 / 0.04394)
    assert rows["Price/Earnings", "QQQ"]["unit"] == "multiple"
    assert rows["Price/Earnings", "Category Average"]["value"] == ""  # null stays null
    assert run.doc["units"]["value"] == "per row: see the unit column"


def fund_route(equity, operations=None):
    data = {"quoteType": {"quoteType": "ETF"}, "summaryProfile": {}, "fundProfile": {"feesExpensesInvestment": operations or {}, "feesExpensesInvestmentCat": {}},
            "topHoldings": {"holdings": [], "equityHoldings": equity, "sectorWeightings": [], "bondRatings": []}}
    return [{"path": "/quoteSummary/QQQ", "json": {"quoteSummary": {"result": [data], "error": None}}},
            {"path": "/v8/finance/chart/QQQ", "json": {"chart": {"result": [{"meta": {"currency": "USD", "exchangeTimezoneName": "America/New_York"}}], "error": None}}}]


def test_a_reciprocal_of_zero_is_null_and_a_negative_keeps_its_sign(cli):
    equity = {"priceToEarnings": 0, "priceToBook": -0.05, "priceToEarningsCat": 0.04, "priceToBookCat": 0.5}
    run = cli("fund", "equity", "QQQ", routes=fund_route(equity))
    assert run.code == 0, run
    rows = {(r["metric"], r["source_column"]): r["value"] for r in run.rows}
    assert rows["Price/Earnings", "QQQ"] == ""
    assert float(rows["Price/Book", "QQQ"]) == pytest.approx(-20.0)
    assert float(rows["Price/Earnings", "Category Average"]) == pytest.approx(25.0)
    assert float(rows["Price/Book", "Category Average"]) == pytest.approx(2.0)
    assert "inverse_of_zero" in [w["code"] for w in run.doc["warnings"]]


def test_fund_operations_keep_ratios_and_mark_net_assets_unverified(cli):
    run = cli("fund", "operations", "QQQ", routes=recorded("fund-operations-qqq"))
    assert run.code == 0, run
    rows = {(r["metric"], r["source_column"]): r for r in run.rows}
    assert float(rows["Annual Report Expense Ratio", "QQQ"]["value"]) == pytest.approx(0.0018000001)
    assert rows["Annual Report Expense Ratio", "QQQ"]["unit"] == "ratio"
    assert rows["Total Net Assets", "QQQ"]["unit"] == "unverified"
    assert float(rows["Annual Report Expense Ratio", "Category Average"]["value"]) == pytest.approx(0.0089579)


def chain_route(percent_change, volatility):
    contract = {"contractSymbol": "AAPL261009C00335000", "strike": 335.0, "currency": "USD", "lastPrice": 2.5, "change": 0.5, "percentChange": percent_change,
                "volume": 10, "openInterest": 20, "bid": 2.4, "ask": 2.6, "contractSize": "REGULAR", "expiration": 1791504000, "lastTradeDate": 1791489600,
                "impliedVolatility": volatility, "inTheMoney": False}
    chain = {"underlyingSymbol": "AAPL", "expirationDates": [1791504000], "strikes": [335.0], "hasMiniOptions": False,
             "quote": {"symbol": "AAPL", "regularMarketPrice": 333.0, "currency": "USD", "regularMarketTime": 1791489600},
             "options": [{"expirationDate": 1791504000, "hasMiniOptions": False, "calls": [contract], "puts": []}]}
    return [{"path": "/v7/finance/options/AAPL", "json": {"optionChain": {"result": [chain], "error": None}}}]


def test_option_percent_change_becomes_a_ratio_and_implied_volatility_stays_one(cli):
    run = cli("options", "chain", "AAPL", routes=chain_route(25.0, 0.31))
    assert run.code == 0, run
    row = run.rows[0]
    assert float(row["percentChange"]) == pytest.approx(0.25)
    assert float(row["impliedVolatility"]) == pytest.approx(0.31)
    assert run.receipt["units"]["percentChange"] == "ratio" and run.receipt["units"]["impliedVolatility"] == "ratio"
    assert run.result()["currency"] == "USD"


def test_the_two_surprise_scales_meet_on_one(cli):
    """Yahoo serves one measurement twice, 100x apart: surprisePercent 0.0674 and Surprise(%) +6.74 for the quarter reported 2026-07-30."""
    history = cli("analysts", "eps-history", "AAPL", routes=recorded("analysts-eps-history-aapl"))
    assert history.code == 0, history
    by_quarter = {r["quarter"][:10]: r for r in history.rows}
    assert float(by_quarter["2026-06-30"]["surprisePercent"]) == pytest.approx(0.0674)
    dates = cli("calendar", "earnings", "AAPL", "--limit", "25", routes=recorded("calendar-earnings-aapl"))
    assert dates.code == 0, dates
    july = next(r for r in dates.rows if r["Earnings Date"].startswith("2026-07-30"))
    assert float(july["Surprise(%)"]) == pytest.approx(0.0674)
    assert dates.receipt["units"]["Surprise(%)"] == "ratio"


# ---- screen queries: the caller's ratio, Yahoo's scale ------------------------------------------------------------------

GROWTH = '{"operator":"AND","operands":[{"operator":"EQ","operands":["region","us"]},{"operator":"GT","operands":["intradaymarketcap",10000000000]},{"operator":"GT","operands":["quarterlyrevenuegrowth.quarterly",0.2]}]}'


def test_a_measured_rate_is_translated_to_yahoos_scale(cli):
    run = cli("screen", "run", "--query", GROWTH, "--limit", "25", routes=recorded("screen-run-growth"))
    assert run.code == 0, run
    sent = run.requests[-1]["body"]["query"]["operands"]
    assert sent[2] == {"operator": "GT", "operands": ["quarterlyrevenuegrowth.quarterly", 20.0]}
    assert sent[1]["operands"] == ["intradaymarketcap", 10000000000], "an amount is sent as written"
    assert run.receipt["results"][0]["source"]["sent_query"]["operands"][2]["operands"][1] == 20.0


@pytest.mark.parametrize("kind", ["equity", "fund", "etf"])
def test_every_rate_field_in_the_catalog_has_a_measured_scale(cli, kind):
    """A rate field without a measured scale would be refused; a library upgrade that adds one fails here and asks for a measurement."""
    run = cli("screen", "fields", "--type", kind, routes=[])
    assert run.code == 0, run
    rates = [r for r in run.rows if r["input_unit"] == "ratio"]
    assert all(r["status"] == "measured" and r["yahoo_unit"] == "percent" for r in rates), [r["field"] for r in rates if r["status"] != "measured"]
    assert {r["field"] for r in rates} >= ({"quarterlyrevenuegrowth.quarterly", "returnonequity.lasttwelvemonths"} if kind == "equity" else set())


def test_an_unknown_field_is_refused_by_name_before_any_request(cli):
    run = cli("screen", "run", "--query", '{"operator":"GT","operands":["nosuchgrowth",0.2]}', routes=[])
    assert run.code == 2, run
    assert run.requests == []
    assert "nosuchgrowth" in run.result()["error"]["message"] and "screen fields" in run.result()["error"]["fix"]


def test_source_units_send_the_query_as_written_and_say_so(cli):
    query = '{"operator":"GT","operands":["returnonequity.lasttwelvemonths",20]}'  # 20 meaning 20%, Yahoo's own scale
    routes = [{"path": "/v1/finance/screener", "json": {"finance": {"result": [{"quotes": [{"symbol": "EX", "currency": "USD"}], "total": 1, "start": 0, "count": 1}], "error": None}}}]
    run = cli("screen", "run", "--query", query, "--source-units", routes=routes)
    assert run.code == 0, run
    assert run.requests[-1]["body"]["query"] == {"operator": "GT", "operands": ["returnonequity.lasttwelvemonths", 20]}
    assert "source_units" in [w["code"] for w in run.doc["warnings"]]
    assert run.result()["conditions"]["query"]["status"] == "unverified"


def test_presets_are_shown_on_the_callers_scale(cli):
    """growth_technology_stocks sends quarterlyrevenuegrowth.quarterly GTE 25 and epsgrowth.lasttwelvemonths GTE 25 (percent points); a caller writes 0.25."""
    run = cli("screen", "presets", routes=[])
    assert run.code == 0, run
    preset = next(p for p in run.records[0]["data"] if p["name"] == "growth_technology_stocks")
    leaves = json.dumps(preset["query"])
    assert '["quarterlyrevenuegrowth.quarterly", 0.25]' in leaves and '["epsgrowth.lasttwelvemonths", 0.25]' in leaves
    assert "source_units" not in preset


# ---- the recorded source itself: the relations behind `verified` ---------------------------------------------------------

def test_source_ko_dividend_yield_is_rate_over_price_in_percent():
    v7 = source("quote-ko", "/v7/finance/quote")["quoteResponse"]["result"][0]
    summary = source("quote-ko", "quoteSummary")["quoteSummary"]["result"][0]["summaryDetail"]
    assert math.isclose(v7["dividendYield"], summary["dividendRate"] / v7["regularMarketPrice"] * 100, abs_tol=0.05)


def test_source_surprise_percent_is_a_ratio_and_the_calendar_reports_it_times_100():
    history = source("analysts-eps-history-aapl", "quoteSummary")["quoteSummary"]["result"][0]["earningsHistory"]["history"]
    june = next(h for h in history if h["quarter"]["fmt"] == "2026-06-30")
    actual, estimate, surprise = june["epsActual"]["raw"], june["epsEstimate"]["raw"], june["surprisePercent"]["raw"]
    assert math.isclose(surprise, (actual - estimate) / abs(estimate), abs_tol=0.0005)
    assert june["surprisePercent"]["fmt"] == "6.74%", "Yahoo formats the ratio as a percent itself"
    assert math.isclose(6.74, surprise * 100, abs_tol=0.05)  # calendar earnings shows +6.74 for this quarter


def test_source_index_52_week_change_equals_its_percent_field():
    v7 = source("quote-gspc", "/v7/finance/quote")["quoteResponse"]["result"][0]
    assert v7["quoteType"] == "INDEX"
    assert v7["fiftyTwoWeekChangePercent"] == pytest.approx(14.575661)


def test_source_ko_debt_to_equity_is_debt_over_equity_in_percent():
    summary = source("quote-ko", "quoteSummary")["quoteSummary"]["result"][0]["financialData"]
    series = next(r["quarterlyTotalEquityGrossMinorityInterest"] for r in source("financials-balance-ko", "timeseries")["timeseries"]["result"]
                  if r.get("quarterlyTotalEquityGrossMinorityInterest"))
    equity = max((x for x in series if x), key=lambda x: x["asOfDate"])["reportedValue"]["raw"]
    assert math.isclose(summary["debtToEquity"], summary["totalDebt"] / equity * 100, abs_tol=0.05)
