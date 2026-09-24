import pytest

def test_scoped_schema_is_offline_and_describes_inputs(cli):
    proc, doc = cli("schema", "prices", "history")
    assert proc.returncode == 0
    assert doc["status"] == "ok"
    assert doc["results"][0]["data"]["arguments"]["--adjust"]["choices"] == ["none", "auto", "back"]


def test_all_purpose_commands_are_discoverable_without_network(cli):
    proc, doc = cli("schema")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert set(doc["results"][0]["data"]["commands"]) == {"search", "prices", "company", "financials", "analysts", "holders", "fund", "options", "screen", "market", "calendar"}
    proc = cli("screen", "run", "--help", raw=True)
    assert proc.returncode == 0
    assert '"operator":"AND"' in proc.stdout
    assert "BTWN [field, number, number]" in proc.stdout
    proc, doc = cli("schema", "financials")
    assert set(doc["results"][0]["data"]["commands"]) == {"income", "balance", "cashflow", "valuation"}


def test_global_output_budget_is_honored_and_schema_recovery_is_scoped(cli):
    proc, doc = cli("--max-chars", "1000", "schema")
    assert proc.returncode == 9, proc.stdout + proc.stderr
    assert doc["results"][0]["error"]["code"] == "too_large"
    assert "schema" in doc["results"][0]["error"]["fix"]
    assert "--fields" not in doc["results"][0]["error"]["fix"]
    proc, doc = cli("schema", "--filter", "options", "--max-chars", "1000")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert list(doc["results"][0]["data"]["commands"]) == ["options"]


def test_timeout_cannot_be_swallowed_by_library_fallback(cli):
    import time
    start = time.monotonic()
    proc, doc = cli("financials", "income", "AAPL", "--timeout", "1", routes=[{"path": "/timeseries/AAPL", "delay": 2, "json": {"timeseries": {"result": [{"timestamp": [], "annualTotalRevenue": []}]}}}])
    assert time.monotonic() - start < 3
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "timeout" in doc["results"][0]["error"]["message"]


def test_empty_native_series_field_name_can_be_reused(cli):
    routes = [{"path": "/v8/finance/chart/AAPL", "json": {"chart": {"result": [{"meta": {"exchangeTimezoneName": "America/New_York"}}], "error": None}}}, {"path": "/timeseries/AAPL", "json": {"timeseries": {"result": [{"timestamp": [1704067200], "shares_out": [42]}]}}}]
    proc, doc = cli("company", "shares", "AAPL", "--list-fields", routes=routes)
    assert proc.returncode == 0
    field = doc["results"][0]["data"][0]
    assert field == "0"
    proc, doc = cli("company", "shares", "AAPL", "--fields", field, routes=routes)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["data"] == [[42]]


def test_valuation_current_only_is_a_valid_period_selection(cli):
    payload = {"timeseries": {"result": [{"meta": {"type": ["trailingPeRatio"]}, "trailingPeRatio": [{"asOfDate": "2025-01-01", "reportedValue": {"raw": 30}}]}]}}
    proc, doc = cli("financials", "valuation", "AAPL", "--periods", "0", "--fields", "Trailing P/E", routes=[{"path": "/timeseries/AAPL", "json": payload}])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert doc["results"][0]["data"]["index"] == ["Current"]



