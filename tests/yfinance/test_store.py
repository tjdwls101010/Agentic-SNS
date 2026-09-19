"""Saved observations: a paid request survives a result that did not fit, and reading it back does not change it."""
import json
import sys

import pytest

from conftest import SCRIPTS

sys.path.insert(0, str(SCRIPTS))

import store as store_module  # noqa: E402
from output import InputError  # noqa: E402
from test_budget import chart_routes, news_routes  # noqa: E402


def test_the_same_observation_saved_twice_is_one_immutable_record(tmp_path):
    saved = store_module.Store(tmp_path)
    record = {"command": "prices history", "target": "AAPL", "data": {"a": 1}}
    first, second = saved.save(record), saved.save(dict(record))
    assert first == second
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert saved.load(first) == record


def test_a_changed_byte_is_refused_rather_than_read_as_the_original(tmp_path):
    saved = store_module.Store(tmp_path)
    ident = saved.save({"command": "prices history", "target": "AAPL", "data": {"a": 1}})
    path = tmp_path / f"{ident}.json"
    path.write_text(path.read_text().replace('"a":1', '"a":2'))
    with pytest.raises(InputError, match="do not match their identifier"):
        saved.load(ident)


def test_an_unknown_id_says_where_observations_live(tmp_path):
    saved = store_module.Store(tmp_path)
    with pytest.raises(InputError, match="per store directory"):
        saved.load("0" * 16)
    with pytest.raises(InputError, match="not an observation id"):
        saved.load("nonsense")


def test_retention_deletes_by_age_and_says_nothing_about_being_current(tmp_path):
    """Age is a disk policy. A quote saved a minute ago is stale the moment the market closed, and a statement saved
    last week is not, so the store never decides validity from it."""
    saved = store_module.Store(tmp_path)
    ident = saved.save({"command": "prices quote", "target": "AAPL", "data": {}})
    import os
    import time
    old = time.time() - 40 * 86400
    os.utime(tmp_path / f"{ident}.json", (old, old))
    assert saved.prune(14) == 1
    assert saved.prune(0) == 0  # retention off deletes nothing


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
