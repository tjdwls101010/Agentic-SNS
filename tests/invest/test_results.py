"""Saved results: every call gets its own folder under data/results (or $INVEST_DATA), published whole or not at all, never overwriting another, deleted only by age."""
import json
import os
from pathlib import Path
import stat
import time

from test_prices import chart_routes


def test_each_call_gets_its_own_folder_and_none_is_overwritten(cli, tmp_path):
    first = cli("history", "AAPL", "--period", "5d", routes=chart_routes())
    second = cli("history", "AAPL", "--period", "5d", routes=chart_routes())
    assert first.code == 0 and second.code == 0, (first, second)
    a, b = Path(first.doc["receipt_path"]).parent, Path(second.doc["receipt_path"]).parent
    assert a != b and a.parent == b.parent == tmp_path / "data" / "results"
    assert first.receipt["id"] == a.name and second.receipt["id"] == b.name
    assert sorted(p.name for p in a.iterdir()) == ["receipt.json", "result.csv"]


def test_the_file_and_receipt_paths_point_at_what_was_written(cli):
    run = cli("history", "AAPL", "--period", "5d", routes=chart_routes())
    assert Path(run.doc["file"]["path"]).is_file() and Path(run.doc["receipt_path"]).is_file()
    assert run.doc["file"]["rows"] == len(run.rows) and run.doc["file"]["columns"] == len(run.rows[0])


def test_a_failed_publish_leaves_no_folder_and_names_no_path(cli, tmp_path):
    data = tmp_path / "data"
    (data / "results").mkdir(parents=True)
    (data / "results").chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        run = cli("history", "AAPL", "--period", "5d", routes=chart_routes(), data=data)
        left = list((data / "results").iterdir())
    finally:
        (data / "results").chmod(stat.S_IRWXU)
    assert run.code == 4, run
    assert left == [], "no half-written folder, staging or final"
    assert "receipt_path" not in run.doc and run.doc["file"] is None
    assert run.result()["error"]["code"] == "local_io"


def test_old_results_are_deleted_by_age_and_zero_keeps_them(cli, tmp_path):
    old = cli("history", "AAPL", "--period", "5d", routes=chart_routes())
    folder = Path(old.doc["receipt_path"]).parent
    month_ago = time.time() - 30 * 86400
    os.utime(folder, (month_ago, month_ago))
    cli("--ttl-days", "0", "history", "AAPL", "--period", "5d", routes=chart_routes())
    assert folder.exists(), "--ttl-days 0 keeps everything"
    cli("history", "AAPL", "--period", "5d", routes=chart_routes())
    assert not folder.exists(), "the default 14 days removes a month-old result"


def test_an_empty_result_saves_its_receipt_and_no_result_file(cli):
    empty = {"chart": {"error": None, "result": [{"meta": {"currency": "USD", "symbol": "AAPL", "instrumentType": "EQUITY", "exchangeTimezoneName": "America/New_York",
                                                           "timezone": "EST", "gmtoffset": -18000, "dataGranularity": "1d", "validRanges": ["1d"]}, "timestamp": [1704205800],
                                                  "indicators": {"quote": [{"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]}], "adjclose": [{"adjclose": [1.0]}]}}]}}
    run = cli("history", "AAPL", "--period", "5d", "--actions", routes=chart_routes(body=empty))
    assert run.code == 7, run
    assert run.doc["file"] is None
    folder = Path(run.doc["receipt_path"]).parent
    assert sorted(p.name for p in folder.iterdir()) == ["receipt.json"]
    assert json.loads((folder / "receipt.json").read_text())["status"] == "empty"


# ---- the long file: unique names, the union of every target's columns, nested values as JSON -----------------------------

def screener(rows):
    return [{"path": "/v1/finance/screener", "json": {"finance": {"result": [{"quotes": rows, "total": len(rows), "start": 0, "count": len(rows)}], "error": None}}}]


def test_a_source_column_named_target_never_overwrites_the_target(cli):
    run = cli("screen", "run", "--query", '{"operator":"EQ","operands":["region","us"]}', routes=screener([{"symbol": "EX", "currency": "USD", "target": "theirs"}]))
    assert run.code == 0, run
    row = run.rows[0]
    assert row["target"] == "query" and row["source.target"] == "theirs"


def test_targets_with_different_columns_share_one_file_under_their_union(cli):
    from test_prices import CHART
    fund = {"chart": {"error": None, "result": [{**CHART["chart"]["result"][0], "meta": {**CHART["chart"]["result"][0]["meta"], "symbol": "SPY", "instrumentType": "ETF"},
                                                 "events": {"capitalGains": {"1704205800": {"amount": 0.25, "date": 1704205800}}}}]}}
    run = cli("history", "AAPL", "SPY", "--start", "2024-01-02", "--end", "2024-01-05", routes=chart_routes() + chart_routes("SPY", fund))
    assert run.code == 0, run
    assert "Capital Gains" in run.rows[0]
    by_target = {}
    for row in run.rows:
        by_target.setdefault(row["target"], []).append(row)
    assert {r["Capital Gains"] for r in by_target["AAPL"]} == {""}, "a column a target lacks is left empty for it"
    assert float(by_target["SPY"][0]["Capital Gains"]) == 0.25


def test_a_nested_value_is_written_as_json(cli):
    run = cli("screen", "run", "--query", '{"operator":"EQ","operands":["region","us"]}',
              routes=screener([{"symbol": "EX", "currency": "USD", "corporateActions": [{"header": "Dividend", "meta": {"amount": 0.5}}]}]))
    assert run.code == 0, run
    assert json.loads(run.rows[0]["corporateActions"]) == [{"header": "Dividend", "meta": {"amount": 0.5}}]
