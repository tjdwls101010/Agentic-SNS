"""Selection: which end of a series a limit keeps, what a projection reaches, and what coverage admits it left out."""
import json

import pytest

from conftest import inflate, shape

META = {"currency": "USD", "symbol": "AAPL", "exchangeName": "NMS", "instrumentType": "EQUITY", "firstTradeDate": 345479400, "regularMarketTime": 1704387600,
        "gmtoffset": -18000, "timezone": "EST", "exchangeTimezoneName": "America/New_York", "regularMarketPrice": 110, "chartPreviousClose": 100,
        "priceHint": 2, "dataGranularity": "1d", "validRanges": ["1d", "5d", "1mo", "max"]}


def series_routes(n, symbol="AAPL"):
    """A daily series the source publishes oldest first, with each row's position as its Close."""
    stamps = [1577977800 + 86400 * i for i in range(n)]
    closes = [float(i) for i in range(n)]
    quote = {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000 + i for i in range(n)]}
    chart = {"chart": {"error": None, "result": [{"meta": dict(META, symbol=symbol), "timestamp": stamps, "indicators": {"quote": [quote], "adjclose": [{"adjclose": closes}]}, "events": {}}]}}
    return [{"path": f"/v8/finance/chart/{symbol}", "json": chart}]


def upgrades_routes(n):
    """Rating actions arrive newest first: the first row carries the latest date."""
    history = [{"epochGradeDate": 1767225600 - 86400 * i, "firm": f"Firm{i}", "toGrade": "Buy", "fromGrade": "Hold", "action": "up"} for i in range(n)]
    return [{"path": "/quoteSummary/AAPL", "params": {"modules": "upgradeDowngradeHistory"}, "json": {"quoteSummary": {"result": [{"upgradeDowngradeHistory": {"history": history}}]}}}]


def filings_routes(n):
    filings = [{"date": f"2026-01-{i % 28 + 1:02d}", "epochDate": 1767225600, "type": "8-K", "title": "t", "edgarUrl": "u", "exhibits": [{"type": "EX-99", "url": "x"}], "maxAge": 1} for i in range(n)]
    return [{"path": "/quoteSummary/AAPL", "params": {"modules": "secFilings"}, "json": {"quoteSummary": {"result": [{"secFilings": {"filings": filings}}]}}}]


def news_routes(count=10):
    items = [{"id": f"i{n}", "content": inflate(shape("news_item"), n)["content"]} for n in range(count)]
    return [{"path": "/xhr/ncp", "json": {"data": {"tickerStream": {"stream": items}}}}]


def closes(result):
    column = result["data"]["columns"].index("Close")
    return [row[column] for row in result["data"]["data"]]


# ---- B1: the limit keeps the wrong end, silently ------------------------------------------------------------------


def test_a_limit_on_an_oldest_first_series_keeps_the_newest_rows(cli):
    """Reproduces B1. `prices history --period 5y --limit 5` answered with 2021 and status ok: a prefix cut on a
    series published oldest first always returns the oldest fragment, and nothing in the result said so."""
    proc, doc = cli("prices", "history", "AAPL", "--period", "5y", "--adjust", "none", "--limit", "5", routes=series_routes(1255))
    assert proc.returncode == 0, proc.stdout[:400]
    r = doc["results"][0]
    assert closes(r) == [1250, 1251, 1252, 1253, 1254]
    assert r["coverage"] == {"received": 1255, "kept": "newest", "truncated_by": "explicit_limit", "shown": 5, "exhaustive": False}


def test_a_limit_on_a_newest_first_series_still_keeps_the_newest_rows(cli):
    """The control: `analysts upgrades` arrives newest first, so a prefix cut is already right there. A single global
    flip would regress this leaf while fixing the others."""
    proc, doc = cli("analysts", "upgrades", "AAPL", "--limit", "20", "--fields", "Firm", routes=upgrades_routes(971))
    assert proc.returncode == 0, proc.stdout[:400]
    r = doc["results"][0]
    assert [row[0] for row in r["data"]["data"]] == [f"Firm{i}" for i in range(20)]
    assert r["coverage"]["kept"] == "first"


@pytest.mark.parametrize("group,leaf,newest", [("prices", "history", True), ("prices", "actions", True), ("company", "shares", True),
                                               ("analysts", "history", True), ("analysts", "upgrades", False),
                                               ("holders", "insider-transactions", False), ("company", "filings", False)])
