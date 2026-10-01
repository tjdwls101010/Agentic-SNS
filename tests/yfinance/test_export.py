"""--out: every row an observation received, in one long CSV a computation can read, and never half a file."""
import csv
import json

import pytest

from test_display import META

STAMPS = [1704205800 + 86400 * i for i in range(30)]


def chart(symbol, closes, extra=None):
    quote = {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000 + i for i in range(len(closes))]}
    body = {"meta": dict(META, symbol=symbol), "timestamp": STAMPS[:len(closes)], "indicators": {"quote": [quote], "adjclose": [{"adjclose": closes}]}, "events": extra or {}}
    return {"path": f"/v8/finance/chart/{symbol}", "json": {"chart": {"error": None, "result": [body]}}}


def rows(path):
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def test_two_targets_land_in_one_long_file_with_every_digit(cli, tmp_path):
    out = tmp_path / "prices.csv"
    closes = [311.4700012207031 + i for i in range(30)]
    proc, doc = cli("prices", "history", "AAPL", "SPY", "--period", "1mo", "--adjust", "none", "--fields", "Close", "--out", str(out),
                    routes=[chart("AAPL", closes), chart("SPY", [500.0 + i for i in range(25)])])
    assert proc.returncode == 0, proc.stdout[:500]
    written = rows(out)
    assert list(written[0]) == ["target", "Date", "Close"]
    assert [r["target"] for r in written].count("AAPL") == 30 and [r["target"] for r in written].count("SPY") == 25
    assert written[0]["Close"] == "311.4700012207031", "the file keeps the digits the screen trims"
    assert written[0]["Date"] == "2024-01-02T00:00:00-05:00"
    first = doc["results"][0]
    assert first["data"] == {"out": str(out), "rows": 30, "columns": ["target", "Date", "Close"], "first": "2024-01-02T00:00:00-05:00", "last": "2024-01-31T00:00:00-05:00"}
    assert first["coverage"]["received"] == 30 and first["coverage"]["shown"] == 30


def test_the_leaf_default_window_does_not_cut_the_file_but_an_explicit_limit_does(cli, tmp_path):
    """company filings shows 20 by default; a file is for computing, so it holds everything that arrived."""
    filings = [{"date": f"2026-01-{i % 28 + 1:02d}", "type": "8-K", "title": f"t{i}", "edgarUrl": "u", "exhibits": [{"type": "EX-99", "url": "x"}]} for i in range(45)]
    routes = [{"path": "/quoteSummary/AAPL", "params": {"modules": "secFilings"}, "json": {"quoteSummary": {"result": [{"secFilings": {"filings": filings}}]}}}]
    proc, doc = cli("company", "filings", "AAPL", "--out", str(tmp_path / "all.csv"), routes=routes)
    assert proc.returncode == 0, proc.stdout[:500]
    written = rows(tmp_path / "all.csv")
    assert len(written) == 45
    assert written[0]["exhibits.EX-99"] == "x", "a nested object is written under the dotted path --fields uses"
    proc, doc = cli("company", "filings", "AAPL", "--limit", "5", "--out", str(tmp_path / "five.csv"), routes=routes)
    assert [r["title"] for r in rows(tmp_path / "five.csv")] == ["t0", "t1", "t2", "t3", "t4"]


def test_a_nested_record_is_flattened_to_the_paths_fields_use(cli, tmp_path):
    items = [{"id": f"i{n}", "content": {"title": f"T{n}", "provider": {"displayName": "P"}, "tags": ["a", "b"]}} for n in range(3)]
    routes = [{"path": "/xhr/ncp", "json": {"data": {"tickerStream": {"stream": items}}}}]
    proc, doc = cli("company", "news", "AAPL", "--out", str(tmp_path / "news.csv"), routes=routes)
    assert proc.returncode == 0, proc.stdout[:500]
    written = rows(tmp_path / "news.csv")
    assert written[0]["content.provider.displayName"] == "P" and written[0]["content.title"] == "T0"
    assert json.loads(written[0]["content.tags"]) == ["a", "b"]


def test_an_option_chain_writes_each_side_under_a_side_column(cli, tmp_path):
    contract = {"contractSymbol": "C1", "strike": 100.0, "lastPrice": 2.0, "impliedVolatility": 0.2, "inTheMoney": True, "currency": "USD"}
    put = dict(contract, contractSymbol="P1")
    routes = [{"path": "/v7/finance/options/AAPL", "json": {"optionChain": {"result": [{"expirationDates": [1705622400], "quote": {"symbol": "AAPL"}, "options": [{"calls": [contract], "puts": [put]}]}], "error": None}}}]
    proc, doc = cli("options", "chain", "AAPL", "--out", str(tmp_path / "chain.csv"), routes=routes)
    assert proc.returncode == 0, proc.stdout[:500]
    written = rows(tmp_path / "chain.csv")
    assert [(r["side"], r["contractSymbol"]) for r in written] == [("calls", "C1"), ("puts", "P1")]


