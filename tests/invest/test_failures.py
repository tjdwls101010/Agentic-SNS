"""Failures: each code rests on what Yahoo's response says, one target's failure leaves the others alone, and the document's status and exit code follow the table below.

| targets                                   | status  | exit                                                         |
| all ok                                    | ok      | 0                                                            |
| ok + empty, error or not_attempted        | partial | 8                                                            |
| all empty                                 | empty   | 7                                                            |
| no ok, an error                           | error   | rate_limited 5 > invalid 2 > local_io 4 > any other code 6   |
| an argument refused before any request    | error   | 2                                                            |

Recorded responses (fixtures/yahoo) carry Yahoo's own refusals; synthetic routes stand in for what cannot be provoked live (a 429, a slow answer).
"""
from pathlib import Path
import stat

from conftest import recorded

TOO_MANY = {"status": 429, "text": "Too Many Requests"}


# ---- the code each failure gets, from Yahoo's own answer ------------------------------------------------------------

def test_a_symbol_yahoo_denies_is_not_found(cli):
    run = cli("quote", "XYZQQ", routes=recorded("quote-xyzqq"))
    assert run.code == 6, run
    error = run.result()["error"]
    assert error["code"] == "not_found" and "Quote not found for symbol: XYZQQ" in error["message"] and "search" in error["fix"]


def test_history_of_a_denied_symbol_is_not_found_and_leaves_the_other_target(cli):
    run = cli("history", "XYZQQ", "AAPL", "--start", "2026-09-28", "--end", "2026-10-03", "--adjust", "none",
              routes=recorded("history-xyzqq") + recorded("history-aapl"))
    assert run.code == 8, run
    assert [r["status"] for r in run.doc["results"]] == ["error", "ok"]
    assert run.result(0)["error"]["code"] == "not_found"
    assert {r["target"] for r in run.rows} == {"AAPL"} and len(run.rows) == 5


def test_a_delisted_symbol_yahoo_still_knows_is_no_data_not_not_found(cli):
    """TWTR: Yahoo's quoteSummary answers 200 with quoteType NONE, so it does not deny the symbol."""
    run = cli("quote", "TWTR", routes=recorded("quote-twtr"))
    assert run.code == 6, run
    error = run.result()["error"]
    assert error["code"] == "no_data" and "quoteType NONE" in error["message"]


def test_a_range_before_listing_is_no_data(cli):
    run = cli("history", "ARM", "--start", "2021-01-01", "--end", "2022-01-01", routes=recorded("history-arm-2021"))
    assert run.code == 6, run
    error = run.result()["error"]
    assert error["code"] == "no_data" and "Data doesn't exist" in error["message"]
    assert "--interval" in error["fix"] or "dates" in error["fix"]


def test_possibly_delisted_is_yfinances_guess_and_stays_no_data(cli):
    """A normal symbol over a window with no bars: yfinance says "possibly delisted", which is not Yahoo denying the symbol."""
    meta = {"currency": "USD", "symbol": "AAPL", "exchangeTimezoneName": "America/New_York", "timezone": "EST", "gmtoffset": -18000,
            "instrumentType": "EQUITY", "regularMarketTime": 1704387600, "dataGranularity": "1d", "validRanges": ["1d", "max"]}
    routes = [{"path": "/v8/finance/chart/AAPL", "json": {"chart": {"result": [{"meta": meta, "timestamp": [], "indicators": {"quote": [{}]}}], "error": None}}}]
    run = cli("history", "AAPL", "--start", "2024-01-06", "--end", "2024-01-08", routes=routes)
    assert run.code in (6, 7), run
    if run.result()["status"] == "error":
        assert run.result()["error"]["code"] == "no_data"


def test_fund_data_for_a_stock_is_not_applicable(cli):
    run = cli("fund", "holdings", "AAPL", routes=recorded("fund-holdings-aapl"))
    assert run.code == 6, run
    error = run.result()["error"]
    assert error["code"] == "not_applicable" and "EQUITY" in error["message"]


