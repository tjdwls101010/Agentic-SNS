"""How much of the source a result covers, and which requested conditions the returned rows confirm.

A list Yahoo truncates (the largest holders, the first page of news) says so in coverage; a count sent to the source comes back as requested beside received, with the shortfall warning where a short page is not the end; a paged source names the next offset. Conditions are judged from the rows that came back, never from the arguments sent.
"""
import pytest

from conftest import recorded


@pytest.mark.parametrize("argv,fixture,statement", [
    (["holders", "institutional", "AAPL"], "holders-institutional-aapl", "the largest institutional holders Yahoo lists, not every holder"),
    (["holders", "insider-transactions", "AAPL"], "holders-insider-transactions-aapl", "Yahoo's recent insider transactions, newest first, not every filing"),
    (["search", "apple"], "search-quotes", "the first page of Yahoo's matches, not every match"),
    (["fund", "holdings", "QQQ"], "fund-holdings-qqq", "the top holdings Yahoo lists, which need not cover the whole portfolio"),
    (["company", "filings", "AAPL"], "company-filings-aapl", "the SEC filings Yahoo currently lists for the symbol, newest first; Form 4 and older filings may be absent"),
])
def test_a_truncated_list_says_what_it_covers(cli, argv, fixture, statement):
    run = cli(*argv, routes=recorded(fixture))
    assert run.code == 0, run
    assert run.result()["coverage"]["statement"] == statement


def test_a_short_page_reports_both_counts_and_does_not_claim_the_end(cli):
    run = cli("company", "news", "AAPL", "--limit", "50", routes=recorded("company-news-aapl"))
    assert run.code == 0, run
    coverage = run.result()["coverage"]
    assert coverage["requested"] == 50 and coverage["received"] == 46   # the recorded page holds 46 entries
    assert "shortfall" in run.result()["warnings"]
    text = {w["code"]: w["text"] for w in run.doc["warnings"]}["shortfall"]
    assert "46" in text and "50" in text and "does not mean" in text


def test_a_paged_screen_names_the_next_offset_and_says_pages_move(cli):
    query = '{"operator":"AND","operands":[{"operator":"EQ","operands":["region","us"]},{"operator":"GT","operands":["intradaymarketcap",10000000000]},{"operator":"GT","operands":["quarterlyrevenuegrowth.quarterly",0.2]}]}'
    run = cli("screen", "run", "--query", query, "--limit", "25", routes=recorded("screen-run-growth"))
    assert run.code == 0, run
    coverage = run.result()["coverage"]
    assert (coverage["requested"], coverage["received"], coverage["total"], coverage["next_offset"]) == (25, 25, 585, 25)
    assert "pages_move" in run.result()["warnings"]
    conditions = run.result()["conditions"]
    assert conditions["offset"]["status"] == "confirmed"
    assert conditions["sort"]["status"] == "confirmed"  # ZTOEF, ZTO, ZS, ZBRA, ... descending by ticker


def test_a_full_calendar_page_names_the_next_offset(cli):
    run = cli("calendar", "economic", "--start", "2026-10-05", "--end", "2026-10-09", "--limit", "25", routes=recorded("calendar-economic"))
    assert run.code == 0, run
    coverage = run.result()["coverage"]
    assert (coverage["requested"], coverage["received"], coverage["next_offset"]) == (25, 25, 25)


def test_a_single_day_calendar_confirms_its_range_from_the_rows(cli):
    run = cli("calendar", "earnings", "--start", "2026-10-01", "--end", "2026-10-01", routes=recorded("calendar-earnings-day"))
    assert run.code == 0, run
    dates = run.result()["conditions"]["dates"]
    assert dates["status"] == "confirmed" and dates["evidence"]["range"] == ["2026-10-01", "2026-10-01"]
    assert run.result()["rows"] == 13
    assert "next_offset" not in run.result()["coverage"], "13 rows of 100 asked for is the whole day"


