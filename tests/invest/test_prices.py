"""Price bars: the file keeps every value as received (a zero, a missing value, an integer past 2**53, the exchange's time zone), --adjust decides what Close means, and only the inline copy rounds prices to the 7 digits Yahoo serves.

The chart is synthetic; its literals are the expectation.
"""
import pytest

CHART = {"chart": {"error": None, "result": [{"meta": {"currency": "USD", "symbol": "AAPL", "exchangeName": "NMS", "instrumentType": "EQUITY", "firstTradeDate": 345479400,
                                                       "regularMarketTime": 1704387600, "gmtoffset": -18000, "timezone": "EST", "exchangeTimezoneName": "America/New_York",
                                                       "regularMarketPrice": 110, "chartPreviousClose": 100, "priceHint": 2, "dataGranularity": "1d",
                                                       "validRanges": ["1d", "5d", "1mo", "max"]},
                                              "timestamp": [1704205800, 1704292200, 1704378600],
                                              "indicators": {"quote": [{"open": [100, 0, 110], "high": [105, 0, 115], "low": [95, 0, 105], "close": [100, 0, 110],
                                                                        "volume": [9007199254740993, 0, 1200]}], "adjclose": [{"adjclose": [50, 0, 55]}]},
                                              "events": {"dividends": {"1704205800": {"amount": 0.5, "date": 1704205800}}}}]}}


def chart_routes(symbol="AAPL", body=CHART):
    return [{"path": f"/v8/finance/chart/{symbol}", "json": body}]


def test_the_file_keeps_zero_large_integers_and_the_exchange_time_zone(cli):
    run = cli("history", "AAPL", "--start", "2024-01-02", "--end", "2024-01-04", "--adjust", "none", routes=chart_routes())
    assert run.code == 0, run
    rows = run.rows
    assert [r["Date"] for r in rows] == ["2024-01-02T00:00:00-05:00", "2024-01-03T00:00:00-05:00"]
    assert [r["Close"] for r in rows] == ["100.0", "0.0"], "a zero close is kept as a zero, not dropped or blanked"
    assert [r["Volume"] for r in rows] == ["9007199254740993", "0"], "an integer past 2**53 keeps every digit"
    assert run.result()["as_of"]["timezone"] == "America/New_York" and run.result()["currency"] == "USD"
    inline = run.result()["data"]
    assert inline[0]["Date"] == "2024-01-02" and inline[0]["Volume"] == 9007199254740993


@pytest.mark.parametrize("adjust,open_,close", [("auto", 50, 50), ("back", 50, 100), ("none", 100, 100)])
def test_each_adjustment_keeps_its_own_meaning(cli, adjust, open_, close):
    run = cli("history", "AAPL", "--start", "2024-01-02", "--end", "2024-01-03", "--adjust", adjust, routes=chart_routes())
    assert run.code == 0, run
    assert (float(run.rows[0]["Open"]), float(run.rows[0]["Close"])) == (open_, close)
    assert any(f"--adjust {adjust}" in n for n in run.doc["notes"])


def test_actions_keep_only_dates_with_an_action_and_the_native_amount(cli):
    run = cli("history", "AAPL", "--period", "1mo", "--actions", routes=chart_routes())
    assert run.code == 0, run
    assert [(r["Date"][:10], float(r["Dividends"])) for r in run.rows] == [("2024-01-02", 0.5)]
    assert "Open" not in run.rows[0]


def test_the_inline_copy_rounds_prices_to_seven_digits_and_the_file_keeps_them_all(cli):
    body = {"chart": {**CHART["chart"], "result": [{**CHART["chart"]["result"][0],
                                                     "indicators": {"quote": [{"open": [123.456789123], "high": [124.0], "low": [120.0], "close": [123.456789123], "volume": [5]}],
                                                                    "adjclose": [{"adjclose": [123.456789123]}]}, "timestamp": [1704205800], "events": {}}]}}
    run = cli("history", "AAPL", "--start", "2024-01-02", "--end", "2024-01-03", "--adjust", "none", routes=chart_routes(body=body))
    assert run.code == 0, run
    assert run.result()["data"][0]["Close"] == 123.4568
    assert run.rows[0]["Close"] == "123.456789123"


def test_the_default_range_is_one_month(cli):
    run = cli("history", "AAPL", routes=chart_routes())
    assert run.code == 0, run
    assert run.receipt["request"]["period"] == "1mo"


def test_five_day_bars_cannot_be_repaired_and_are_refused_before_any_request(cli):
    run = cli("history", "AAPL", "--repair", "--interval", "5d", routes=[])
    assert run.code == 2, run
    error = run.result()["error"]
    assert error["code"] == "invalid" and "--repair" in error["fix"] and "--interval" in error["fix"]
    assert run.requests == []
