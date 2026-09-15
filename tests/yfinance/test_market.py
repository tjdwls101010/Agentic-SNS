import pytest

def test_search_returns_reusable_symbols_without_claiming_pagination(cli):
    routes = [{"path": "/v1/finance/lookup", "params": {"query": "apple", "type": "equity", "start": 0, "count": 1}, "json": {"finance": {"result": [{"documents": [{"symbol": "AAPL", "shortName": "Apple Inc.", "quoteType": "EQUITY"}]}], "error": None}}}]
    proc, doc = cli("search", "apple", "--type", "stock", "--limit", "1", routes=routes)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    r = doc["results"][0]
    assert r["data"]["index"] == ["AAPL"]
    assert r["data"]["data"][0][0] == "Apple Inc."
    assert r["context"]["coverage"] == "first_page_only"
    assert "next_offset" not in r["context"]


def test_screen_catalog_and_nested_query_use_public_query_validation(cli):
    proc, doc = cli("screen", "fields", "--filter", "intradaymarketcap")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "intradaymarketcap" in str(doc["results"][0]["data"])
    proc, doc = cli("screen", "values", "--field", "region", "--filter", "us")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "us" in str(doc["results"][0]["data"])
    query = '{"operator":"AND","operands":[{"operator":"EQ","operands":["region","us"]},{"operator":"GT","operands":["intradaymarketcap",2000000000]}]}'
    import json
    routes = [{"path": "/v1/finance/screener", "body": {"query": json.loads(query), "offset": 2, "size": 1}, "json": {"finance": {"result": [{"quotes": [{"symbol": "AAPL", "marketCap": 9007199254740993}], "total": 5, "start": 2, "count": 1}], "error": None}}}]
    proc, doc = cli("screen", "run", "--query", query, "--offset", "2", "--limit", "1", "--fields", "symbol", routes=routes)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"] == [{"symbol": "AAPL"}]
    assert doc["results"][0]["context"]["next_offset"] == 3


def test_single_symbol_earnings_clips_native_batch_and_does_not_skip_rows(cli):
    head = "<table><thead><tr><th>Symbol</th><th>Company</th><th>Earnings Date</th><th>EPS Estimate</th><th>Reported EPS</th><th>Surprise (%)</th></tr></thead><tbody>"
    rows = "".join(f"<tr><td>AAPL</td><td>Apple</td><td>January {25-i:02d}, 2024 at 4 PM EST</td><td>0</td><td>-</td><td>0</td></tr>" for i in range(25))
    routes = [{"path": "/calendar/earnings", "params": {"symbol": "AAPL", "offset": 0, "size": 25}, "text": head + rows + "</tbody></table>"}]
    proc, doc = cli("calendar", "earnings", "AAPL", "--limit", "1", routes=routes)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    r = doc["results"][0]
    assert len(r["data"]["data"]) == 1
    assert r["data"]["data"] == [[0, None, 0]]
    assert r["context"]["native_batch_size"] == 25
    assert r["context"]["next_offset"] == 1
    assert r["data"]["index"] == ["2024-01-25T16:00:00-05:00"]


def calendar_route(kind, columns, rows):
    return {"path": "/v1/finance/visualization", "body": {"entityIdType": kind, "size": 1, "offset": 0}, "json": {"finance": {"result": [{"documents": [{"columns": [{"label": label, "type": "TIMESTAMP" if label == "Event Start Date" else "STRING"} for label in columns], "rows": rows}]}], "error": None}}}


