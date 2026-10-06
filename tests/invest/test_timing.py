"""When a value was true: the last bar's verdict moves with the observation time alone, and the quote reports each source time it carries.

The chart below is synthetic: the session Yahoo reports as current is 2024-01-04 09:30-16:00 New York (14:30-21:00 UTC), the last daily bar is that day's, and the last trade is at 15:30 New York. Only $YF_FIXTURE_NOW changes between cases, so each verdict is read from the observation time against the session end, never from the last trade.
"""
import datetime as dt

import pytest

from conftest import recorded

SESSION = (1704378600, 1704402000)  # 2024-01-04 14:30Z and 21:00Z
DAY_BARS = [1704205800, 1704292200, 1704378600]  # 2024-01-02, 01-03, 01-04 at the open


def chart(timestamps, session=SESSION, granularity="1d", last_trade=1704400200, zone=("America/New_York", "EST", -18000)):
    meta = {"currency": "USD", "symbol": "AAPL", "exchangeName": "NMS", "instrumentType": "EQUITY", "firstTradeDate": 345479400,
            "regularMarketTime": last_trade, "gmtoffset": zone[2], "timezone": zone[1], "exchangeTimezoneName": zone[0],
            "regularMarketPrice": 110, "chartPreviousClose": 100, "priceHint": 2, "dataGranularity": granularity, "validRanges": ["1d", "5d", "1mo", "max"]}
    if session:
        regular = {"timezone": zone[1], "start": session[0], "end": session[1], "gmtoffset": zone[2]}
        meta["currentTradingPeriod"] = {"pre": regular, "regular": regular, "post": regular}
        meta["tradingPeriods"] = [[regular]]  # Yahoo sends the day's periods with intraday bars
    n = len(timestamps)
    quote = {"open": [100.0] * n, "high": [105.0] * n, "low": [95.0] * n, "close": [100.0 + i for i in range(n)], "volume": [1000] * n}
    return [{"path": "/v8/finance/chart/AAPL", "json": {"chart": {"error": None, "result": [{"meta": meta, "timestamp": timestamps,
                                                                                             "indicators": {"quote": [quote], "adjclose": [{"adjclose": quote["close"]}]}}]}}}]


def instant(text):
    return dt.datetime.fromisoformat(text)


def verdict(cli, now, routes, *extra):
    run = cli("history", "AAPL", "--period", "5d", *extra, routes=routes, now=now)
    assert run.code == 0, run
    result = run.result()
    return result["as_of"]["last_bar_status"], [w for w in result["warnings"]], run


@pytest.mark.parametrize("now,expected", [
    ("2024-01-04T15:00:00+00:00", "provisional"),   # 10:00 New York, the session open
    ("2024-01-04T21:30:00+00:00", "final"),         # 16:30 New York, after the close
    ("2024-01-05T01:00:00+00:00", "final"),         # 10:00 on 01-05 in Seoul, still 20:00 on 01-04 in New York, after its close
])
def test_a_daily_bar_is_final_only_after_its_session_closes(cli, now, expected):
    status, warnings, run = verdict(cli, now, chart(DAY_BARS))
    assert status == expected
    assert ("last_bar_provisional" in warnings) is (expected == "provisional")
    assert run.result()["as_of"]["last_bar"].startswith("2024-01-04")
    session = run.result()["as_of"]["session"]
    assert instant(session["start"]) == instant("2024-01-04T14:30:00+00:00") and instant(session["end"]) == instant("2024-01-04T21:00:00+00:00")


def test_a_last_trade_before_the_close_does_not_make_the_bar_provisional_after_it(cli):
    """A thin stock last traded at 15:30; observed at 16:30 its bar is final, whatever the last trade time says."""
    status, _, run = verdict(cli, "2024-01-04T21:30:00+00:00", chart(DAY_BARS, last_trade=1704400200))
    assert status == "final"
    assert instant(run.result()["as_of"]["regularMarketTime"]) == instant("2024-01-04T20:30:00+00:00")


def test_an_asian_session_is_judged_in_its_own_time_zone(cli):
    """Tokyo's 2024-01-04 session runs 00:00-06:30 UTC and its daily bar is dated at midnight Tokyo time, 15:00 UTC the day before; read in UTC the bar would look a day older than the session."""
    tokyo = ("Asia/Tokyo", "JST", 32400)
    session = (1704326400, 1704349800)  # 2024-01-04 00:00Z and 06:30Z
    bars = [1704153600, 1704240000, 1704326400]  # the 01-02, 01-03 and 01-04 opens, 09:00 Tokyo
    status, warnings, _ = verdict(cli, "2024-01-04T03:00:00+00:00", chart(bars, session=session, last_trade=1704337200, zone=tokyo))
    assert status == "provisional" and "last_bar_provisional" in warnings
    status, _, _ = verdict(cli, "2024-01-04T07:00:00+00:00", chart(bars, session=session, last_trade=1704337200, zone=tokyo))
    assert status == "final"


def test_a_bar_from_before_the_current_session_is_final(cli):
    """The session Yahoo reports is the next day's (a weekend or holiday in between does the same), so the 01-04 bar is closed."""
    next_session = (1704465000, 1704488400)  # 2024-01-05 14:30Z-21:00Z
    status, warnings, _ = verdict(cli, "2024-01-05T15:00:00+00:00", chart(DAY_BARS, session=next_session))
    assert status == "final" and warnings == []


def test_without_a_reported_session_the_verdict_is_unknown_not_final(cli):
    status, warnings, run = verdict(cli, "2024-01-04T21:30:00+00:00", chart(DAY_BARS, session=None))
    assert status == "unknown"
    assert "last_bar_unknown" in warnings
    assert "session" in run.result()["as_of"]["reason"]


@pytest.mark.parametrize("interval,timestamps,now,expected", [
    ("1wk", [1703480400, 1704085200], "2024-01-04T15:00:00+00:00", "provisional"),   # week of 2024-01-01, still running
    ("1wk", [1703480400, 1704085200], "2024-01-09T15:00:00+00:00", "final"),
    ("1mo", [1701388800, 1704085200], "2024-01-15T15:00:00+00:00", "provisional"),   # January 2024, still running
    ("1mo", [1701388800, 1704085200], "2024-02-02T15:00:00+00:00", "final"),
    ("5m", [1704378600, 1704378900], "2024-01-04T14:37:00+00:00", "provisional"),   # the 14:35 bar runs to 14:40
    ("5m", [1704378600, 1704378900], "2024-01-04T14:41:00+00:00", "final"),
])
def test_longer_and_intraday_bars_are_final_once_their_span_ends(cli, interval, timestamps, now, expected):
    status, _, _ = verdict(cli, now, chart(timestamps, granularity=interval), "--interval", interval)
    assert status == expected


def test_the_quote_reports_market_state_and_each_source_time(cli):
    run = cli("quote", "KO", routes=recorded("quote-ko"))
    assert run.code == 0, run
    as_of = run.result()["as_of"]
    assert as_of["market_state"] == "PREPRE"
    assert as_of["regularMarketTime"] == "2026-10-05T20:00:02+00:00"   # raw 1791230402
    assert as_of["postMarketTime"] == "2026-10-05T23:57:52+00:00"      # raw 1791244672
    assert "preMarketTime" not in as_of, "a time the response does not carry is not invented"
    assert any("do not share one time" in n for n in run.doc["notes"])
