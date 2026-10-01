"""Saved observations: a paid request survives a result that did not fit, and reading it back does not change it."""
import json
import os
from pathlib import Path
import shutil
import time

import pytest

from test_budget import chart_routes, news_routes


def observe(cli, store):
    proc, doc = cli("prices", "history", "AAPL", "--period", "1mo", routes=chart_routes(), store=store)
    assert proc.returncode in (0, 8), proc.stdout[:300]
    return doc["results"][0]["id"]


def test_a_changed_byte_is_refused_rather_than_read_as_the_original(cli, tmp_path):
    store = tmp_path / "s"
    ident = observe(cli, store)
    path = store / f"{ident}.json"
    path.write_text(path.read_text().replace('"AAPL"', '"MSFT"', 1))
    proc, doc = cli("read", ident, routes=[], store=store)
    assert proc.returncode == 2
    assert "do not match their identifier" in doc["results"][0]["error"]["message"]


def test_an_unknown_id_says_where_observations_live(cli, tmp_path):
    proc, doc = cli("read", "0" * 16, routes=[], store=tmp_path / "s")
    assert proc.returncode == 2 and "per store directory" in doc["results"][0]["error"]["message"]
    proc, doc = cli("read", "nonsense", routes=[], store=tmp_path / "s")
    assert proc.returncode == 2 and "not an observation id" in doc["results"][0]["error"]["message"]


def test_retention_deletes_by_age_and_says_nothing_about_being_current(cli, tmp_path):
    """Age is a disk policy. A quote saved a minute ago is stale the moment the market closed, and a statement saved
    last week is not, so the store never decides validity from it."""
    store = tmp_path / "s"
    ident = observe(cli, store)
    old = time.time() - 40 * 86400
    os.utime(store / f"{ident}.json", (old, old))
    cli("--ttl-days", "0", "schema", "prices", routes=[], store=store)
    assert (store / f"{ident}.json").exists(), "retention off deletes nothing"
    cli("--ttl-days", "14", "schema", "prices", routes=[], store=store)
    assert not (store / f"{ident}.json").exists()


# ---- round trip through the CLI -----------------------------------------------------------------------------------


def test_a_read_returns_the_same_values_the_original_call_printed(cli, tmp_path):
    """R5: a recovery that returns a different question's answer is not a recovery."""
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--period", "1y", "--fields", "Close", "--limit", "10", routes=chart_routes(), store=store)
    assert proc.returncode == 0
    first = doc["results"][0]
    proc, back = cli("read", first["id"], "--fields", "Close", "--start", str(first["coverage"]["received"] - 10), routes=[], store=store)
    assert proc.returncode == 0
    again = back["results"][0]
    assert again["data"]["data"] == first["data"]["data"]
    assert again["data"]["index"] == first["data"]["index"]
    assert again["observed_at"] == first["observed_at"], "a re-read is another reading of one observation, not a new one"


def test_a_read_reaches_fields_the_original_projection_left_out(cli, tmp_path):
    """The store holds what the adapter returned, before selection, so a narrowed call does not throw away the rest."""
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--period", "1y", "--fields", "Close", routes=chart_routes(), store=store)
    ident = doc["results"][0]["id"]
    proc, back = cli("read", ident, "--fields", "Open,Volume", "--limit", "3", routes=[], store=store)
    assert proc.returncode == 0, proc.stdout[:300]
    assert back["results"][0]["data"]["columns"] == ["Open", "Volume"]


def test_reading_an_empty_observation_keeps_reporting_it_as_empty(cli, tmp_path):
    """R7-5: a read that succeeded must not erase the original observation's own emptiness."""
    store = tmp_path / "s"
    routes = [{"path": "/xhr/ncp", "json": {"data": {"tickerStream": {"stream": []}}}}]
    proc, doc = cli("company", "news", "AAPL", routes=routes, store=store)
    assert proc.returncode == 7 and doc["results"][0]["status"] == "empty"
    ident = doc["results"][0]["id"]
    proc, back = cli("read", ident, routes=[], store=store)
    assert proc.returncode == 7, proc.stdout[:300]
    assert back["results"][0]["status"] == "empty"
    assert any("does not change that" in w for w in back["results"][0]["warnings"])