@pytest.mark.parametrize("argv", [
    ["prices", "history", "AAPL", "--start", "2024-02-30"],
    ["prices", "history", "AAPL", "--start", "2024-01-01", "--end", "2024-01-01"],
    ["prices", "history", "AAPL", "--period", "1mo", "--start", "2024-01-01", "--end", "2024-02-01"],
    ["prices", "history", "AAPL", "--period", "0mo"],
    ["financials", "balance", "AAPL", "--frequency", "trailing"],
    ["financials", "income", "AAPL", "--periods", "0"],
    ["calendar", "earnings", "AAPL", "--start", "2024-01-01"],
    ["calendar", "earnings", "--offset", "1", "--most-active"],
    ["calendar", "economic", "--limit", "101"],
    ["screen", "run", "--query", '{"operator":"GT","operands":["intradayprice",NaN]}'],
    ["screen", "run", "--query", '{"operator":"GT","operands":["intradayprice",true]}'],
    ["screen", "run", "--query", '{"operator":"GT","operands":["intradayprice",null]}'],
    ["screen", "run", "--query", '{"operator":"AND","operands":[{"operator":"GT","operands":["intradayprice",1]}]}'],
    ["screen", "run", "--query", '{"operator":"BTWN","operands":["intradayprice",20,10]}'],
    ["screen", "run", "--query", '{"operator":"EQ","operands":["region","MARS"]}'],
    ["screen", "run", "--query", '{"operator":"EQ",}'],
    ["screen", "run", "--preset", "unknown"],
    ["prices", "history", "AAPL", "--limit", "0"],
    ["options", "chain", "AAPL", "--date", "20240119"],
])
def test_invalid_inputs_fail_before_external_http(cli, argv):
    proc, doc = cli(*argv)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert doc["results"][0]["error"]["code"] == "invalid"
    assert doc["results"][0]["error"]["fix"]
    if "--query" in argv:
        assert "$" in doc["results"][0]["error"]["message"]


def test_empty_search_is_not_proof_of_absence(cli):
    proc, doc = cli("search", "missing", routes=[{"path": "/v1/finance/lookup", "json": {"finance": {"result": [{"documents": []}], "error": None}}}])
    assert proc.returncode == 7
    assert doc["status"] == "empty"
    assert "does not prove" in doc["results"][0]["warnings"][0]


def test_schema_preserves_effective_global_defaults(cli):
    proc, doc = cli("schema")
    assert proc.returncode == 0
    shared = doc["results"][0]["data"]["common_arguments"]
    assert shared["--max-chars"]["default"] == 20000
    assert shared["--filter"]["default"] == ""


@pytest.mark.parametrize("argv", [["schema", "--max-chars", "0"], ["prices", "quote", ""], ["search", "   "]])
def test_invalid_empty_targets_and_budgets_are_rejected_before_network(cli, argv):
    proc, doc = cli(*argv)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert doc["results"][0]["error"]["code"] == "invalid"


def test_empty_dataset_does_not_falsely_reject_unverifiable_fields(cli):
    proc, doc = cli("search", "missing", "--fields", "shortName", routes=[{"path": "/v1/finance/lookup", "json": {"finance": {"result": [{"documents": []}], "error": None}}}])
    assert proc.returncode == 7, proc.stdout + proc.stderr
    assert doc["results"][0]["coverage"]["unverified_fields"] == ["shortName"]


@pytest.mark.parametrize('argv', [
    ['options', 'chain', 'AAPL', '--date', ''],
    ['prices', 'history', 'AAPL', '--start', ''],
    ['calendar', 'economic', '--end', ''],
])
def test_explicit_empty_date_is_not_an_omitted_date(cli, argv):
    proc, doc = cli(*argv)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert doc['results'][0]['error']['code'] == 'invalid'


def test_schema_and_requests_share_omitted_option_defaults(cli):
    from datetime import date, timedelta
    proc, doc = cli('schema', 'calendar', 'economic')
    schema = doc['results'][0]['data']['arguments']
    assert doc['results'][0]['data']['default_window']['rows'] == 12
    assert schema['--start']['default'] == date.today().isoformat()
    assert schema['--end']['default'] == (date.today() + timedelta(days=7)).isoformat()
    for scope, limit in [(('search',), 10), (('screen', 'run'), 25)]:
        proc, doc = cli('schema', *scope)
        assert doc['results'][0]['data']['default_window']['rows'] == limit
    proc, doc = cli('schema', 'prices', 'history')
    assert doc['results'][0]['data']['arguments']['--period']['default'] == '1mo'


def test_scoped_schema_states_its_own_defaults_and_the_document_contract(cli):
    proc, doc = cli("schema", "holders", "major")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = doc["results"][0]["data"]
    assert "default_window" in data and "narrowing" in data
    assert "schema (no scope)" in data["common"], "the shared envelope is described once, not on every leaf"
    proc, doc = cli("schema", "screen", "run", "--filter", "ascending")
    assert "--ascending" in doc["results"][0]["data"]["arguments"]
    assert list(doc["results"][0]["data"]["arguments"]) == ["--ascending"], "a filtered schema keeps only what matched"