def test_an_unconfirmed_quote_type_is_no_data_not_a_guess(cli):
    routes = [{"path": "/quoteSummary/MYST", "json": {"quoteSummary": {"result": [{"summaryProfile": {}}], "error": None}}}]
    run = cli("fund", "holdings", "MYST", routes=routes)
    assert run.code == 6, run
    assert run.result()["error"]["code"] == "no_data"


def test_an_intraday_span_refusal_names_the_days_allowed(cli):
    run = cli("history", "AAPL", "--period", "1y", "--interval", "1m", routes=recorded("history-intraday-reach"))
    assert run.code == 6, run
    error = run.result()["error"]
    assert error["code"] == "source_constraint"
    assert "8 days" in error["fix"] and "--period 8d" in error["fix"]


def test_an_intraday_reach_refusal_names_how_far_back(cli):
    body = {"chart": {"result": None, "error": {"code": "Unprocessable Entity", "description": "5m data not available for startTime=1 and endTime=2. The requested range must be within the last 60 days."}}}
    zone = {"path": "/v8/finance/chart/AAPL", "params": {"range": "1d"}, "json": CHART}  # yfinance first reads the exchange's time zone
    run = cli("history", "AAPL", "--start", "2024-01-01", "--end", "2024-01-10", "--interval", "5m",
              routes=[zone, {"path": "/v8/finance/chart/AAPL", "status": 422, "json": body}])
    assert run.code == 6, run
    error = run.result()["error"]
    assert error["code"] == "source_constraint" and "last 60 days" in error["fix"]


# ---- a rate limit stops the rest; what arrived is kept ------------------------------------------------------------------

STATEMENT = {"timeseries": {"result": [{"meta": {"type": ["annualTotalRevenue"]}, "timestamp": [1735603200],
                                        "annualTotalRevenue": [{"asOfDate": "2024-12-31", "reportedValue": {"raw": 120}}]}], "error": None}}


def test_a_rate_limit_on_the_currency_lookup_keeps_the_statement_and_stops_the_next_target(cli):
    routes = [{"path": "/timeseries/AAPL", "json": STATEMENT}, {"path": "/quoteSummary/AAPL", **TOO_MANY}, {"path": "/v7/finance/quote", **TOO_MANY}]
    run = cli("financials", "income", "AAPL", "MSFT", routes=routes)  # no MSFT route: asking for MSFT would fail the fixture
    assert run.code == 8, run
    first, second = run.doc["results"]
    assert first["status"] == "ok" and "secondary_rate_limited" in first["warnings"]
    assert second["status"] == "not_attempted" and second["error"]["code"] == "not_attempted"
    assert [float(r["TotalRevenue"]) for r in run.rows] == [120.0]


def test_a_save_failure_after_a_rate_limit_keeps_the_remaining_targets_not_attempted(cli, tmp_path):
    data = tmp_path / "locked"
    data.mkdir()
    data.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        routes = [{"path": "/timeseries/AAPL", "json": STATEMENT}, {"path": "/quoteSummary/AAPL", **TOO_MANY}, {"path": "/v7/finance/quote", **TOO_MANY}]
        run = cli("financials", "income", "AAPL", "MSFT", routes=routes, data=data)
    finally:
        data.chmod(stat.S_IRWXU)
    assert "receipt_path" not in run.doc and run.doc["file"] is None, "nothing was saved, so no path is named"
    first, second = run.doc["results"]
    assert first["error"]["code"] == "local_io" and second["status"] == "not_attempted"
    assert "not_saved" in [w["code"] for w in run.doc["warnings"]]
    assert run.code == 5, "the rate limit already met outranks the save failure that followed it"


def test_a_rate_limited_first_target_exits_5_and_attempts_nothing_else(cli):
    run = cli("history", "RATE", "NEVER", routes=[{"path": "/v8/finance/chart/RATE", **TOO_MANY}])
    assert run.code == 5, run
    assert [r["status"] for r in run.doc["results"]] == ["error", "not_attempted"]
    assert run.result(0)["error"]["code"] == "rate_limited"
    assert all("NEVER" not in r["path"] for r in run.requests)


