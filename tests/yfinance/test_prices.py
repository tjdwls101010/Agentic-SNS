import pytest

CHART = {"chart": {"error": None, "result": [{"meta": {"currency": "USD", "symbol": "AAPL", "exchangeName": "NMS", "instrumentType": "EQUITY", "firstTradeDate": 345479400, "regularMarketTime": 1704387600, "gmtoffset": -18000, "timezone": "EST", "exchangeTimezoneName": "America/New_York", "regularMarketPrice": 110, "chartPreviousClose": 100, "priceHint": 2, "dataGranularity": "1d", "validRanges": ["1d", "5d", "1mo", "max"]}, "timestamp": [1704205800, 1704292200, 1704378600], "indicators": {"quote": [{"open": [100, 0, 110], "high": [105, 0, 115], "low": [95, 0, 105], "close": [100, 0, 110], "volume": [9007199254740993, 0, 1200]}], "adjclose": [{"adjclose": [50, 0, 55]}]}, "events": {"dividends": {"1704205800": {"amount": 0.5, "date": 1704205800}}}}]}}


def chart_routes():
    return [{"path": "/v8/finance/chart/AAPL", "json": CHART}]


def test_history_preserves_axis_timezone_zero_and_large_integer(cli):
    proc, doc = cli("prices", "history", "AAPL", "--start", "2024-01-02", "--end", "2024-01-04", "--adjust", "none", "--fields", "Close,Volume", routes=chart_routes())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    r = doc["results"][0]
    assert r["data"]["columns"] == ["Close", "Volume"]
    assert r["data"]["data"] == [[100.0, 9007199254740993], [0.0, 0]]
    assert r["data"]["index"] == ["2024-01-02T00:00:00-05:00", "2024-01-03T00:00:00-05:00"]
    assert r["data"]["index_names"] == ["Date"]
    assert r["context"]["currency"] == "USD"
    assert doc["request"]["period"] is None
    assert doc["request"]["repair"] is False
    assert r["context"]["end_boundary"] == "exclusive"


def test_batch_retains_success_and_stops_remaining_targets_on_rate_limit(cli):
    routes = chart_routes() + [{"path": "/v1/test/getcrumb", "status": 429, "text": "Too Many Requests"}, {"path": "/v8/finance/chart/RATE", "status": 429, "text": "Too Many Requests"}, {"path": "/consent", "text": ""}]
    proc, doc = cli("prices", "history", "AAPL", "RATE", "NEVER", "--period", "1mo", "--adjust", "none", routes=routes)
    assert proc.returncode == 8, proc.stdout + proc.stderr
    assert doc["status"] == "partial"
    assert [r["status"] for r in doc["results"]] == ["ok", "error", "not_attempted"]
    assert doc["results"][1]["error"]["code"] == "rate_limited"



@pytest.mark.parametrize("adjust,expected_open,expected_close", [("auto", 50, 50), ("back", 50, 100), ("none", 100, 100)])
def test_adjustment_modes_keep_their_distinct_price_meaning(cli, adjust, expected_open, expected_close):
    proc, doc = cli("prices", "history", "AAPL", "--start", "2024-01-02", "--end", "2024-01-03", "--adjust", adjust, "--fields", "Open,Close", routes=chart_routes())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["data"] == [[expected_open, expected_close]]
    assert doc["request"]["adjust"] == adjust


def test_actions_keep_native_dividend_amount(cli):
    proc, doc = cli("prices", "actions", "AAPL", "--period", "1mo", "--fields", "Dividends", routes=chart_routes())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["data"] == [[0.5]]


def test_bad_target_does_not_erase_a_good_target(cli):
    routes = chart_routes() + [{"path": "/v8/finance/chart/BAD", "json": {"chart": {"result": None, "error": {"code": "Not Found", "description": "No such symbol"}}}}]
    routes += [{"path": "/quoteSummary/BAD", "json": {"quoteSummary": {"result": []}}}, {"path": "/v7/finance/quote", "params": {"symbols": "BAD"}, "json": {"quoteResponse": {"result": []}}}, {"path": "/timeseries/BAD", "json": {"timeseries": {"result": []}}}]
    proc, doc = cli("prices", "history", "BAD", "AAPL", "--period", "1mo", routes=routes)
    assert proc.returncode == 8, proc.stdout + proc.stderr
    assert [r["status"] for r in doc["results"]] == ["error", "ok"]
    assert doc["results"][1]["data"]["index"]


def test_oversize_returns_no_partial_table_and_actionable_recovery(cli):
    proc, doc = cli("prices", "history", "AAPL", "AAPL", "--period", "1mo", "--max-chars", "1000", routes=chart_routes())
    assert proc.returncode == 9, proc.stdout + proc.stderr
    r = doc["results"][0]
    assert r["data"] is None
    assert "--fields" in r["error"]["fix"]
    assert "--max-chars" in r["error"]["fix"]


def test_rate_limit_without_success_uses_rate_exit_code(cli):
    proc, doc = cli("prices", "history", "RATE", "NEVER", routes=[{"path": "/v8/finance/chart/RATE", "status": 429, "text": "Too Many Requests"}, {"path": "/consent", "text": ""}])
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert doc["status"] == "error"
    assert [r["status"] for r in doc["results"]] == ["error", "not_attempted"]


def many_symbol_routes(count):
    return [{"path": f"/v8/finance/chart/S{i:02d}", "json": CHART} for i in range(count)]


def test_thirty_targets_one_value_each_fit_the_default_budget(cli):
    symbols = [f"S{i:02d}" for i in range(30)]
    proc, doc = cli("prices", "history", *symbols, "--period", "5d", "--fields", "Close", "--limit", "1", routes=many_symbol_routes(30))
    assert proc.returncode == 0, proc.stdout[:300] + proc.stderr
    assert doc["status"] == "ok"
    assert [r["target"] for r in doc["results"]] == symbols
    assert doc["request"]["fields"] == ["Close"]
    assert "request" not in doc["results"][0]


def test_envelope_dominated_oversize_recovery_names_budget_before_narrowing(cli):
    symbols = [f"S{i:02d}" for i in range(30)]
    proc, doc = cli("prices", "history", *symbols, "--period", "5d", "--fields", "Close", "--limit", "1", "--max-chars", "5000", routes=many_symbol_routes(30))
    assert proc.returncode == 9, proc.stdout[:300] + proc.stderr
    fix = doc["results"][0]["error"]["fix"]
    assert "--max-chars" in fix
    assert "--fields" not in fix.split("--max-chars")[0]
    assert "target" in fix.lower()
