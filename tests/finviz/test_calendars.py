from pages import calendar_page


def test_calendar_date_is_judged_by_the_sources_own_start_date_not_by_the_returned_items(client):
    entries = {"items": [{"ticker": "MU", "earningsDate": "2026-09-25T08:30:00"}], "page": 1, "totalPages": 1, "totalItemsCount": 1}
    client.add("https://finviz.com/calendar/earnings?dateFrom=2026-09-01", calendar_page({"data": {"initialDateFrom": "2026-09-18", "initialSort": "earningsDate", "entries": entries}}))
    result = client.one("calendar", "earnings", "--date", "2026-09-01")
    assert result["conditions"]["date"] == {"requested": "2026-09-01", "status": "not_applied", "evidence": {"source_date_from": "2026-09-18"}}
    assert result["data"]["date_from"] == "2026-09-18"
    client.add("https://finviz.com/calendar/earnings?dateFrom=2026-09-01&sort=-earningsDate", calendar_page({"data": {"initialDateFrom": "2026-09-01", "initialSort": "-earningsDate", "entries": entries}}))
    result = client.one("calendar", "earnings", "--date", "2026-09-01", "--sort=-earningsDate")
    assert result["conditions"]["date"]["status"] == "confirmed"
    assert result["conditions"]["sort"] == {"requested": "-earningsDate", "status": "unverified", "evidence": {"source_sort": "-earningsDate"}}
    client.add("https://finviz.com/api/calendar/earnings?dateFrom=2026-09-01&page=2&sort=earningsDate", dict(entries, page=2, totalPages=3))
    paged = client.one("calendar", "earnings", "--date", "2026-09-01", "--page", "2")
    assert paged["conditions"]["date"] == {"requested": "2026-09-01", "status": "unverified", "evidence": None}
    assert paged["conditions"]["page"]["status"] == "confirmed" and paged["data"].get("date_from") is None
    assert paged["next"] == "calendar earnings --date 2026-09-01 --page 3"


def test_calendar_pages_use_source_entries_and_name_the_next_page(client):
    entries = {"items": [{"ticker": "BIOX", "earningsDate": "2026-09-15T08:30:00", "isEarningDateEstimate": False, "epsEstimate": 0.07}], "page": 1, "pageSize": 100, "totalItemsCount": 5, "totalPages": 1}
    client.add("https://finviz.com/calendar/earnings", calendar_page({"data": {"initialDateFrom": "2026-09-15", "initialSort": "earningsDate", "entries": entries}}))
    result = client.one("calendar", "earnings")
    assert result["data"] == {"date_from": "2026-09-15", "items": entries["items"]}
    assert result["coverage"] == {"received": 1, "matched": 1, "shown": 1, "start": 0, "source_total": 5} and "next" not in result
    economic = [{"calendarId": 1, "event": "Monthly Budget Statement", "date": "2026-09-11T14:00:00", "actual": "-$167B"}]
    client.add("https://finviz.com/calendar/economic", calendar_page({"data": {"initialDateFrom": "2026-09-14", "entries": economic}}))
    assert client.one("calendar", "economic")["data"]["items"] == economic
    client.add("https://finviz.com/calendar/dividends", calendar_page({"data": {"initialDateFrom": "2026-09-15", "entries": dict(entries, totalPages=7, totalItemsCount=304)}}))
    client.add("https://finviz.com/api/calendar/dividends?dateFrom=2026-09-15&page=2", dict(entries, items=[{"ticker": "CX", "exdate": "2026-09-15"}], page=2, totalPages=7, totalItemsCount=304))
    result = client.one("calendar", "dividends", "--page", "2")
    assert result["data"]["items"] == [{"ticker": "CX", "exdate": "2026-09-15"}] and result["data"]["date_from"] == "2026-09-15"
    assert result["coverage"]["source_total"] == 304 and result["next"] == "calendar dividends --page 3" and result["conditions"]["page"]["status"] == "confirmed"
    client.add("https://finviz.com/calendar/earnings/season-preview", calendar_page({"data": {"initialDateFrom": "2026-09-14", "entries": [{"date": "2026-09-30", "ticker": "MU"}], "totalsPerDay": {"2026-09-30": 3}, "totalCount": 64}}))
    result = client.one("calendar", "season")
    assert result["data"]["items"] == [{"date": "2026-09-30", "ticker": "MU"}] and result["data"]["totals_per_day"] == {"2026-09-30": 3} and result["coverage"]["source_total"] == 64