def test_a_read_reports_how_long_ago_the_observation_was_made(cli, tmp_path):
    store = tmp_path / "s"
    proc, doc = cli("company", "news", "AAPL", routes=news_routes(3), store=store)
    ident = doc["results"][0]["id"]
    proc, back = cli("read", ident, routes=[], store=store)
    assert proc.returncode == 0
    assert isinstance(back["results"][0]["stored_age_seconds"], (int, float))
    assert "stored_age_seconds" not in doc["results"][0], "a fresh observation has no stored age to report"


def test_the_second_of_two_sibling_leaves_costs_no_request(cli, tmp_path):
    """prices quote and company profile select different sides of one assembled response; the second one reuses the
    observation rather than paying for it again."""
    store = tmp_path / "s"
    routes = [{"path": "/quoteSummary/AAPL", "json": {"quoteSummary": {"result": [{"assetProfile": {"sector": "Technology", "fullTimeEmployees": 10, "country": "United States"}, "financialData": {"financialCurrency": "USD"}}], "error": None}}},
              {"path": "/v7/finance/quote", "json": {"quoteResponse": {"result": [{"symbol": "AAPL", "currency": "USD", "regularMarketPrice": 100, "marketCap": 1}], "error": None}}},
              {"path": "/timeseries/AAPL", "json": {"timeseries": {"result": [], "error": None}}}]
    proc, quote = cli("prices", "quote", "AAPL", routes=routes, store=store)
    assert proc.returncode == 0, proc.stdout[:300]
    ident = quote["results"][0]["id"]
    # no routes at all: any request would be reported as UNEXPECTED NETWORK by the fixture
    proc, profile = cli("company", "profile", "AAPL", "--from", ident, routes=[], store=store)
    assert proc.returncode == 0, proc.stdout[:300]
    r = profile["results"][0]
    assert r["id"] == ident and r["observed_at"] == quote["results"][0]["observed_at"]
    assert r["data"]["sector"] == "Technology"
    assert "sector" not in quote["results"][0]["data"], "the two leaves answer different questions"


def test_a_from_id_of_another_symbol_or_command_is_refused(cli, tmp_path):
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--period", "1mo", routes=chart_routes(), store=store)
    ident = doc["results"][0]["id"]
    proc, refused = cli("company", "profile", "AAPL", "--from", ident, routes=[], store=store)
    assert proc.returncode == 2
    assert "does not hold this command's fields" in refused["results"][0]["error"]["message"]


def test_the_store_directory_is_selectable_so_ids_are_findable_again(cli, tmp_path):
    other = tmp_path / "elsewhere"
    proc, doc = cli("prices", "history", "AAPL", "--period", "1mo", routes=chart_routes(), store=other)
    ident = doc["results"][0]["id"]
    assert json.loads((other / f"{ident}.json").read_text())["command"] == "prices history"
    proc, missing = cli("read", ident, routes=[], store=tmp_path / "empty")
    assert proc.returncode == 2 and "rerun the original command" in missing["results"][0]["error"]["message"]


# ---- observations saved by an earlier version -----------------------------------------------------------------------

# Made by the CLI as it stood before the layout moved to scripts/cli.py (synthetic routes; the values below are the
# ones those routes served). A store outlives the code that wrote it, so these ids must keep reading after any move.
SAVED = Path(__file__).parent / "fixtures/store"
OLD_HISTORY, OLD_QUOTE = "e9171c42d922e848", "c5f6574d8a9c834a"


def old_store(tmp_path):
    """A copy with fresh modification times: retention prunes by age, and a committed file is older than any window."""
    store = tmp_path / "old"
    store.mkdir()
    for path in SAVED.glob("*.json"):
        shutil.copy(path, store / path.name)
    return store