def test_a_list_of_values_is_one_value_column(cli, tmp_path):
    proc, doc = cli("market", "sectors", "--out", str(tmp_path / "sectors.csv"))
    assert proc.returncode == 0, proc.stdout[:500]
    written = rows(tmp_path / "sectors.csv")
    assert list(written[0]) == ["target", "value"] and len(written) == 11


def test_a_mapping_of_records_gets_a_key_column_and_a_colliding_field_is_renamed(cli, tmp_path):
    summary = {"marketSummaryResponse": {"result": [{"exchange": "SNP", "shortName": "S&P 500", "key": "clash", "regularMarketPrice": {"raw": 5000.5}}], "error": None}}
    status = {"finance": {"marketTimes": [{"marketTime": [{"open": "2024-01-02T09:30:00-05:00", "close": "2024-01-02T16:00:00-05:00", "time": "2024-01-02T16:00:00-05:00", "timezone": [{"short": "EST", "gmtoffset": "-5000"}]}]}]}}
    routes = [{"path": "/v6/finance/quote/marketSummary", "json": summary}, {"path": "/v6/finance/markettime", "json": status}]
    proc, doc = cli("market", "summary", "--out", str(tmp_path / "summary.csv"), routes=routes)
    assert proc.returncode == 0, proc.stdout[:500]
    written = rows(tmp_path / "summary.csv")
    assert written[0]["key"] == "SNP" and written[0]["source.key"] == "clash"


def test_a_single_record_command_offers_no_out(cli, tmp_path):
    proc = cli("prices", "quote", "AAPL", "--out", str(tmp_path / "q.csv"), raw=True)
    assert proc.returncode == 2
    assert "--out" not in cli("prices", "quote", "--help", raw=True).stdout
    assert "--out" in cli("prices", "history", "--help", raw=True).stdout


def test_an_existing_file_is_never_overwritten(cli, tmp_path):
    out = tmp_path / "kept.csv"
    out.write_text("precious\n")
    proc, doc = cli("prices", "history", "AAPL", "--period", "1mo", "--out", str(out), routes=[chart("AAPL", [1.0, 2.0])])
    assert proc.returncode == 2
    assert "exists" in doc["results"][0]["error"]["message"]
    assert out.read_text() == "precious\n"


def test_a_missing_directory_is_refused_before_any_request(cli, tmp_path):
    proc, doc = cli("prices", "history", "AAPL", "--out", str(tmp_path / "nowhere" / "x.csv"), routes=[])
    assert proc.returncode == 2 and "directory" in doc["results"][0]["error"]["message"]


def test_a_file_that_appears_before_publishing_keeps_its_bytes(cli, tmp_path):
    """Checked before the request and again at publication: a file that appears in between is kept, and the
    observation stays readable under its id so the rows are not lost either."""
    out = tmp_path / "race.csv"
    proc, doc = cli("prices", "history", "AAPL", "--period", "1mo", "--out", str(out), routes=[chart("AAPL", [1.0, 2.0]) | {"touch": str(out)}])
    assert out.read_text() == "arrived first\n"
    r = doc["results"][0]
    assert r["status"] == "error" and r["id"], proc.stdout[:400]
    assert r["error"]["code"] == "invalid" and f"read {r['id']}" in r["error"]["fix"]
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".race")] == [], "no temporary file is left behind"


def test_when_every_target_is_empty_no_file_is_made(cli, tmp_path):
    routes = [{"path": "/xhr/ncp", "json": {"data": {"tickerStream": {"stream": []}}}}]
    proc, doc = cli("company", "news", "AAPL", "--out", str(tmp_path / "none.csv"), routes=routes)
    assert proc.returncode == 7
    assert not (tmp_path / "none.csv").exists()


