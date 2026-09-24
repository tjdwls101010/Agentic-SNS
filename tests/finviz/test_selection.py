"""One selection rule for every collection: declared order, then --filter, local selectors, --start, the window, and --fields."""

import pytest

from pages import stock_overview, stock_section

STATEMENT = {"currency": "USD", "data": {"Period": ["TTM", "2025FY"], "Period End Date": ["", "10/31/2025"], "Total Revenue": ["7,372.00", "6,948.00"], "EPS (Diluted)": ["4.91", "4.57"]}}


def revision(period, kind, date, mean):
    return {"ticker": None, "fiscalPeriod": period, "estimateType": kind, "estimateDate": date + "T00:00:00", "estimates": 30, "mean": mean}


# Published oldest first, as the source does: the newest estimate of each period is at the end of its run.
REVISIONS = [revision("2023FY", "E", "2023-07-06", 5.99), revision("2023FY", "E", "2023-07-10", 6.01), revision("2023FY", "S", "2023-07-06", 380000.0), revision("2026Q4", "E", "2026-09-09", 1.97), revision("2026Q4", "E", "2026-09-17", 1.98), revision("2026Q4", "S", "2026-09-17", 113250.57)]


@pytest.mark.xfail(strict=True, reason="D3: the default revisions window is the oldest forty records")
def test_revisions_default_to_the_newest_estimate_of_each_period_and_type(client):
    client.add("https://finviz.com/stock?t=A&ty=ea", stock_section({"earningsDate": "2026-10-30T16:30:00", "earningsData": [], "earningsAnnualData": [], "earningsRevisionsData": REVISIONS, "priceReactionData": []}))
    result = client.one("stock", "earnings", "A", "--sections", "revisions")
    latest = {(r["fiscalPeriod"], r["estimateType"]): (r["estimateDate"], r["mean"]) for r in result["data"]["revisions"]}
    assert latest == {("2023FY", "E"): ("2023-07-10T00:00:00", 6.01), ("2023FY", "S"): ("2023-07-06T00:00:00", 380000.0), ("2026Q4", "E"): ("2026-09-17T00:00:00", 1.98), ("2026Q4", "S"): ("2026-09-17T00:00:00", 113250.57)}
    history = client.one("stock", "earnings", "A", "--sections", "revisions", "--fiscal-period", "2026Q4", "--filter", "E")
    assert [r["estimateDate"][:10] for r in history["data"]["revisions"] if r["estimateType"] == "E"] == ["2026-09-17", "2026-09-09"]


@pytest.mark.xfail(strict=True, reason="D5: --fields names statement rows, not periods")
def test_a_statement_is_selected_by_line_item_and_projected_by_period(client):
    client.add("https://finviz.com/api/statement?t=A&so=F&s=IA", STATEMENT)
    result = client.one("stock", "statement", "A", "--filter", "Revenue", "--fields", "TTM")
    assert result["data"]["items"] == [{"item": "Total Revenue", "TTM": "7,372.00"}]
    assert result["data"]["currency"] == "USD" and result["data"]["periods"] == ["TTM", "2025FY"]


@pytest.mark.xfail(strict=True, reason="D7: a headline under an earlier row's date loses it")
def test_overview_headlines_inherit_the_date_of_the_row_that_opened_their_day(client):
    news = (("Sep-14-26 04:30PM", "First of the day", "https://example.com/1", "A"), ("08:10PM", "Later that day", "https://example.com/2", "B"), ("Sep-13-26 09:00AM", "Day before", "https://example.com/3", "C"))
    client.add("https://finviz.com/stock?t=A&ty=c", stock_overview(news=news))
    rows = client.one("stock", "overview", "A", "--sections", "news", "--filter", "Later")["data"]["news"]
    assert rows == [{"date": "Sep-14-26", "time": "08:10PM", "title": "Later that day", "url": "https://example.com/2", "source": "B"}]


@pytest.mark.xfail(strict=True, reason="D8: a selection that matched nothing is reported as an empty source")
def test_a_selection_that_matches_nothing_is_ok_with_zero_matched(client):
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A"}, {"ticker": "AA"}])
    result = client.one("search", "A", "--filter", "ABSENT")
    assert result["status"] == "ok" and result["data"] == []
    assert result["coverage"]["received"] == 2 and result["coverage"]["matched"] == 0
    assert any("0" in w and "2" in w for w in result["warnings"])