def test_a_timestamp_containing_429_is_not_a_rate_limit(cli):
    """A bare substring test once read endTime=1791264293 inside a 422 refusal as a rate limit."""
    body = {"chart": {"result": None, "error": {"code": "Unprocessable Entity", "description": "1m data not available for startTime=1759728293 and endTime=1791264293. Only 8 days worth of 1m granularity data are allowed to be fetched per request."}}}
    zone = {"path": "/v8/finance/chart/AAPL", "params": {"range": "1d"}, "json": CHART}
    run = cli("history", "AAPL", "--period", "1y", "--interval", "1m", routes=[zone, {"path": "/v8/finance/chart/AAPL", "status": 422, "json": body}])
    assert run.result()["error"]["code"] == "source_constraint", run
    assert run.code == 6


# ---- each target under its own deadline ---------------------------------------------------------------------------------

CHART = {"chart": {"error": None, "result": [{"meta": {"currency": "USD", "symbol": "FAST", "exchangeTimezoneName": "America/New_York", "timezone": "EST",
                                                       "gmtoffset": -18000, "instrumentType": "EQUITY", "regularMarketTime": 1704387600,
                                                       "dataGranularity": "1d", "validRanges": ["1d", "5d", "1mo", "max"]},
                                              "timestamp": [1704205800], "indicators": {"quote": [{"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]}],
                                                                                         "adjclose": [{"adjclose": [1.0]}]}}]}}


def test_a_slow_answer_times_out_alone_and_the_next_target_and_the_file_follow(cli):
    routes = [{"path": "/v8/finance/chart/SLOW", "json": CHART, "delay": 5}, {"path": "/v8/finance/chart/FAST", "json": CHART}]
    run = cli("history", "SLOW", "FAST", "--period", "5d", "--timeout", "1", routes=routes)
    assert run.code == 8, run
    slow, fast = run.doc["results"]
    assert slow["status"] == "error" and "--timeout 1" in slow["error"]["message"]
    assert fast["status"] == "ok" and [r["target"] for r in run.rows] == ["FAST"]


def test_the_deadline_passes_through_a_lookup_whose_errors_are_caught(cli):
    """The currency lookup catches every Exception so a failed lookup keeps the statement; the deadline is a BaseException and still ends the target."""
    routes = [{"path": "/timeseries/SLOW", "json": STATEMENT}, {"path": "/quoteSummary/SLOW", "json": {}, "delay": 5},
              {"path": "/timeseries/FAST", "json": STATEMENT},
              {"path": "/quoteSummary/FAST", "json": {"quoteSummary": {"result": [{"financialData": {"financialCurrency": "USD"}}], "error": None}}},
              {"path": "/v7/finance/quote", "json": {"quoteResponse": {"result": [{"symbol": "FAST", "currency": "USD"}], "error": None}}}]
    run = cli("financials", "income", "SLOW", "FAST", "--timeout", "1", routes=routes)
    assert run.code == 8, run
    slow, fast = run.doc["results"]
    assert slow["status"] == "error" and "--timeout" in slow["error"]["message"]
    assert fast["status"] == "ok" and fast["financial_currency"] == "USD"


# ---- the status table ---------------------------------------------------------------------------------------------------

def test_all_empty_is_empty_and_exits_7(cli):
    run = cli("history", "KO", "--start", "2025-01-02", "--end", "2025-01-10", "--actions", routes=recorded("history-actions-ko"))
    assert run.doc["status"] == "empty" and run.code == 7, run
    assert run.doc["file"] is None and Path(run.doc["receipt_path"]).is_file()


def test_ok_beside_empty_is_partial(cli):
    empty = {"path": "/v7/finance/options/EMPTY", "json": {"optionChain": {"result": [{"expirationDates": [1705622400], "quote": {}, "options": [{"calls": [], "puts": []}]}], "error": None}}}
    full = {"path": "/v7/finance/options/AAPL", "json": {"optionChain": {"result": [{"expirationDates": [1705622400], "quote": {"currency": "USD"},
            "options": [{"calls": [{"contractSymbol": "C1", "strike": 1.0, "lastPrice": 1.0, "currency": "USD"}], "puts": []}]}], "error": None}}}
    run = cli("options", "chain", "AAPL", "EMPTY", routes=[full, empty])
    assert [r["status"] for r in run.doc["results"]] == ["ok", "empty"]
    assert run.doc["status"] == "partial" and run.code == 8, run


def test_an_invalid_target_argument_without_any_ok_exits_2(cli):
    routes = [{"path": "/v7/finance/options/AAPL", "json": {"optionChain": {"result": [{"expirationDates": [1705622400], "quote": {}, "options": [{"calls": [], "puts": []}]}], "error": None}}}]
    run = cli("options", "chain", "AAPL", "--date", "2030-01-18", routes=routes)
    assert run.result()["error"]["code"] == "invalid" and run.code == 2, run


def test_a_refused_argument_saves_nothing_and_exits_2(cli, tmp_path):
    run = cli("history", "AAPL", "--repair", "--interval", "5d", routes=[], data=tmp_path / "fresh")
    assert run.code == 2 and run.doc["status"] == "error", run
    assert "receipt_path" not in run.doc and not (tmp_path / "fresh").exists()
    assert run.requests == []


def test_upstream_codes_without_any_ok_exit_6(cli):
    run = cli("quote", "XYZQQ", "TWTR", routes=recorded("quote-xyzqq") + recorded("quote-twtr"))
    assert [r["error"]["code"] for r in run.doc["results"]] == ["not_found", "no_data"]
    assert run.doc["status"] == "error" and run.code == 6, run


def test_rate_limited_outranks_invalid_and_local_io(cli):
    """Two errors in one document: the more actionable code decides the exit."""
    routes = [{"path": "/v7/finance/options/AAPL", "json": {"optionChain": {"result": [{"expirationDates": [1705622400], "quote": {}, "options": [{"calls": [], "puts": []}]}], "error": None}}},
              {"path": "/v7/finance/options/RATE", **TOO_MANY}]
    run = cli("options", "chain", "AAPL", "RATE", "--date", "2030-01-18", routes=routes)
    assert [r["error"]["code"] for r in run.doc["results"]] == ["invalid", "rate_limited"]
    assert run.code == 5, run


def test_a_save_failure_is_reported_even_when_every_target_had_already_failed(cli, tmp_path):
    data = tmp_path / "locked"
    data.mkdir()
    data.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        run = cli("quote", "XYZQQ", routes=recorded("quote-xyzqq"), data=data)
    finally:
        data.chmod(stat.S_IRWXU)
    assert run.result()["error"]["code"] == "not_found"
    assert "not_saved" in [w["code"] for w in run.doc["warnings"]] and "receipt_path" not in run.doc
    assert run.code == 4, run


def test_a_rate_limit_on_the_currency_lookup_is_the_last_request_for_that_target(cli):
    targets = {"path": "/quoteSummary/AAPL", "params": {"modules": "financialData"}, "json": {"quoteSummary": {"result": [{"financialData": {"targetMeanPrice": 120, "currentPrice": 100}}], "error": None}}}
    run = cli("analysts", "targets", "AAPL", "MSFT", routes=[targets, {"path": "/v8/finance/chart/AAPL", **TOO_MANY}])
    assert [r["status"] for r in run.doc["results"]] == ["ok", "not_attempted"], run
    assert "secondary_rate_limited" in run.result()["warnings"] and "currency_unconfirmed" in run.result()["warnings"]
    assert sum("/chart/" in r["path"] for r in run.requests) <= 2, "one lookup (yfinance retries a refused request once), never a second lookup"
    assert run.code == 8


def test_after_a_rate_limit_no_further_lookup_is_made_for_the_same_target(cli):
    """valuation's currency lookup is refused with 429; its Market Cap still lacks a quote currency, and asking the chart for one would spend another request."""
    payload = {"timeseries": {"result": [{"meta": {"type": ["trailingPeRatio"]}, "trailingPeRatio": [{"asOfDate": "2025-01-01", "reportedValue": {"raw": 30}}]}]}}
    routes = [{"path": "/timeseries/AAPL", "json": payload}, {"path": "/quoteSummary/AAPL", **TOO_MANY}, {"path": "/v7/finance/quote", **TOO_MANY}]
    run = cli("financials", "valuation", "AAPL", "MSFT", routes=routes)
    assert [r["status"] for r in run.doc["results"]] == ["ok", "not_attempted"], run
    assert not any("/chart/" in r["path"] for r in run.requests)