def test_schema_states_the_end_a_limit_keeps_as_measured_for_each_leaf(cli, group, leaf, newest):
    proc, doc = cli("schema", group, leaf)
    assert proc.returncode == 0
    keeps = doc["results"][0]["data"]["default_window"]["limit_keeps"]
    assert ("newest" in keeps) is newest, keeps


def test_coverage_names_the_cut_even_when_the_leaf_chose_it(cli):
    proc, doc = cli("company", "filings", "AAPL", routes=filings_routes(80))
    assert proc.returncode == 0, proc.stdout[:400]
    coverage = doc["results"][0]["coverage"]
    assert coverage["truncated_by"] == "leaf_default" and coverage["shown"] == 20 and coverage["exhaustive"] is False


def test_an_untruncated_result_says_so(cli):
    proc, doc = cli("prices", "history", "AAPL", "--period", "5d", routes=series_routes(3))
    coverage = doc["results"][0]["coverage"]
    assert coverage["exhaustive"] is True and "kept" not in coverage


# ---- paging: the window walks forward -----------------------------------------------------------------------------


def test_a_paged_read_walks_forward_instead_of_returning_the_same_tail(cli, tmp_path):
    """With the newest-end rule applied to a paged read, every --start returned the same newest rows: the counts
    summed to the whole series while the early rows were never shown once."""
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--period", "5y", "--adjust", "none", "--limit", "1", routes=series_routes(1000), store=store)
    ident = doc["results"][0]["id"]
    seen, start = [], 0
    while True:
        proc, page = cli("read", ident, "--fields", "Close", "--start", str(start), "--limit", "400", routes=[], store=store)
        assert proc.returncode == 0, proc.stdout[:400]
        r = page["results"][0]
        seen += closes(r)
        start += r["coverage"]["shown"]
        if start >= r["coverage"]["received"]:
            break
    assert seen == list(range(1000))


def test_a_start_past_the_end_is_refused_rather_than_returning_nothing(cli, tmp_path):
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--period", "5d", routes=series_routes(10), store=store)
    proc, back = cli("read", doc["results"][0]["id"], "--start", "10", routes=[], store=store)
    assert proc.returncode == 2
    assert "past the 10 rows" in back["results"][0]["error"]["message"]


# ---- projection ----------------------------------------------------------------------------------------------------


def test_a_dotted_path_reaches_a_nested_payload(cli):
    """company news nests its article under content, so only a dotted projection reduces it; a flat --fields could
    name nothing that worked, which is what made the old recovery sentence unfollowable."""
    proc, doc = cli("company", "news", "AAPL", "--fields", "content.title,content.provider.displayName", routes=news_routes())
    assert proc.returncode == 0, proc.stdout[:400]
    r = doc["results"][0]
    assert set(r["data"][0]) == {"content.title", "content.provider.displayName"}
    assert r["data"][0]["content.provider.displayName"] is not None
    assert r["coverage"]["fields"]["shown"] == 2 and r["coverage"]["fields"]["source"] == "requested"


def test_the_default_projection_drops_the_fields_measured_as_the_bulk(cli):
    proc, default = cli("company", "news", "AAPL", routes=news_routes())
    proc, whole = cli("company", "news", "AAPL", "--fields", "id,content", "--max-chars", "200000", routes=news_routes())
    first = default["results"][0]["data"][0]
    assert "content.thumbnail" not in first and "content.storyline" not in first
    assert len(json.dumps(default["results"][0]["data"])) < len(json.dumps(whole["results"][0]["data"])) / 2


def test_list_fields_names_the_dotted_paths_a_projection_can_use(cli):
    proc, doc = cli("company", "news", "AAPL", "--list-fields", routes=news_routes(1))
    listed = doc["results"][0]["data"]
    assert "content.title" in listed and "content.provider.displayName" in listed


def test_an_unknown_field_is_refused_with_where_to_look(cli):
    proc, doc = cli("prices", "history", "AAPL", "--period", "5d", "--fields", "Opne", routes=series_routes(3))
    assert proc.returncode == 2
    assert "--list-fields" in doc["results"][0]["error"]["message"]


def test_a_default_projection_never_fails_on_a_target_that_lacks_a_field(cli):
    """A default projection describes the common shape; a thinly reported instrument must not become an error."""
    routes = [{"path": "/quoteSummary/THIN", "json": {"quoteSummary": {"result": [{}], "error": None}}},
              {"path": "/v7/finance/quote", "json": {"quoteResponse": {"result": [{"symbol": "THIN", "currency": "USD"}], "error": None}}},
              {"path": "/timeseries/THIN", "json": {"timeseries": {"result": [], "error": None}}}]
    proc, doc = cli("prices", "quote", "THIN", routes=routes)
    assert proc.returncode == 0, proc.stdout[:400]
    r = doc["results"][0]
    assert r["data"]["symbol"] == "THIN" and r["data"]["currency"] == "USD"
    assert r["coverage"]["fields"]["shown"] == len(r["data"])