def test_an_observation_saved_by_an_earlier_version_is_still_read(cli, tmp_path):
    store = old_store(tmp_path)
    proc, doc = cli("read", OLD_HISTORY, "--fields", "Close", routes=[], store=store)
    assert proc.returncode == 0, proc.stdout[:400]
    r = doc["results"][0]
    assert r["target"] == "AAPL" and r["id"] == OLD_HISTORY
    assert r["data"]["columns"] == ["Close"]
    assert r["data"]["data"] == [[101.25], [102.5], [103.75], [104], [105.5]]
    assert r["data"]["index"] == ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06"]


def test_an_earlier_versions_quote_still_serves_the_sibling_profile(cli, tmp_path):
    store = old_store(tmp_path)
    proc, doc = cli("company", "profile", "AAPL", "--from", OLD_QUOTE, "--fields", "sector,country", routes=[], store=store)
    assert proc.returncode == 0, proc.stdout[:400]
    assert doc["results"][0]["data"] == {"sector": "Technology", "country": "United States"}
    assert doc["results"][0]["id"] == OLD_QUOTE


# Written by hand in the form versions before 2026-10 saved a quote in: source_time as Yahoo's Unix epoch (1727380800 is 2024-09-26 20:00 UTC).
OLD_EPOCH_QUOTE = "980e71a120088de0"
EPOCH_AS_ISO = "2024-09-26T20:00:00+00:00"


def test_an_earlier_versions_epoch_source_time_prints_as_an_iso_time(cli, tmp_path):
    store = old_store(tmp_path)
    proc, doc = cli("read", OLD_EPOCH_QUOTE, "--fields", "regularMarketPrice", routes=[], store=store)
    assert proc.returncode == 0, proc.stdout[:400]
    assert doc["results"][0]["source_time"] == EPOCH_AS_ISO
    proc, doc = cli("company", "profile", "AAPL", "--from", OLD_EPOCH_QUOTE, "--fields", "sector", routes=[], store=store)
    assert proc.returncode == 0, proc.stdout[:400]
    assert doc["results"][0]["source_time"] == EPOCH_AS_ISO


def test_a_fresh_quote_saves_its_source_time_as_an_iso_time(cli, tmp_path):
    """The saved record carries the time in the form the envelope prints, so a reader of the store meets one time format."""
    store = tmp_path / "s"
    routes = [{"path": "/quoteSummary/AAPL", "json": {"quoteSummary": {"result": [{"assetProfile": {"sector": "Technology"}, "financialData": {"financialCurrency": "USD"}}], "error": None}}},
              {"path": "/v7/finance/quote", "json": {"quoteResponse": {"result": [{"symbol": "AAPL", "currency": "USD", "regularMarketPrice": 100, "regularMarketTime": 1727380800}], "error": None}}},
              {"path": "/timeseries/AAPL", "json": {"timeseries": {"result": [], "error": None}}}]
    proc, doc = cli("prices", "quote", "AAPL", routes=routes, store=store)
    assert proc.returncode == 0, proc.stdout[:400]
    r = doc["results"][0]
    assert r["source_time"] == EPOCH_AS_ISO
    assert json.loads((store / f"{r['id']}.json").read_text())["source_time"] == EPOCH_AS_ISO


def test_a_source_time_no_calendar_can_hold_is_kept_as_received_and_the_response_saved(cli, tmp_path):
    """Converting the time must not cost the paid response: a value outside any date keeps the form the source sent."""
    store = tmp_path / "s"
    routes = [{"path": "/quoteSummary/AAPL", "json": {"quoteSummary": {"result": [{"assetProfile": {"sector": "Technology"}, "financialData": {"financialCurrency": "USD"}}], "error": None}}},
              {"path": "/v7/finance/quote", "json": {"quoteResponse": {"result": [{"symbol": "AAPL", "currency": "USD", "regularMarketPrice": 100, "regularMarketTime": 1e30}], "error": None}}},
              {"path": "/timeseries/AAPL", "json": {"timeseries": {"result": [], "error": None}}}]
    proc, doc = cli("prices", "quote", "AAPL", routes=routes, store=store)
    assert proc.returncode == 0, proc.stdout[:400]
    r = doc["results"][0]
    assert r["source_time"] == 1e30 and (store / f"{r['id']}.json").exists()
    proc, back = cli("read", r["id"], routes=[], store=store)
    assert proc.returncode == 0 and back["results"][0]["source_time"] == 1e30, proc.stdout[:400]


