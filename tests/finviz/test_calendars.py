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
    assert "--date" not in season and "--page" not in season and "--sort" not in season
    economic = client.raw("calendar", "economic", "--help", code=0).stdout
    assert "--date" in economic and "--sort" in economic and "--page" not in economic
    assert client.one("calendar", "season", "--date", "2026-09-01", code=2)["error"]["code"] == "invalid_argument"
    refused = client.one("calendar", "economic", "--page", "2", code=2)
    assert "--page" in refused["error"]["message"] and "calendar economic --help" in refused["error"]["fix"]


def test_a_sort_echo_confirms_nothing_but_a_disagreeing_one_reports_not_applied(client):
    ignored = {"data": {"initialDateFrom": "2026-09-15", "initialSort": "earningsDate", "entries": {"items": [{"ticker": "A"}], "page": 1, "totalPages": 1}}}
    client.add("https://finviz.com/calendar/earnings?sort=marketCap", calendar_page(ignored))
    assert client.one("calendar", "earnings", "--sort", "marketCap")["conditions"]["sort"] == {"requested": "marketCap", "status": "not_applied", "evidence": {"source_sort": "earningsDate"}}
    repeated = {"data": {"initialDateFrom": "2026-09-15", "initialSort": "bogus", "entries": {"items": [{"ticker": "A"}], "page": 1, "totalPages": 1}}}
    client.add("https://finviz.com/calendar/earnings?sort=bogus", calendar_page(repeated))
    assert client.one("calendar", "earnings", "--sort", "bogus")["conditions"]["sort"] == {"requested": "bogus", "status": "unverified", "evidence": {"source_sort": "bogus"}}


def test_an_empty_calendar_is_empty_and_stays_empty_when_read(client):
    client.add("https://finviz.com/calendar/earnings", calendar_page({"data": {"initialDateFrom": "2026-09-15", "entries": {"items": [], "page": 1, "totalPages": 1, "totalItemsCount": 0}}}))
    empty = client.one("calendar", "earnings", code=7)
    assert empty["data"]["date_from"] == "2026-09-15" and empty["coverage"]["received"] == 0
    assert client.one("read", empty["id"], code=7)["status"] == "empty"
