"""Search, screen, market and calendar: what each reads, the query checks made before any request, and the calendar's zero loss, scope and paging.

Synthetic routes are examples of each endpoint's shape; recorded ones are Yahoo's own answers.
"""
import json

import pytest

from conftest import recorded


def test_search_returns_reusable_symbols_from_the_first_page(cli):
    routes = [{"path": "/v1/finance/lookup", "params": {"query": "apple", "type": "equity", "start": 0, "count": 1},
               "json": {"finance": {"result": [{"documents": [{"symbol": "AAPL", "shortName": "Apple Inc.", "quoteType": "EQUITY", "currency": "USD"}]}], "error": None}}}]
    run = cli("search", "apple", "--type", "stock", "--limit", "1", routes=routes)
    assert run.code == 0, run
    assert run.rows[0]["symbol"] == "AAPL" and run.rows[0]["shortName"] == "Apple Inc."
    assert run.result()["coverage"]["requested"] == 1 and "next_offset" not in run.result()["coverage"]


def test_search_research_sends_no_count(cli):
    routes = [{"path": "/v1/finance/search", "json": {"quotes": [], "news": [], "lists": [], "researchReports": [{"id": "r1", "reportTitle": "t"}], "nav": []}}]
    run = cli("search", "apple", "--dataset", "research", routes=routes)
    assert run.code == 0, run
    assert run.records[0]["data"] == [{"id": "r1", "reportTitle": "t"}]
    assert "requested" not in run.result()["coverage"]


def test_search_type_filters_instrument_candidates_only(cli):
    run = cli("search", "apple", "--dataset", "news", "--type", "etf", routes=[])
    assert run.code == 2 and "--dataset quotes" in run.result()["error"]["message"], run


def test_screen_catalogs_narrow_by_field_and_text(cli):
    fields = cli("screen", "fields", "--filter", "intradaymarketcap", routes=[])
    assert fields.code == 0, fields
    assert [r["field"] for r in fields.rows] == ["intradaymarketcap"]
    values = cli("screen", "values", "--field", "region", "--filter", "us", routes=[])
    assert values.code == 0, values
    assert "us" in values.records[0]["data"]["region"]


def test_screen_run_sends_offset_and_limit_and_names_the_next_page(cli):
    query = '{"operator":"AND","operands":[{"operator":"EQ","operands":["region","us"]},{"operator":"GT","operands":["intradaymarketcap",2000000000]}]}'
    routes = [{"path": "/v1/finance/screener", "body": {"query": json.loads(query), "offset": 2, "size": 1},
               "json": {"finance": {"result": [{"quotes": [{"symbol": "AAPL", "marketCap": 9007199254740993, "currency": "USD", "region": "US"}], "total": 5, "start": 2, "count": 1}], "error": None}}}]
    run = cli("screen", "run", "--query", query, "--offset", "2", "--limit", "1", routes=routes)
    assert run.code == 0, run
    assert run.rows[0]["symbol"] == "AAPL" and run.rows[0]["marketCap"] == "9007199254740993"
    assert run.result()["coverage"]["next_offset"] == 3
    assert run.result()["conditions"]["query"]["status"] == "confirmed"


def test_a_preset_runs_its_own_universe_and_sort(cli):
    routes = [{"path": "/v1/finance/screener", "body": {"quoteType": "ETF", "sortField": "percentchange", "sortType": "DESC"},
               "json": {"finance": {"result": [{"quotes": [{"symbol": "SPY", "currency": "USD"}], "total": 1}], "error": None}}}]
    run = cli("screen", "run", "--preset", "top_etfs_us", routes=routes)
    assert run.code == 0, run
    source = run.receipt["results"][0]["source"]
    assert (source["type"], source["sort"], source["ascending"]) == ("etf", "percentchange", False)


def test_a_preset_refuses_a_type_of_its_own(cli):
    run = cli("screen", "run", "--preset", "top_etfs_us", "--type", "equity", routes=[])
    assert run.code == 2, run


@pytest.mark.parametrize("kind,query,quote_type", [("equity", '{"operator":"IS-IN","operands":["region","us","gb"]}', "EQUITY"),
                                                   ("fund", '{"operator":"EQ","operands":["exchange","NAS"]}', "MUTUALFUND"),
                                                   ("etf", '{"operator":"BTWN","operands":["intradayprice",10,20]}', "ETF")])