def test_read_exports_a_saved_observation_without_a_new_request(cli, tmp_path):
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--period", "1mo", routes=[chart("AAPL", [float(i) for i in range(30)])], store=store)
    ident = doc["results"][0]["id"]
    proc, back = cli("read", ident, "--fields", "Close", "--out", str(tmp_path / "read.csv"), routes=[], store=store)
    assert proc.returncode == 0, proc.stdout[:500]
    assert [r["Close"] for r in rows(tmp_path / "read.csv")] == [str(float(i)) for i in range(30)]
    proc, back = cli("read", ident, "--start", "10", "--limit", "5", "--out", str(tmp_path / "slice.csv"), routes=[], store=store)
    assert [r["Close"] for r in rows(tmp_path / "slice.csv")] == [str(float(i)) for i in range(10, 15)]


@pytest.mark.parametrize("code", ["local_io"])
def test_the_root_schema_names_the_export_failure(cli, code):
    proc, doc = cli("schema")
    data = doc["results"][0]["data"]
    assert data["output"]["exit_codes"][code] == 4
    assert "--out" in data["common_arguments"]


# ---- defects found by an independent review of this feature --------------------------------------------------------


def test_a_colliding_field_name_never_drops_a_value(cli, tmp_path):
    quotes = [{"symbol": "A", "target": "ORIGINAL", "source.target": "SECOND"}]
    routes = [{"path": "/v1/finance/screener", "json": {"finance": {"result": [{"quotes": quotes, "total": 1}], "error": None}}}]
    proc, doc = cli("screen", "run", "--query", '{"operator":"EQ","operands":["region","us"]}', "--out", str(tmp_path / "s.csv"), routes=routes)
    assert proc.returncode == 0, proc.stdout[:400]
    row = rows(tmp_path / "s.csv")[0]
    assert "ORIGINAL" in row.values() and "SECOND" in row.values() and row["target"] != "ORIGINAL"


def test_an_all_null_target_is_empty_and_writes_no_file(cli, tmp_path):
    columns = ["Symbol", "Company Name", "Market Cap (Intraday)", "Event Name", "Event Start Date", "EPS Estimate", "Reported EPS", "Surprise (%)"]
    route = {"path": "/v1/finance/visualization", "body": {"entityIdType": "sp_earnings"},
             "json": {"finance": {"result": [{"documents": [{"columns": [{"label": c, "type": "TIMESTAMP" if c == "Event Start Date" else "STRING"} for c in columns], "rows": [["AAPL", "Apple", 0, "Earnings", "2024-01-25T21:00:00Z", 0, 0, 0]]}]}], "error": None}}}
    proc, doc = cli("calendar", "earnings", "--start", "2024-01-25", "--end", "2024-01-25", "--fields", "EPS Estimate,Reported EPS,Surprise(%)", "--out", str(tmp_path / "e.csv"), routes=[route])
    assert proc.returncode == 7, proc.stdout[:400]
    assert not (tmp_path / "e.csv").exists()


def test_a_mapping_of_records_honours_an_explicit_limit(cli, tmp_path):
    summary = {"marketSummaryResponse": {"result": [{"exchange": "SNP", "shortName": "S&P 500"}, {"exchange": "DJI", "shortName": "Dow"}], "error": None}}
    status = {"finance": {"marketTimes": [{"marketTime": [{"open": "2024-01-02T09:30:00-05:00", "close": "2024-01-02T16:00:00-05:00", "time": "2024-01-02T16:00:00-05:00", "timezone": [{"short": "EST", "gmtoffset": "-5000"}]}]}]}}
    routes = [{"path": "/v6/finance/quote/marketSummary", "json": summary}, {"path": "/v6/finance/markettime", "json": status}]
    proc, doc = cli("market", "summary", "--limit", "1", "--out", str(tmp_path / "m.csv"), routes=routes)
    assert proc.returncode == 0, proc.stdout[:400]
    assert [r["key"] for r in rows(tmp_path / "m.csv")] == ["DJI"], "exchanges are rows in sorted key order, as the store saves them"
    assert doc["results"][0]["coverage"]["received"] == 2 and doc["results"][0]["coverage"]["shown"] == 1


def test_a_failed_publication_names_a_retry_that_keeps_the_selection(cli, tmp_path):
    out = tmp_path / "race.csv"
    proc, doc = cli("prices", "history", "AAPL", "--period", "1mo", "--fields", "Close", "--out", str(out), routes=[chart("AAPL", [1.0, 2.0]) | {"touch": str(out)}])
    assert "--fields Close" in doc["results"][0]["error"]["fix"]


def test_a_stray_file_beside_the_destination_is_left_alone(cli, tmp_path):
    stray = tmp_path / ".p.csv.1.part"
    stray.write_text("not ours\n")
    proc, doc = cli("prices", "history", "AAPL", "--period", "1mo", "--out", str(tmp_path / "p.csv"), routes=[chart("AAPL", [1.0, 2.0])])
    assert proc.returncode == 0, proc.stdout[:400]
    assert stray.read_text() == "not ours\n"


