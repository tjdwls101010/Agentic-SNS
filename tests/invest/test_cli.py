"""The receipt and the arguments: key order, what receipt.json keeps, how a receipt is cut to fit --max-chars, and every argument refused before any request.

A refused argument saves nothing and asks Yahoo nothing; a receipt that does not fit loses its inline rows first and its status, warnings and receipt path never.
"""
import pytest

from conftest import recorded
from invest import receipts
from test_prices import CHART, chart_routes

DOCUMENT = ["status", "command", "receipt_path", "file", "units", "warnings", "notes", "results", "trimmed", "projected", "over_budget"]
TARGET = ["target", "status", "rows", "warnings", "observed_at", "as_of", "currency", "financial_currency", "coverage", "conditions", "data", "first", "last", "error"]


def year_of_bars(symbol="AAPL", days=250, start=1704205800):
    stamps = [start + i * 86400 for i in range(days)]
    body = {"chart": {"error": None, "result": [{**CHART["chart"]["result"][0], "meta": {**CHART["chart"]["result"][0]["meta"], "symbol": symbol},
                                                 "timestamp": stamps, "events": {},
                                                 "indicators": {"quote": [{"open": [100.0 + i for i in range(days)], "high": [101.0 + i for i in range(days)],
                                                                           "low": [99.0 + i for i in range(days)], "close": [100.5 + i for i in range(days)],
                                                                           "volume": [1000 + i for i in range(days)]}], "adjclose": [{"adjclose": [100.5 + i for i in range(days)]}]}}]}}
    return chart_routes(symbol, body)


def in_order(keys, order):
    positions = [order.index(k) for k in keys]
    return positions == sorted(positions)


def test_the_receipt_keys_come_in_their_fixed_order(cli):
    run = cli("history", "AAPL", "MSFT", "--period", "5d", routes=chart_routes() + chart_routes("MSFT"))
    assert run.code == 0, run
    assert in_order(list(run.doc), DOCUMENT) and list(run.doc)[:3] == ["status", "command", "receipt_path"]
    for result in run.doc["results"]:
        assert in_order(list(result), TARGET)


def test_receipt_json_keeps_everything_the_printed_receipt_may_cut(cli):
    run = cli("--max-chars", "1500", "history", "AAPL", "--period", "1y", routes=year_of_bars())
    assert run.doc["trimmed"] is True, run
    full = run.receipt
    assert full["columns"][:2] == ["target", "Date"] and {"Open", "Close", "Volume"} <= set(full["columns"])
    assert set(full["units"]) == set(full["columns"]) and set(full["unit_status"]) >= set(full["columns"]) - {"target"}
    assert all(isinstance(w, dict) and w["code"] and w["text"] for w in full["warnings"])
    assert full["results"][0]["observed_at"] and full["results"][0]["as_of"]["timezone"] == "America/New_York"
    assert full["request"]["period"] == "1y" and full["request"]["interval"] == "1d"


def test_a_small_result_is_inline_and_a_large_one_shows_its_ends(cli):
    small = cli("history", "AAPL", "--period", "5d", routes=chart_routes())
    assert small.doc["trimmed"] is False and len(small.result()["data"]) == 3
    large = cli("history", "AAPL", "--period", "1y", routes=year_of_bars())
    result = large.result()
    assert large.doc["trimmed"] is True and "data" not in result
    assert [r["Date"] for r in result["first"]] == ["2024-01-02", "2024-01-03", "2024-01-04"]
    assert len(result["last"]) == 3 and result["rows"] == 250
    assert len(large.proc.stdout.strip()) <= 8000


def test_cutting_goes_data_then_preview_then_notes_then_units_then_detail_and_keeps_the_rest(cli):
    sizes = {}
    for limit in (8000, 2200, 1700, 1300, 900):
        run = cli("--max-chars", str(limit), "history", "AAPL", "--period", "1y", routes=year_of_bars())
        assert len(run.proc.stdout.strip()) <= limit, (limit, len(run.proc.stdout))
        doc, result = run.doc, run.result()
        sizes[limit] = {"preview": "first" in result, "notes": "notes" in doc, "units": "units" in doc, "detail": "as_of" in result}
        assert doc["status"] == "ok" and doc["receipt_path"] and result["target"] == "AAPL" and result["status"] == "ok"
        assert "data" not in result
    order = [sizes[k] for k in (8000, 2200, 1700, 1300, 900)]
    for before, after in zip(order, order[1:]):
        assert all(after[k] <= before[k] for k in before), "a smaller budget never keeps what a larger one cut"
    assert order[0] == {"preview": True, "notes": True, "units": True, "detail": True}
    assert order[-1]["detail"] is False


def test_warning_codes_survive_every_cut(cli):
    run = cli("--max-chars", "700", "quote", "TM", routes=recorded("quote-tm"))
    assert run.code == 0, run
    assert "cross_currency_fields" in [w if isinstance(w, str) else w["code"] for w in run.doc["warnings"]]
    assert run.doc["trimmed"] is True and run.doc["receipt_path"]