def test_each_universe_and_operator_form_reaches_the_screener(cli, kind, query, quote_type):
    routes = [{"path": "/v1/finance/screener", "body": {"quoteType": quote_type}, "json": {"finance": {"result": [{"quotes": [{"symbol": "EX", "currency": "USD"}]}], "error": None}}}]
    run = cli("screen", "run", "--type", kind, "--query", query, routes=routes)
    assert run.code == 0, run
    assert run.rows[0]["symbol"] == "EX"


@pytest.mark.parametrize("query,message", [('{"operator":"BTWN","operands":["intradayprice",20,10]}', "lower bound"),
                                           ('{"operator":"EQ","operands":["region",true]}', "not a boolean"),
                                           ('{"operator":"EQ"}', "operator and operands"), ('{"operator":', "JSON")])
def test_a_malformed_query_is_refused_before_any_request(cli, query, message):
    run = cli("screen", "run", "--query", query, routes=[])
    assert run.code == 2, run
    assert message in run.result()["error"]["message"] + run.result()["error"]["fix"]
    assert run.requests == []


def test_the_preset_catalog_follows_the_universe(cli):
    run = cli("screen", "presets", "--type", "etf", routes=[])
    assert run.code == 0, run
    names = [p["name"] for p in run.records[0]["data"]]
    assert "top_etfs_us" in names and "most_actives" not in names


@pytest.mark.parametrize("argv,named", [(["screen", "run", "--preset", "nope"], "day_gainers"), (["market", "sector", "nope"], "technology"),
                                        (["market", "sector", "technology", "--region", "ZZ"], "KR")])
def test_a_value_outside_a_small_closed_set_is_refused_with_the_set(cli, argv, named):
    run = cli(*argv, routes=[])
    assert run.code == 2, run
    assert named in run.result()["error"]["message"]


def test_sector_industries_carry_reusable_keys(cli):
    route = {"path": "/v1/finance/sectors/technology", "json": {"data": {"name": "Technology", "symbol": "XLK", "overview": {"companiesCount": 10, "marketWeight": {"raw": 0.3}},
                                                                         "industries": [{"key": "semiconductors", "name": "Semiconductors", "symbol": "^SOX", "marketWeight": {"raw": 0.2}}]}}}
    run = cli("market", "sector", "technology", "--dataset", "industries", routes=[route])
    assert run.code == 0, run
    assert run.rows[0]["key"] == "semiconductors" and float(run.rows[0]["market weight"]) == 0.2


@pytest.mark.parametrize("dataset", ["overview", "top-companies", "research-reports", "top-performing", "top-growth"])
def test_each_industry_part_is_read(cli, dataset):
    data = {"name": "Semiconductors", "symbol": "^SOX", "sectorKey": "technology", "sectorName": "Technology", "overview": {"companiesCount": 10},
            "topCompanies": [{"symbol": "EX", "name": "Example"}], "researchReports": [{"id": "r1"}], "topPerformingCompanies": [{"symbol": "EX", "name": "Example"}],
            "topGrowthCompanies": [{"symbol": "EX", "name": "Example"}]}
    run = cli("market", "industry", "semiconductors", "--dataset", dataset, routes=[{"path": "/v1/finance/industries/semiconductors", "json": {"data": data}}])
    assert run.code == 0, run
    if dataset == "overview":
        assert run.records[0]["data"]["companies_count"] == 10
    elif dataset == "research-reports":
        assert run.records[0]["data"] == [{"id": "r1"}]
    else:
        assert run.rows[0]["symbol"] == "EX"


def calendar_route(kind, columns, rows, size=1):
    return {"path": "/v1/finance/visualization", "body": {"entityIdType": kind, "size": size, "offset": 0},
            "json": {"finance": {"result": [{"documents": [{"columns": [{"label": label, "type": "TIMESTAMP" if label == "Event Start Date" else "STRING"} for label in columns],
                                                            "rows": rows}]}], "error": None}}}


EARNINGS = ["Symbol", "Company Name", "Market Cap (Intraday)", "Event Name", "Event Start Date", "EPS Estimate", "Reported EPS", "Surprise (%)"]