def test_history_confirms_its_dates_from_the_bars(cli):
    run = cli("history", "AAPL", "--start", "2026-09-28", "--end", "2026-10-03", "--adjust", "none", routes=recorded("history-aapl"))
    assert run.code == 0, run
    dates = run.result()["conditions"]["dates"]
    assert dates["status"] == "confirmed" and dates["evidence"]["range"] == ["2026-09-28", "2026-10-02"]


def test_an_ipo_range_is_unverified_because_three_dates_can_match(cli):
    run = cli("calendar", "ipo", "--start", "2026-10-05", "--end", "2026-10-09", routes=recorded("calendar-ipo"))
    assert run.code == 0, run
    assert run.result()["conditions"]["dates"]["status"] == "unverified"


# ---- the screen query, judged row by row in three-valued logic --------------------------------------------------------

def screen(rows):
    return [{"path": "/v1/finance/screener", "json": {"finance": {"result": [{"quotes": rows, "total": len(rows), "start": 0, "count": len(rows)}], "error": None}}}]


def row(symbol, region="US", change=None, cap=None):
    found = {"symbol": symbol, "region": region, "currency": "USD"}
    if change is not None:
        found["regularMarketChangePercent"] = change  # percent on Yahoo's scale: 2.0 is 2%
    if cap is not None:
        found["marketCap"] = cap
    return found


def judged(cli, query, rows):
    run = cli("screen", "run", "--query", query, routes=screen(rows))
    assert run.code == 0, run
    return run.result()["conditions"]["query"], run


def test_an_and_query_with_one_failing_row_is_not_applied(cli):
    query = '{"operator":"AND","operands":[{"operator":"EQ","operands":["region","us"]},{"operator":"GT","operands":["percentchange",0.01]}]}'
    found, _ = judged(cli, query, [row("A", change=2.0), row("B", change=0.5)])
    assert found["status"] == "not_applied"
    assert (found["evidence"]["rows_true"], found["evidence"]["rows_false"], found["evidence"]["rows_unknown"]) == (1, 1, 0)


def test_an_or_query_holds_when_one_branch_holds(cli):
    query = '{"operator":"OR","operands":[{"operator":"GT","operands":["percentchange",0.05]},{"operator":"EQ","operands":["region","us"]}]}'
    found, run = judged(cli, query, [row("A", change=0.5), row("B", change=9.0, region="GB")])
    assert found["status"] == "confirmed" and found["evidence"]["rows_true"] == 2
    assert "sample_only" in run.result()["warnings"], "confirmed is about the returned rows, not the whole market"


def test_a_nested_query_with_an_unchecked_field_is_unverified(cli):
    query = ('{"operator":"AND","operands":[{"operator":"OR","operands":[{"operator":"EQ","operands":["region","us"]},{"operator":"EQ","operands":["region","gb"]}]},'
             '{"operator":"GT","operands":["intradaymarketcap",1000]},{"operator":"GT","operands":["returnonequity.lasttwelvemonths",0.1]}]}')
    found, _ = judged(cli, query, [row("A", cap=5000), row("B", cap=9000)])
    assert found["status"] == "unverified"
    assert found["evidence"]["rows_unknown"] == 2 and found["evidence"]["unchecked_fields"] == ["returnonequity.lasttwelvemonths"]


def test_a_row_failing_a_checkable_part_is_false_even_when_another_part_is_unknown(cli):
    query = '{"operator":"AND","operands":[{"operator":"GT","operands":["intradaymarketcap",1000]},{"operator":"GT","operands":["returnonequity.lasttwelvemonths",0.1]}]}'
    found, _ = judged(cli, query, [row("A", cap=500)])
    assert found["status"] == "not_applied" and found["evidence"]["rows_false"] == 1


def test_an_empty_result_confirms_nothing(cli):
    run = cli("screen", "run", "--query", '{"operator":"EQ","operands":["region","us"]}', routes=screen([]))
    assert run.code == 7 and run.result()["status"] == "empty", run
    assert run.result()["conditions"]["query"]["status"] == "unverified"
    assert run.result()["warnings"] == []