def test_each_calendar_takes_only_the_arguments_it_accepts(client):
    season = client.raw("calendar", "season", "--help", code=0).stdout
    assert "--date" in season and "--day" in season and "--page" not in season and "--sort" not in season
    economic = client.raw("calendar", "economic", "--help", code=0).stdout
    assert "--date" in economic and "--sort" in economic and "--page" not in economic
    assert client.one("calendar", "season", "--sort", "ticker", code=2)["error"]["code"] == "invalid_argument"
    assert client.one("calendar", "earnings", "--sort", "bogus", code=2)["error"]["code"] == "invalid_argument"
    assert "-yield" in client.one("schema", "calendar", "dividends")["data"]["arguments"]["--sort"]["choices"]
    refused = client.one("calendar", "economic", "--page", "2", code=2)
    assert "--page" in refused["error"]["message"] and "calendar economic --help" in refused["error"]["fix"]


def test_a_sort_echo_confirms_nothing_but_a_disagreeing_one_reports_not_applied(client):
    ignored = {"data": {"initialDateFrom": "2026-09-15", "initialSort": "earningsDate", "entries": {"items": [{"ticker": "A"}], "page": 1, "totalPages": 1}}}
    client.add("https://finviz.com/calendar/earnings?sort=marketCap", calendar_page(ignored))
    assert client.one("calendar", "earnings", "--sort", "marketCap")["conditions"]["sort"] == {"requested": "marketCap", "status": "not_applied", "evidence": {"source_sort": "earningsDate"}}
    repeated = {"data": {"initialDateFrom": "2026-09-15", "initialSort": "-ticker", "entries": {"items": [{"ticker": "A"}], "page": 1, "totalPages": 1}}}
    client.add("https://finviz.com/calendar/earnings?sort=-ticker", calendar_page(repeated))
    assert client.one("calendar", "earnings", "--sort=-ticker")["conditions"]["sort"] == {"requested": "-ticker", "status": "unverified", "evidence": {"source_sort": "-ticker"}}


def test_an_empty_calendar_is_empty_and_stays_empty_when_read(client):
    client.add("https://finviz.com/calendar/earnings", calendar_page({"data": {"initialDateFrom": "2026-09-15", "entries": {"items": [], "page": 1, "totalPages": 1, "totalItemsCount": 0}}}))
    empty = client.one("calendar", "earnings", code=7)
    assert empty["data"]["date_from"] == "2026-09-15" and empty["coverage"]["received"] == 0
    assert client.one("read", empty["id"], code=7)["status"] == "empty"


def test_one_economic_series_reads_its_history_newest_first_and_its_releases(client):
    detail = {"ticker": "FDTR", "category": "Interest Rate", "description": "Fed funds rate.", "table": [{"calendarId": 390605, "ticker": "FDTR", "event": "Fed Interest Rate Decision", "date": "2026-10-28T14:00:00", "previous": "4%"}], "chartData": [{"actual": 0.5, "estimate": None, "refDate": "2016-10-31", "reference": None}, {"actual": 0.75, "estimate": None, "refDate": "2016-12-14", "reference": None}], "frequency": 0, "chartUnit": "percent", "chartSource": "Federal Reserve", "chartSourceUrl": "https://www.federalreserve.gov"}
    client.add("https://finviz.com/api/calendar/economic/detail?ticker=FDTR", detail)
    result = client.one("calendar", "event", "FDTR")
    assert result["data"]["history"] == detail["chartData"][::-1] and result["data"]["other_sections"] == {"releases": 1}
    assert result["data"]["unit"] == "percent" and result["conditions"]["ticker"] == {"requested": "FDTR", "status": "confirmed", "evidence": "FDTR"}
    assert client.one("read", result["id"], "--section", "releases")["data"]["releases"] == detail["table"]
    client.add("https://finviz.com/api/calendar/economic/detail?ticker=FDTR&dateFrom=2025-01-01", dict(detail, chartData=detail["chartData"][1:]))
    assert len(client.one("calendar", "event", "FDTR", "--date", "2025-01-01")["data"]["history"]) == 1


def test_the_season_preview_reads_one_whole_day_or_starts_at_a_date(client):
    day = [{"date": "2026-09-30", "ticker": "MU", "company": "Micron Technology Inc", "marketCap": 1210573.85}, {"date": "2026-09-30", "ticker": "JBL", "company": "Jabil Inc"}]
    client.add("https://finviz.com/api/calendar/earnings/season-preview/day?date=2026-09-30", day)
    result = client.one("calendar", "season", "--day", "2026-09-30")
    assert result["data"]["items"] == day and result["conditions"]["day"] == {"requested": "2026-09-30", "status": "confirmed", "evidence": ["2026-09-30"]}
    client.add("https://finviz.com/calendar/earnings/season-preview?dateFrom=2026-10-05", calendar_page({"data": {"initialDateFrom": "2026-10-05", "entries": [], "totalsPerDay": {}}}))
    assert client.one("calendar", "season", "--date", "2026-10-05", code=7)["conditions"]["date"]["status"] == "confirmed"