# ---- the store's own contract: nothing lost to an argument, every failure a document -------------------------------


def test_a_negative_retention_is_refused_before_anything_is_deleted(cli, tmp_path):
    """-1 days put the cutoff in the future, so every saved observation counted as expired and was deleted."""
    store = tmp_path / "s"
    ident = observe(cli, store)
    proc, doc = cli("--ttl-days", "-1", "schema", routes=[], store=store)
    assert proc.returncode == 2, proc.stdout[:300]
    assert "--ttl-days" in doc["results"][0]["error"]["message"]
    proc, back = cli("read", ident, routes=[], store=store)
    assert proc.returncode == 0, back["results"][0].get("error")


@pytest.mark.parametrize("argv", [["--start", "-1"], ["--limit", "0"]])
def test_read_checks_its_arguments_before_reading(cli, tmp_path, argv):
    store = tmp_path / "s"
    ident = observe(cli, store)
    before = sorted(p.name for p in store.iterdir())
    out = tmp_path / "slice.csv"
    proc, doc = cli("read", ident, *argv, "--out", str(out), routes=[], store=store)
    assert proc.returncode == 2, proc.stdout[:300]
    assert doc["results"][0]["error"]["code"] == "invalid"
    assert not out.exists() and sorted(p.name for p in store.iterdir()) == before


def assert_local_failure(proc):
    assert "Traceback" not in proc.stderr, proc.stderr[-800:]
    assert proc.returncode == 4, proc.stdout[:300] + proc.stderr[-300:]
    doc = json.loads(proc.stdout)
    assert doc["results"][0]["error"]["code"] == "local_io"
    return doc


def test_a_store_path_under_a_regular_file_is_a_local_failure(cli, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory\n")
    assert_local_failure(cli("schema", routes=[], store=blocker / "store", raw=True))


def test_an_unreadable_saved_observation_is_a_local_failure(cli, tmp_path):
    store = tmp_path / "s"
    (store / ("ab" * 8 + ".json")).mkdir(parents=True)  # the observation's name is taken by a directory
    assert_local_failure(cli("read", "ab" * 8, routes=[], store=store, raw=True))


def test_an_earlier_observation_without_a_requested_count_reads_without_one(cli, tmp_path):
    proc, doc = cli("read", "411a5a0389f4abb1", routes=[], store=old_store(tmp_path))
    assert proc.returncode == 0, proc.stdout[:400]
    assert [row["content.title"] for row in doc["results"][0]["data"]] == ["Headline 0", "Headline 1", "Headline 2"]
    assert "requested" not in doc["results"][0]["coverage"]


@pytest.mark.parametrize("argv", [["--start", "-1"], ["--limit", "0"]])
def test_an_invalid_read_neither_prunes_nor_creates_a_store(cli, tmp_path, argv):
    store = tmp_path / "s"
    ident = observe(cli, store)
    old = time.time() - 40 * 86400
    os.utime(store / f"{ident}.json", (old, old))
    proc, doc = cli("read", ident, *argv, routes=[], store=store)
    assert proc.returncode == 2, proc.stdout[:300]
    assert (store / f"{ident}.json").exists(), "an invalid call applied retention"
    fresh = tmp_path / "never-created"
    proc, doc = cli("read", ident, *argv, routes=[], store=fresh)
    assert proc.returncode == 2 and not fresh.exists()


def test_a_target_that_fails_after_its_response_was_saved_still_names_the_saved_id(cli, tmp_path):
    """The response was paid for and saved before the projection was refused; without the id the only way back to it
    is a second request, and a result without an id reads as nothing saved."""
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--period", "1mo", "--fields", "NoSuchColumn", routes=chart_routes(), store=store)
    r = doc["results"][0]
    assert r["status"] == "error" and r["error"]["code"] == "invalid", proc.stdout[:300]
    assert r.get("id") and (store / f"{r['id']}.json").exists(), r
    proc, back = cli("read", r["id"], "--fields", "Close", "--limit", "2", routes=[], store=store)
    assert proc.returncode == 0, proc.stdout[:300]