def test_market_earnings_asks_for_the_day_after_an_inclusive_end_and_loses_zeros(cli):
    """Yahoo excludes its own end date, so --start D --end D sends D and D+1; yfinance turns zeros into nulls."""
    route = calendar_route("sp_earnings", EARNINGS, [["AAPL", "Apple", 100, "Earnings", "2024-01-25T21:00:00Z", 0, 0, 0]])
    route["body"]["query"] = {"operator": "AND", "operands": [{"operator": "EQ", "operands": ["region", "us"]},
                                                             {"operator": "OR", "operands": [{"operator": "EQ", "operands": ["eventtype", "EAD"]}, {"operator": "EQ", "operands": ["eventtype", "ERA"]}]},
                                                             {"operator": "GTE", "operands": ["startdatetime", "2024-01-25"]}, {"operator": "LTE", "operands": ["startdatetime", "2024-01-26"]}]}
    run = cli("calendar", "earnings", "--start", "2024-01-25", "--end", "2024-01-25", "--limit", "1", routes=[route])
    assert run.code == 0, run
    row = run.rows[0]
    assert row["Symbol"] == "AAPL" and (row["EPS Estimate"], row["Reported EPS"], row["Surprise(%)"]) == ("", "", ""), "Yahoo's zeros arrive as nulls"
    assert "zero_as_null" in run.result()["warnings"]


def test_a_short_calendar_page_is_complete_without_a_next_offset(cli):
    route = calendar_route("sp_earnings", EARNINGS, [["AAPL", "Apple", 100, "Earnings", "2024-01-25T21:00:00Z", 1, 2, 3]], size=100)
    run = cli("calendar", "earnings", "--start", "2024-01-25", "--end", "2024-01-25", routes=[route])
    assert run.code == 0, run
    coverage = run.result()["coverage"]
    assert (coverage["requested"], coverage["received"]) == (100, 1) and "next_offset" not in coverage
    assert "shortfall" not in run.result()["warnings"]


@pytest.mark.parametrize("kind,entity,columns,row,field,expected", [
    ("economic", "economic_event", ["Event", "Country Code", "Event Time", "Actual", "Market Expectation", "Prior to This", "Revised from"],
     ["Jobs", "US", "2024-01-25T13:30:00Z", 0, 1, 2, 0], "Expected", "1.0"),
    ("ipo", "ipo_info", ["Symbol", "Exchange Short Name", "Filing Date", "Date", "Amended Date", "Price From", "Price To", "Price", "Shares"],
     ["NEW", "NYQ", "2024-01-20", "2024-01-25", "2024-01-23", 0, 10, 0, 0], "Price To", "10.0"),
    ("splits", "splits", ["Symbol", "Payable On", "Optionable?", "Old Share Worth", "Share Worth"], ["AAPL", "2024-01-25", True, 1, 2], "Share Worth", "2"),
])
def test_other_calendars_keep_their_columns_and_judge_their_dates(cli, kind, entity, columns, row, field, expected):
    run = cli("calendar", kind, "--start", "2024-01-25", "--end", "2024-01-25", "--limit", "1", routes=[calendar_route(entity, columns, [row])])
    assert run.code == 0, run
    assert run.rows[0][field].removesuffix(".0") == expected.removesuffix(".0")
    status = run.result()["conditions"]["dates"]["status"]
    assert status == ("unverified" if kind == "ipo" else "confirmed")


@pytest.mark.parametrize("missing_first", [True, False])
def test_an_undated_earnings_row_is_refused_rather_than_misaligned(cli, missing_first):
    header = "<table><tr><th>Symbol</th><th>Company</th><th>Earnings Date</th><th>EPS Estimate</th><th>Reported EPS</th><th>Surprise (%)</th></tr>"
    count = 25 if missing_first else 2
    rows = "".join(f"<tr><td>AAPL</td><td>Apple</td><td>{'-' if missing_first and i == 0 else f'January {25 - i:02d}, 2024 at 4 PM EST'}</td><td>{i}</td><td>2</td><td>0</td></tr>"
                   for i in range(count))
    run = cli("calendar", "earnings", "AAPL", "--limit", "25", routes=[{"path": "/calendar/earnings", "text": header + rows + "</table>"}])
    if missing_first:
        assert run.code == 6 and "aligned" in run.result()["error"]["message"], run
    else:
        assert run.code == 0, run
        assert "next_offset" not in run.result()["coverage"]


def test_one_companys_earnings_take_no_date_range(cli):
    run = cli("calendar", "earnings", "AAPL", "--start", "2024-01-01", routes=[])
    assert run.code == 2, run


def test_market_summary_has_one_row_per_exchange_and_each_rows_currency(cli):
    run = cli("market", "summary", routes=recorded("market-summary"))
    assert run.code == 0, run
    assert len(run.rows) == run.result()["rows"] and all(r["exchange"] for r in run.rows)
    assert any("currency column" in n for n in run.doc["notes"])
    assert "currency_unconfirmed" not in run.result()["warnings"]