def test_fields_project_the_inline_copy_and_keep_identifying_columns(cli):
    run = cli("history", "AAPL", "--period", "5d", "--fields", "Close", routes=chart_routes())
    assert run.doc["projected"] is True
    assert [set(r) for r in run.result()["data"]] == [{"Date", "Close"}] * 3
    assert {"Open", "Volume"} <= set(run.rows[0]), "the file keeps every column"


def test_a_wide_record_shows_a_default_selection_and_says_so(cli):
    run = cli("quote", "KO", routes=recorded("quote-ko"))
    assert run.doc["projected"] is True and any("selection" in n for n in run.doc["notes"])
    shown = run.result().get("data") or {}
    assert "regularMarketPrice" in shown and "companyOfficers" not in shown
    assert len(run.records[0]["data"]) > len(shown) + 50, "result.json holds the whole response"


def test_a_budget_too_small_for_the_uncuttable_receipt_is_refused_before_any_request(cli, tmp_path):
    run = cli("--max-chars", "120", "history", "AAPL", "MSFT", "--period", "5d", routes=[], data=tmp_path / "fresh")
    assert run.code == 2, run
    assert run.requests == [] and not (tmp_path / "fresh").exists()
    assert "--max-chars" in run.result()["error"]["fix"]


def test_a_receipt_whose_uncuttable_part_does_not_fit_prints_it_whole_and_says_over_budget():
    document = {"status": "error", "command": "history", "receipt_path": "/x/receipt.json", "file": None, "units": {}, "notes": ["n"],
                "warnings": [{"code": f"code_{i}", "text": "t"} for i in range(30)],
                "results": [{"target": f"T{i}", "status": "error", "warnings": [f"code_{i}"], "error": {"code": "upstream", "message": "m", "fix": "f"}} for i in range(30)],
                "trimmed": False, "projected": False}
    printed = receipts.fit(document, 200)
    assert printed["over_budget"] is True and printed["trimmed"] is True
    assert printed["warnings"] == [f"code_{i}" for i in range(30)], "every warning code is kept"
    assert [r["target"] for r in printed["results"]] == [f"T{i}" for i in range(30)]


# ---- arguments refused before any request ----------------------------------------------------------------------------

@pytest.mark.parametrize("argv,phrase", [
    (["history", "AAPL", "--start", "2024-13-01"], "YYYY-MM-DD"),
    (["history", "AAPL", "--period", "1mo", "--start", "2024-01-01"], "--period"),
    (["history", "AAPL", "--start", "2024-01-05", "--end", "2024-01-05"], "exclusive"),
    (["history", "AAPL", "--period", "fortnight"], "--period"),
    (["calendar", "ipo", "--start", "2024-01-05", "--end", "2024-01-04"], "inclusive"),
    (["calendar", "earnings", "--limit", "101"], "100"),
    (["calendar", "earnings", "--most-active", "--offset", "5"], "--most-active"),
    (["screen", "run", "--preset", "day_gainers", "--limit", "251"], "250"),
    (["screen", "run", "--preset", "day_gainers", "--query", "{}"], "exactly one"),
    (["screen", "run", "--preset", "day_gainers", "--source-units"], "--source-units"),
    (["screen", "run"], "exactly one"),
    (["financials", "income", "AAPL", "--periods", "3"], "--periods"),
    (["options", "expirations", "AAPL", "--side", "calls"], "--side"),
    (["history", "AAPL", "--timeout", "0"], "--timeout"),
    (["history", "AAPL", "--limit", "5"], "unrecognized"),
    (["company", "news", "AAPL", "--limit", "0"], "--limit"),
    (["history"], "SYMBOL"),
    (["history", " "], "empty"),
    (["company", "AAPL"], "invalid choice"),
    (["prices", "quote", "AAPL"], "invalid choice"),
    (["--ttl-days", "-1", "quote", "AAPL"], "--ttl-days"),
    (["market", "summary", "--region", "KR"], "summary --region"),
    (["market", "industry", "semiconductors", "--dataset", "industries"], "--dataset"),
])
def test_a_refused_argument_asks_nothing_and_saves_nothing(cli, tmp_path, argv, phrase):
    run = cli(*argv, routes=[], data=tmp_path / "fresh")
    assert run.code == 2, run
    error = run.result()["error"]
    assert error["code"] == "invalid" and phrase in error["message"] + error["fix"], error
    assert run.requests == [] and not (tmp_path / "fresh").exists()
    assert "receipt_path" not in run.doc


def test_max_chars_is_accepted_after_the_command_too(cli):
    run = cli("history", "AAPL", "--period", "1y", "--max-chars", "1500", routes=year_of_bars())
    assert len(run.proc.stdout.strip()) <= 1500 and run.doc["trimmed"] is True


def test_help_opens_nothing_and_asks_nothing(cli, tmp_path):
    run = cli("history", "--help", routes=[], data=tmp_path / "fresh")
    assert run.code == 0 and run.doc is None and run.proc.stdout.startswith("usage: cli.py")
    assert run.requests == [] and not (tmp_path / "fresh").exists()