def test_market_earnings_discloses_us_scope_and_native_zero_loss(cli):
    columns = ["Symbol", "Company Name", "Market Cap (Intraday)", "Event Name", "Event Start Date", "EPS Estimate", "Reported EPS", "Surprise (%)"]
    route = calendar_route("sp_earnings", columns, [["AAPL", "Apple", 100, "Earnings", "2024-01-25T21:00:00Z", 0, 0, 0]])
    route["body"]["query"] = {"operator": "AND", "operands": [{"operator": "EQ", "operands": ["region", "us"]}, {"operator": "OR", "operands": [{"operator": "EQ", "operands": ["eventtype", "EAD"]}, {"operator": "EQ", "operands": ["eventtype", "ERA"]}]}, {"operator": "GTE", "operands": ["startdatetime", "2024-01-25"]}, {"operator": "LTE", "operands": ["startdatetime", "2024-01-25"]}]}
    proc, doc = cli("calendar", "earnings", "--start", "2024-01-25", "--end", "2024-01-25", "--limit", "1", "--fields", "EPS Estimate,Reported EPS,Surprise(%)", routes=[route])
    assert proc.returncode == 7, proc.stdout + proc.stderr
    r = doc["results"][0]
    assert r["data"]["data"] == [[None, None, None]]
    assert r["context"]["scope"] == "US"
    assert doc["request"]["most_active"] is False
    assert r["context"]["end_boundary"] == "native_inclusive"
    assert any("zero" in w.lower() for w in r["warnings"])


def test_sector_industry_keys_are_reusable(cli):
    route = {"path": "/v1/finance/sectors/technology", "json": {"data": {"name": "Technology", "symbol": "XLK", "overview": {"companiesCount": 10, "marketWeight": {"raw": 0.3}}, "industries": [{"key": "semiconductors", "name": "Semiconductors", "symbol": "^SOX", "marketWeight": {"raw": 0.2}}]}}}
    proc, doc = cli("market", "sector", "technology", "--dataset", "industries", routes=[route])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["index"] == ["semiconductors"]
    assert doc["results"][0]["data"]["data"] == [["Semiconductors", "^SOX", 0.2]]
    proc, doc = cli("market", "sectors", "--filter", "technology")
    assert proc.returncode == 0
    assert doc["results"][0]["data"] == ["technology"]


def test_market_status_retains_native_time_and_timezone(cli):
    routes = [{"path": "/quote/marketSummary", "json": {"marketSummaryResponse": {"result": [{"exchange": "NMS", "shortName": "Nasdaq", "regularMarketPrice": 123}]}}}, {"path": "/v6/finance/markettime", "json": {"finance": {"marketTimes": [{"marketTime": [{"id": "us", "time": "unused", "open": "2024-01-02T09:30:00-05:00", "close": "2024-01-02T16:00:00-05:00", "timezone": [{"gmtoffset": -5000, "short": "EST"}]}]}]}}}]
    proc, doc = cli("market", "status", "--fields", "open,close,tz", routes=routes)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"] == {"open": "2024-01-02T09:30:00-05:00", "close": "2024-01-02T16:00:00-05:00", "tz": "EST"}


def test_screen_applied_defaults_identify_actual_preset_universe(cli):
    routes = [{"path": "/v1/finance/screener", "body": {"quoteType": "ETF", "sortField": "percentchange", "sortType": "DESC"}, "json": {"finance": {"result": [{"quotes": [{"symbol": "SPY"}], "total": 1}], "error": None}}}]
    proc, doc = cli("screen", "run", "--preset", "top_etfs_us", routes=routes)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    request = doc["request"]
    assert request["type"] == "etf"
    assert request["sort"] == "percentchange"
    assert request["ascending"] is False



@pytest.mark.parametrize("leaf,kind,columns,row,field,expected", [
    ("economic", "economic_event", ["Event", "Country Code", "Event Time", "Actual", "Market Expectation", "Prior to This", "Revised from"], ["Jobs", "US", "2024-01-25T13:30:00Z", 0, 1, 2, 0], "Actual,Expected", [None, 1]),
    ("ipo", "ipo_info", ["Symbol", "Exchange Short Name", "Filing Date", "Date", "Amended Date", "Price From", "Price To", "Price", "Shares"], ["NEW", "NYQ", "2024-01-20", "2024-01-25", "2024-01-23", 0, 10, 0, 0], "Exchange,Price", ["NYQ", None]),
    ("splits", "splits", ["Symbol", "Payable On", "Optionable?", "Old Share Worth", "Share Worth"], ["AAPL", "2024-01-25", True, 1, 2], "Old Share Worth,Share Worth", [1, 2]),
])
def test_other_market_calendar_dates_and_numeric_semantics(cli, leaf, kind, columns, row, field, expected):
    proc, doc = cli("calendar", leaf, "--start", "2024-01-25", "--end", "2024-01-25", "--limit", "1", "--fields", field, routes=[calendar_route(kind, columns, [row])])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["data"] == [expected]
    if leaf == "ipo":
        assert doc["results"][0]["context"]["date_field"] == ["startdatetime", "filingdate", "amendeddate"]


