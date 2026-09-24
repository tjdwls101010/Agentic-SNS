"""What stdout prints: the source's information without float residue, midnight clocks or echoed defaults.

The saved observation keeps every digit and every timestamp; only the screen is trimmed, so each test that checks a
trimmed value also checks, where it matters, that the stored copy was left alone.
"""
import json
import struct

META = {"currency": "USD", "symbol": "AAPL", "exchangeName": "NMS", "instrumentType": "EQUITY", "firstTradeDate": 345479400, "regularMarketTime": 1704387600,
        "gmtoffset": -18000, "timezone": "EST", "exchangeTimezoneName": "America/New_York", "regularMarketPrice": 110, "chartPreviousClose": 100,
        "priceHint": 2, "dataGranularity": "1d", "validRanges": ["1d", "5d", "1mo", "max"]}


def chart(close, adjclose, stamps=(1704205800, 1704292200), volume=(34673600, 1000)):
    quote = {"open": list(close), "high": list(close), "low": list(close), "close": list(close), "volume": list(volume)}
    payload = {"chart": {"error": None, "result": [{"meta": META, "timestamp": list(stamps), "indicators": {"quote": [quote], "adjclose": [{"adjclose": list(adjclose)}]}, "events": {}}]}}
    return [{"path": "/v8/finance/chart/AAPL", "json": payload}]


def column(result, name):
    data = result["data"]
    return [row[data["columns"].index(name)] for row in data["data"]]


# ---- numbers ------------------------------------------------------------------------------------------------------


def test_a_price_prints_the_float32_value_yahoo_served_not_its_float64_residue(cli):
    proc, doc = cli("prices", "history", "AAPL", "--period", "5d", "--adjust", "none", routes=chart([311.4700012207031, 313.3599853515625], [311.4700012207031, 313.3599853515625]))
    assert proc.returncode == 0, proc.stdout[:400]
    r = doc["results"][0]
    assert column(r, "Close") == [311.47, 313.36]
    assert column(r, "Volume") == [34673600, 1000]
    assert [type(v) for v in column(r, "Dividends")] == [int, int], "an integral float prints as an integer"


def test_an_adjusted_price_prints_seven_significant_digits(cli):
    """Auto adjustment multiplies the served float32 by a ratio; the digits past the seventh are that arithmetic."""
    proc, doc = cli("prices", "history", "AAPL", "--period", "5d", "--adjust", "auto", routes=chart([311.4700012207031, 313.3599853515625], [308.0643005371094, 310.0]))
    assert proc.returncode == 0, proc.stdout[:400]
    r = doc["results"][0]
    assert column(r, "Close") == [308.0643, 310]


def test_seven_significant_digits_never_drop_integer_digits(cli):
    proc, doc = cli("prices", "history", "AAPL", "--period", "5d", "--adjust", "auto", routes=chart([100.0, 100.0], [12345678.9, 100.0]))
    assert column(doc["results"][0], "Close") == [12345679, 100]


def test_the_saved_observation_keeps_every_digit(cli, tmp_path):
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--period", "5d", "--adjust", "auto", routes=chart([311.4700012207031, 313.3599853515625], [308.0643005371094, 310.0]), store=store)
    saved = json.loads((store / (doc["results"][0]["id"] + ".json")).read_text())
    close = saved["data"]["columns"].index("Close")
    assert saved["data"]["data"][0][close] == 308.0643005371094
    assert saved["data"]["index"][0] == "2024-01-02T00:00:00-05:00"


def test_a_field_whose_source_precision_is_unknown_keeps_every_digit(cli):
    """Half the option-chain values are not float32 at all, so there is no established precision to trim to."""
    contract = {"contractSymbol": "C1", "lastTradeDate": 1704205800, "strike": 100.0, "lastPrice": 2.0, "bid": 0.0, "ask": 2.1,
                "impliedVolatility": 1.0000000000000003e-05, "inTheMoney": True, "currency": "USD"}
    routes = [{"path": "/v7/finance/options/AAPL", "json": {"optionChain": {"result": [{"expirationDates": [1705622400], "quote": {"symbol": "AAPL"}, "options": [{"calls": [contract], "puts": []}]}], "error": None}}}]
    proc, doc = cli("options", "chain", "AAPL", "--side", "calls", "--fields", "strike,impliedVolatility,lastTradeDate", routes=routes)
    assert proc.returncode == 0, proc.stdout[:400]
    assert doc["results"][0]["data"]["calls"]["data"] == [[100, 1.0000000000000003e-05, "2024-01-02T14:30:00+00:00"]]


def test_a_statement_amount_prints_as_the_integer_it_is(cli):
    payload = {"timeseries": {"result": [{"meta": {"type": ["annualTotalRevenue"]}, "timestamp": [1735603200], "annualTotalRevenue": [{"asOfDate": "2024-12-31", "reportedValue": {"raw": 416161000000.0}}]}], "error": None}}
    info = [{"path": "/quoteSummary/AAPL", "json": {"quoteSummary": {"result": [{"financialData": {"financialCurrency": "USD"}}], "error": None}}},
            {"path": "/v7/finance/quote", "json": {"quoteResponse": {"result": [{"symbol": "AAPL", "currency": "USD"}], "error": None}}}]
    proc, doc = cli("financials", "income", "AAPL", "--fields", "TotalRevenue", routes=[{"path": "/timeseries/AAPL", "json": payload}] + info)
    assert proc.returncode == 0, proc.stdout[:400]
    assert '"data":[[416161000000]]' in proc.stdout
    assert doc["results"][0]["data"]["index"] == ["2024-12-31"]


