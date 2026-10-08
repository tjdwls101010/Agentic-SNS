"""Thirty symbols in one call: thirty target statuses, one long file, each target's full range, and no request made twice."""
from test_cli import year_of_bars

SYMBOLS = [f"S{i:02d}" for i in range(30)]


def test_thirty_symbols_a_year_each_in_one_call(cli):
    routes = [route for symbol in SYMBOLS for route in year_of_bars(symbol)]
    run = cli("history", *SYMBOLS, "--period", "1y", routes=routes)
    assert run.code == 0, run
    assert [r["target"] for r in run.doc["results"]] == SYMBOLS and {r["status"] for r in run.doc["results"]} == {"ok"}
    assert [r["rows"] for r in run.doc["results"]] == [250] * 30
    assert run.doc["file"]["rows"] == 7500 and len(run.rows) == 7500
    spans = {}
    for row in run.rows:
        spans.setdefault(row["target"], []).append(row["Date"][:10])
    assert {s: (min(d), max(d), len(d)) for s, d in spans.items()} == {s: ("2024-01-02", "2024-09-07", 250) for s in SYMBOLS}
    asked = [r["path"].rsplit("/", 1)[-1] for r in run.requests]
    assert sorted(set(asked)) == SYMBOLS
    assert max(asked.count(s) for s in SYMBOLS) <= 2, "each symbol is read once (plus the library's one time-zone lookup on a cold cache)"
    assert len(run.proc.stdout.strip()) <= 8000 and run.doc["trimmed"] is True