def test_listing_fields_into_a_file_is_refused(cli, tmp_path):
    """--list-fields names columns; a file of names would read as data."""
    proc, doc = cli("prices", "history", "AAPL", "--list-fields", "--out", str(tmp_path / "f.csv"), routes=[])
    assert proc.returncode == 2 and "--list-fields" in doc["results"][0]["error"]["message"]
    assert not (tmp_path / "f.csv").exists()


def test_an_unwritable_directory_is_a_local_failure_that_keeps_the_rows_reachable(cli, tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o555)
    try:
        proc = cli("prices", "history", "AAPL", "--period", "1mo", "--out", str(locked / "p.csv"), routes=[chart("AAPL", [1.0, 2.0])], raw=True)
    finally:
        locked.chmod(0o755)
    assert "Traceback" not in proc.stderr, proc.stderr[-800:]
    assert proc.returncode == 4, proc.stdout[:300]
    r = json.loads(proc.stdout)["results"][0]
    assert r["error"]["code"] == "local_io" and f"read {r['id']}" in r["error"]["fix"]


# ---- the file is written before the budget is judged, so the document never loses the fact of it --------------------


def path_of_length(base, length):
    """An --out path of exactly `length` characters whose directories exist."""
    directory, name = base, "x.csv"
    while True:
        room = length - len(str(directory)) - 1 - len(name) - 1
        if room <= 200:
            break
        directory = directory / ("d" * 200)
    directory = directory / ("d" * room)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    assert len(str(path)) == length
    return path


def news_statuses():
    """AAA ok, BBB empty, CCC failed, DDD rate limited, EEE therefore not attempted."""
    def body(symbol):
        return {"serviceConfig": {"snippetCount": 5, "s": [symbol]}}
    return [{"path": "/xhr/ncp", "body": body("AAA"), "json": {"data": {"tickerStream": {"stream": [{"id": f"a{i}", "content": {"title": f"t{i}"}} for i in range(3)]}}}},
            {"path": "/xhr/ncp", "body": body("BBB"), "json": {"data": {"tickerStream": {"stream": []}}}},
            {"path": "/xhr/ncp", "body": body("CCC"), "status": 500, "text": "Internal Server Error"},
            {"path": "/xhr/ncp", "body": body("DDD"), "status": 429, "text": "Too Many Requests"}]


def test_a_written_file_survives_a_budget_its_summaries_do_not_fit(cli, tmp_path):
    symbols = [f"S{i:02d}" for i in range(10)]
    out = path_of_length(tmp_path, 132)
    proc, doc = cli("prices", "history", *symbols, "--period", "1mo", "--out", str(out), "--max-chars", "1000",
                    routes=[chart(s, [float(n) for n in range(30)]) for s in symbols])
    assert proc.returncode == 0, proc.stdout[:400]
    assert len(proc.stdout.strip()) <= 1000
    assert doc["receipt"]["out"] == str(out) and doc["receipt"]["rows"] == 300
    assert len(rows(out)) == 300


def test_the_receipt_names_every_target_the_file_does_not_hold(cli, tmp_path):
    out = path_of_length(tmp_path, 400)
    proc, doc = cli("company", "news", "AAA", "BBB", "CCC", "DDD", "EEE", "--limit", "5", "--out", str(out), "--max-chars", "1000", routes=news_statuses())
    assert proc.returncode == 8, proc.stdout[:400]
    assert doc["status"] == "partial" and len(proc.stdout.strip()) <= 1000
    receipt = doc["receipt"]
    assert receipt["out"] == str(out) and receipt["rows"] == 3 and receipt["in_file"] == 1
    assert receipt["missing"] == {"empty": ["BBB"], "error": ["CCC", "DDD"], "not_attempted": ["EEE"]}
    assert {r["target"] for r in rows(out)} == {"AAA"}


def test_a_path_too_long_for_its_own_receipt_is_refused_before_any_request(cli, tmp_path):
    out = path_of_length(tmp_path, 950)
    proc, doc = cli("company", "news", "AAA", "--out", str(out), "--max-chars", "1000", routes=[])
    assert proc.returncode == 2, proc.stdout[:400]
    assert "--max-chars" in doc["results"][0]["error"]["message"] and not out.exists()
    assert len(proc.stdout.strip()) <= 1000, "the refusal of a path too long to report cannot itself carry the path"