# ---- dates --------------------------------------------------------------------------------------------------------


def test_daily_bars_print_their_date_when_the_timezone_travels_with_them(cli):
    proc, doc = cli("prices", "history", "AAPL", "--period", "5d", routes=chart([1.0, 2.0], [1.0, 2.0]))
    r = doc["results"][0]
    assert r["data"]["index"] == ["2024-01-02", "2024-01-03"]
    assert r["context"]["timezone"] == "America/New_York"


def test_a_time_of_day_is_kept(cli):
    head = "<table><thead><tr><th>Symbol</th><th>Company</th><th>Earnings Date</th><th>EPS Estimate</th><th>Reported EPS</th><th>Surprise (%)</th></tr></thead><tbody>"
    rows = "<tr><td>AAPL</td><td>Apple</td><td>January 25, 2024 at 4 PM EST</td><td>1</td><td>1</td><td>0</td></tr>"
    proc, doc = cli("calendar", "earnings", "AAPL", routes=[{"path": "/calendar/earnings", "text": head + rows + "</tbody></table>"}])
    assert proc.returncode == 0, proc.stdout[:400]
    assert doc["results"][0]["data"]["index"] == ["2024-01-25T16:00:00-05:00"]


def test_an_offset_with_no_timezone_beside_it_is_kept(cli):
    """Dropping the offset is only lossless when the envelope says which zone the dates are in."""
    routes = [{"path": "/v8/finance/chart/AAPL", "json": {"chart": {"result": [{"meta": {"exchangeTimezoneName": "America/New_York"}}], "error": None}}},
              {"path": "/timeseries/AAPL", "json": {"timeseries": {"result": [{"timestamp": [1704067200, 1704153600], "shares_out": [42, 43]}]}}}]
    proc, doc = cli("company", "shares", "AAPL", routes=routes)
    assert proc.returncode == 0, proc.stdout[:400]
    assert doc["results"][0]["data"]["index"] == ["2024-01-01T00:00:00-05:00", "2024-01-02T00:00:00-05:00"]


def test_a_label_among_dates_is_left_as_it_is(cli):
    payload = {"timeseries": {"result": [{"meta": {"type": ["trailingPeRatio"]}, "timestamp": [1735603200], "trailingPeRatio": [{"asOfDate": "2024-12-31", "reportedValue": {"raw": 30.5}}]}]}}
    proc, doc = cli("financials", "valuation", "AAPL", "--periods", "0", "--fields", "Trailing P/E", routes=[{"path": "/timeseries/AAPL", "json": payload}])
    assert doc["results"][0]["data"]["index"] == ["Current"]


def test_null_axis_names_are_left_out(cli):
    proc, doc = cli("prices", "history", "AAPL", "--period", "5d", routes=chart([1.0, 2.0], [1.0, 2.0]))
    data = doc["results"][0]["data"]
    assert data["index_names"] == ["Date"] and "column_names" not in data


# ---- the echoed request -------------------------------------------------------------------------------------------


def test_the_request_names_what_was_chosen_and_what_a_default_filled_in(cli, tmp_path):
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--adjust", "none", routes=chart([1.0, 2.0], [1.0, 2.0]), store=store)
    assert doc["request"] == {"adjust": "none", "period": "1mo"}, "period was filled in by the leaf's default, adjust was chosen"
    saved = json.loads((store / (doc["results"][0]["id"] + ".json")).read_text())
    assert saved["request"]["interval"] == "1d" and saved["request"]["timeout"] == 30, "the stored request stays complete"


def float32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def test_five_years_of_daily_bars_show_about_twice_the_rows_in_one_screen(cli):
    """The same fixture showed 133 of 1254 rows before the residue was trimmed; the budget now holds about twice as
    many. (The budget narrows to 80% of --max-chars so it converges in one pass, which is why this is not 20000/row.)"""
    n = 1254
    close = [float32(100 + 0.37 * i) for i in range(n)]
    adjusted = [float32(c * 0.9813) for c in close]
    quote = {"open": close, "high": close, "low": close, "close": close, "volume": [30000000 + i for i in range(n)]}
    payload = {"chart": {"error": None, "result": [{"meta": META, "timestamp": [1577977800 + 86400 * i for i in range(n)], "indicators": {"quote": [quote], "adjclose": [{"adjclose": adjusted}]}, "events": {}}]}}
    proc, doc = cli("prices", "history", "AAPL", "--period", "5y", routes=[{"path": "/v8/finance/chart/AAPL", "json": payload}])
    assert proc.returncode == 8, proc.stdout[:300]
    assert doc["results"][0]["coverage"]["shown"] >= 240