@pytest.mark.parametrize("dataset", ["overview", "top-companies", "research-reports", "top-performing", "top-growth"])
def test_industry_datasets(cli, dataset):
    data = {"name": "Semiconductors", "symbol": "^SOX", "sectorKey": "technology", "sectorName": "Technology", "overview": {"companiesCount": 10}, "topCompanies": [{"symbol": "EX", "name": "Example"}], "researchReports": [{"id": "r1"}], "topPerformingCompanies": [{"symbol": "EX", "name": "Example"}], "topGrowthCompanies": [{"symbol": "EX", "name": "Example"}]}
    proc, doc = cli("market", "industry", "semiconductors", "--dataset", dataset, routes=[{"path": "/v1/finance/industries/semiconductors", "json": {"data": data}}])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    if dataset == "overview":
        assert doc["results"][0]["data"]["companies_count"] == 10
    elif dataset == "research-reports":
        assert doc["results"][0]["data"] == [{"id": "r1"}]
    else:
        assert doc["results"][0]["data"]["index"] == ["EX"]


@pytest.mark.parametrize("kind,query,quote_type", [("equity", '{"operator":"IS-IN","operands":["region","us","gb"]}', "EQUITY"), ("fund", '{"operator":"EQ","operands":["exchange","NAS"]}', "MUTUALFUND"), ("etf", '{"operator":"BTWN","operands":["intradayprice",10,20]}', "ETF")])
def test_query_universes_and_operator_forms(cli, kind, query, quote_type):
    routes = [{"path": "/v1/finance/screener", "body": {"quoteType": quote_type}, "json": {"finance": {"result": [{"quotes": [{"symbol": "EX"}]}], "error": None}}}]
    proc, doc = cli("screen", "run", "--type", kind, "--query", query, routes=routes)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"] == [{"symbol": "EX"}]


@pytest.mark.parametrize('missing_first', [True, False])
def test_earnings_missing_dates_do_not_corrupt_values_or_prove_page_end(cli, missing_first):
    header = '<table><tr><th>Symbol</th><th>Company</th><th>Earnings Date</th><th>EPS Estimate</th><th>Reported EPS</th><th>Surprise (%)</th></tr>'
    count = 25 if missing_first else 2
    rows = []
    for i in range(count):
        day = '-' if missing_first and i == 0 else f'January {25-i:02d}, 2024 at 4 PM EST'
        rows.append(f'<tr><td>AAPL</td><td>Apple</td><td>{day}</td><td>{i}</td><td>2</td><td>0</td></tr>')
    route = {'path': '/calendar/earnings', 'text': header + ''.join(rows) + '</table>'}
    proc, doc = cli('calendar', 'earnings', 'AAPL', '--limit', '25', routes=[route])
    r = doc['results'][0]
    if missing_first:
        assert proc.returncode == 6, proc.stdout
        assert r['data'] is None
        assert 'alignment' in r['error']['message']
    else:
        assert proc.returncode == 0, proc.stdout
        assert r['context']['remaining'] is None
        assert r['context']['next_offset'] == 2


def test_preset_catalog_honors_the_selected_asset_universe(cli):
    proc, doc = cli('screen', 'presets', '--type', 'etf')
    assert proc.returncode == 0, proc.stdout
    names = [entry['name'] for entry in doc['results'][0]['data']]
    assert 'top_etfs_us' in names
    assert 'most_actives' not in names