def test_a_table_slice_keeps_its_column_names_and_index(cli):
    """A generic JSON pointer into the encoded rows would return an unlabelled array; the leaf's own selector keeps
    the row labels attached to the rows."""
    proc, doc = cli("prices", "history", "AAPL", "--period", "5d", "--limit", "3", "--fields", "Close", routes=series_routes(10))
    data = doc["results"][0]["data"]
    assert data["columns"] == ["Close"] and data["index_names"] == ["Date"] and len(data["index"]) == 3


# ---- conditions -----------------------------------------------------------------------------------------------------


def calendar_route(rows, lte):
    columns = ["Symbol", "Company Name", "Market Cap (Intraday)", "Event Name", "Event Start Date", "EPS Estimate", "Reported EPS", "Surprise (%)"]
    route = {"path": "/v1/finance/visualization", "body": {"entityIdType": "sp_earnings"},
             "json": {"finance": {"result": [{"documents": [{"columns": [{"label": c, "type": "TIMESTAMP" if c == "Event Start Date" else "STRING"} for c in columns], "rows": rows}]}], "error": None}}}
    return route


def test_a_date_range_is_confirmed_from_the_rows_not_from_the_request(cli):
    rows = [["AAPL", "Apple", 100, "Earnings", "2026-10-01T21:00:00Z", 1, 1, 1], ["MSFT", "Microsoft", 100, "Earnings", "2026-10-01T21:00:00Z", 1, 1, 1]]
    proc, doc = cli("calendar", "earnings", "--start", "2026-10-01", "--end", "2026-10-01", routes=[calendar_route(rows, "2026-10-02")])
    found = doc["results"][0]["conditions"]["dates"]
    assert found["status"] == "confirmed" and found["evidence"]["outside"] == []


def test_a_row_outside_the_requested_range_reports_the_condition_as_not_applied(cli):
    rows = [["AAPL", "Apple", 100, "Earnings", "2026-11-20T21:00:00Z", 1, 1, 1]]
    proc, doc = cli("calendar", "earnings", "--start", "2026-10-01", "--end", "2026-10-01", routes=[calendar_route(rows, "2026-10-02")])
    found = doc["results"][0]["conditions"]["dates"]
    assert found["status"] == "not_applied" and found["evidence"]["outside"] == ["2026-11-20"]


def test_a_source_epoch_is_reported_in_the_same_form_as_every_other_time(cli):
    routes = [{"path": "/quoteSummary/AAPL", "json": {"quoteSummary": {"result": [{}], "error": None}}},
              {"path": "/v7/finance/quote", "json": {"quoteResponse": {"result": [{"symbol": "AAPL", "currency": "USD", "regularMarketTime": 1789761602}], "error": None}}},
              {"path": "/timeseries/AAPL", "json": {"timeseries": {"result": [], "error": None}}}]
    proc, doc = cli("prices", "quote", "AAPL", routes=routes)
    assert proc.returncode == 0, proc.stdout[:400]
    source_time = doc["results"][0]["source_time"]
    assert source_time.startswith("2026-") and source_time.endswith("+00:00")


# ---- the index is a field a reader can name ------------------------------------------------------------------------


def test_the_index_name_is_listed_and_accepted_as_a_field(cli):
    """A baseline session asked for --fields Date,Close and was refused: the date is the index, which the listing
    never named. It is always returned once, in index."""
    proc, doc = cli("prices", "history", "AAPL", "--period", "5d", "--list-fields", routes=series_routes(3))
    assert doc["results"][0]["data"][0] == "Date"
    proc, doc = cli("prices", "history", "AAPL", "--period", "5d", "--fields", "Date,Close", routes=series_routes(3))
    assert proc.returncode == 0, proc.stdout[:400]
    data = doc["results"][0]["data"]
    assert data["columns"] == ["Close"] and len(data["index"]) == 3


def test_naming_only_the_index_is_refused_with_what_to_do(cli):
    proc, doc = cli("prices", "history", "AAPL", "--period", "5d", "--fields", "Date", routes=series_routes(3))
    assert proc.returncode == 2
    assert "index is always returned" in doc["results"][0]["error"]["message"]
