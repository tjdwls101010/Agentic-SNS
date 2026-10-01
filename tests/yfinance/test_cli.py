from datetime import date, timedelta
import re

import pytest

from conftest import arguments, document, fact, groups


def test_a_documents_arguments_carry_their_choices_and_defaults():
    adjust = arguments("prices")["--adjust"][0]
    assert adjust[1] == "--adjust {none,auto,back}" and adjust[2].endswith("(default auto)")
    assert arguments("prices")["--interval"][0][2].endswith("(default 1d)")
    assert [text.endswith("(default 5) (at least 1)") or text.endswith("(default 5) (at least 0)") for _, _, text in arguments("financials")["--periods"]] == [True, True]
    assert "(default 20000) (at least 1000)" in document() and "(default 14)" in document() and "0 keeps every one" in document()
    assert arguments("calendar")["--offset"][0][2].endswith("(default 0)"), "a default of 0 is a default, not an absent one"
    assert "--start N  Zero-based first row to return; each slice names the start of the next one. (default 0)" in document("read")


def test_all_purpose_commands_are_discoverable_without_network(cli):
    assert set(groups()) == {"search", "prices", "company", "financials", "analysts", "holders", "fund", "options", "screen", "market", "calendar"}
    text = document("screen", "run")
    assert '"operator":"AND"' in text and "BTWN [field, number, number]" in text
    assert groups()["financials"] == ["income", "balance", "cashflow", "valuation"]


@pytest.mark.parametrize("scope", [[], ["prices"], ["prices", "history"], ["screen", "run"], ["search"], ["read"]])
def test_help_needs_no_target_ignores_the_budget_and_opens_no_store(cli, tmp_path, scope):
    """A document is not a result: it needs none of the command's required arguments, is not cut to --max-chars, and makes no store or request."""
    store = tmp_path / "never-created"
    proc = cli("--max-chars", "1000", *scope, "--help", routes=[], store=store, raw=True)
    assert proc.returncode == 0, proc.stdout[:300]
    assert len(proc.stdout) > 1000 and proc.stdout == document(*scope)
    assert not store.exists()


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
    ["search", "apple", "--dataset", "news", "--type", "etf"],
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


@pytest.mark.parametrize("argv", [["--max-chars", "0", "search", "apple"], ["prices", "quote", ""], ["search", "   "]])
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


def test_the_defaults_a_command_fills_in_are_the_ones_its_request_echoes(cli):
    """The document states the default windows; the computed defaults (a calendar's dates, a series' period) show in the request the call echoes."""
    assert fact("calendar", "economic", "default rows") == "12"
    assert fact("search", "", "default rows") == "10" and fact("screen", "run", "default rows") == "25"
    economic = cli("calendar", "economic", "--limit", "101", routes=[], raw=True)
    assert economic.returncode == 2, "the limit cap is checked before the defaults are filled and anything is asked"
    route = {"path": "/v1/finance/visualization", "json": {"finance": {"result": [{"documents": [{"columns": [], "rows": []}]}], "error": None}}}
    proc, doc = cli("calendar", "economic", routes=[route])
    assert doc["request"]["start"] == date.today().isoformat()
    assert doc["request"]["end"] == (date.today() + timedelta(days=7)).isoformat()
    from test_budget import chart_routes
    proc, doc = cli("prices", "history", "AAPL", routes=chart_routes())
    assert doc["request"]["period"] == "1mo"


def test_the_root_map_states_every_exit_code(cli):
    """Exit codes other than 0 and 2 are defined by --help; a caller that branches on 8 must be able to read what 8 is."""
    expected = {"ok": 0, "invalid": 2, "local_io": 4, "rate_limited": 5, "upstream": 6, "empty": 7, "partial": 8, "too_large": 9}
    text = cli("--help", raw=True).stdout
    listed = {name: int(code) for code, name in re.findall(r"(?m)^\s+(\d)\s+(\w+): \S", text)}
    assert listed == expected, text[-900:]


# ---- --filter narrows a listing and nothing else -------------------------------------------------------------------


def test_filter_narrows_a_catalog_alone_and_a_field_listing(cli, tmp_path):
    proc, doc = cli("screen", "presets", routes=[])
    assert proc.returncode == 0, proc.stdout[:300]
    every = [p["name"] for p in doc["results"][0]["data"]]
    proc, doc = cli("screen", "presets", "--filter", "gainers", routes=[])
    assert proc.returncode == 0 and [p["name"] for p in doc["results"][0]["data"]] == [n for n in every if "gainers" in n]
    assert "filter" not in cli("screen", "presets", routes=[])[1]["request"], "an omitted --filter is not echoed"
    from test_budget import chart_routes
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--list-fields", "--filter", "clo", routes=chart_routes(), store=store)
    assert proc.returncode == 0 and doc["results"][0]["data"] == ["Close"], proc.stdout[:300]
    proc, back = cli("read", doc["results"][0]["id"], "--list-fields", "--filter", "vol", routes=[], store=store)
    assert proc.returncode == 0 and back["results"][0]["data"] == ["Volume"], proc.stdout[:300]


@pytest.mark.parametrize("argv", [["prices", "history", "AAPL", "--filter", "Close"], ["prices", "history", "AAPL", "--filter", ""],
                                  ["read", "0123456789abcdef", "--filter", "x"], ["screen", "run", "--preset", "day_gainers", "--filter", "x"]])
def test_filter_where_it_narrows_nothing_is_refused_before_anything_is_opened(cli, tmp_path, argv):
    store = tmp_path / "never-created"
    proc, doc = cli(*argv, routes=[], store=store)
    assert proc.returncode == 2 and "--filter" in doc["results"][0]["error"]["message"], proc.stdout[:300]
    assert not store.exists()


def test_a_range_a_default_completes_is_checked_again_before_anything_is_asked(cli, tmp_path):
    """A calendar's --start defaults to today, so an --end in the past makes a reversed range that was never checked once the default filled it in."""
    store = tmp_path / "never-created"
    proc, doc = cli("calendar", "economic", "--end", "2020-01-01", routes=[], store=store)
    assert proc.returncode == 2, proc.stdout[:400]
    assert doc["results"][0]["error"]["code"] == "invalid"
    assert not store.exists()
