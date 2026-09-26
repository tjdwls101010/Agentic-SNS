"""Opt-in checks against the real Yahoo Finance; run with `-m live`.

Every leaf is called the way a model first reaches for it — positional arguments only, every other value left to the
command's own default — because a first call that fails makes "the model chooses the range" impossible: you cannot
choose what you were never shown. The recoveries are then executed verbatim, and a declared sort direction is checked
against the order the source actually publishes, since that declaration is the one thing no test fixture can confirm.
"""

import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest

CLI = Path(__file__).resolve().parents[2] / ".claude/skills/yfinance/scripts/cli.py"

SYMBOL = {"fund": "SPY"}
POSITIONAL = {("market", "sector"): ["technology"], ("market", "industry"): ["software-infrastructure"],
              ("screen", "run"): ["--preset", "day_gainers"], ("search", ""): ["Apple"]}


def defaults_for(group, name):
    if (group, name) in POSITIONAL:
        return POSITIONAL[group, name]
    if group in {"prices", "company", "financials", "analysts", "holders", "fund", "options"}:
        return [SYMBOL.get(group, "AAPL")]
    return []


def run(arguments, store, timeout=180):
    env = dict(os.environ, YF_STORE=str(store))
    proc = subprocess.run(["uv", "run", "--quiet", str(CLI), *arguments],
                          capture_output=True, text=True, env=env, cwd=str(store.parent), timeout=timeout)
    return proc, (json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else None)


def schema(*scope):
    """Offline, and the only catalogue a reader has; the live checks enumerate from it rather than from the source."""
    proc = subprocess.run([sys.executable, str(CLI), "schema", *scope], capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, YF_STORE=os.environ.get("YF_STORE", "/tmp/yf-live-schema")))
    return json.loads(proc.stdout)["results"][0]["data"]


EVERY_LEAF = sorted((group, leaf) for group, leaves in schema()["commands"].items() for leaf in leaves)

# The column each leaf's rows are dated by. The order a source publishes in is the one fact a fixture cannot confirm,
# so this table is the test's own expectation, checked against what the source actually sends.
DATED_BY = {("prices", "history"): "index", ("prices", "actions"): "index", ("company", "shares"): "index",
            ("company", "filings"): "date", ("analysts", "upgrades"): "index", ("analysts", "history"): "index",
            ("holders", "institutional"): "Date Reported", ("holders", "fund"): "Date Reported",
            ("holders", "insider-transactions"): "Start Date", ("holders", "insider-roster"): "Latest Transaction Date",
            ("calendar", "earnings"): "Event Start Date", ("calendar", "economic"): "Event Time",
            ("calendar", "ipo"): "Date", ("calendar", "splits"): "Payable On"}


def keeps_newest(group, name):
    return "newest" in schema(group, *([name] if name else []))["default_window"]["limit_keeps"]


@pytest.mark.live
@pytest.mark.parametrize("key", EVERY_LEAF, ids=lambda k: f"{k[0]} {k[1]}".strip())
def test_every_leaf_answers_at_its_own_defaults(key, tmp_path):
    """Proposition 1: a first call succeeds inside the default budget for every leaf, with no argument supplied but
    the target. Four leaves failed this before the rewrite, and a leaf that cannot answer once cannot be narrowed."""
    group, name = key
    arguments = [group] + ([name] if name else []) + defaults_for(group, name)
    proc, doc = run(arguments, tmp_path / "store")
    assert proc.returncode in (0, 7), proc.stdout[:800] + proc.stderr[-400:]
    assert len(proc.stdout.strip()) <= 20000, "a default answer has to fit the default budget"
    result = doc["results"][0]
    if result["status"] == "empty":
        pytest.skip(f"{group} {name} legitimately returned nothing for this target")
    coverage = result.get("coverage") or {}
    if coverage.get("received") is not None:
        assert coverage["shown"] <= coverage["received"]
        assert coverage.get("truncated_by") != "budget", "a leaf's own default window should fit without the budget cutting it"


@pytest.mark.live
@pytest.mark.parametrize("key,date_column", sorted(DATED_BY.items()),
                         ids=lambda v: v if isinstance(v, str) else "")
def test_the_declared_order_matches_the_order_the_source_publishes(key, date_column, tmp_path):
    """Proposition 3: `recent` decides which end a limit keeps, and it is the one declaration a fixture cannot check.
    Measured, the direction differs within `analysts` and within `calendar`, so each leaf is pinned to reality here."""
    group, name = key
    path = f"{group} {name}".strip()
    recent = keeps_newest(group, name)
    arguments = [group] + ([name] if name else []) + defaults_for(group, name) + ["--limit", "40"]
    if group == "prices":
        arguments += ["--period", "1y"]
    proc, doc = run(arguments, tmp_path / "store")
    if proc.returncode not in (0, 8):
        pytest.skip(f"{path} did not return rows: {proc.stdout[:200]}")
    data = doc["results"][0]["data"]
    if isinstance(data, list):  # a record list, such as the filing entries
        values = [row.get(date_column) for row in data if isinstance(row, dict)]
    elif date_column == "index":
        values = data["index"]
    elif date_column in data.get("columns", []):
        values = [row[data["columns"].index(date_column)] for row in data["data"]]
    else:
        values = []
    dates = [str(v)[:10] for v in values if v]
    if len(dates) < 2:
        pytest.skip(f"{path} returned too few dated rows to judge an order")
    ascending = dates == sorted(dates)
    descending = dates == sorted(dates, reverse=True)
    if ascending and descending:
        # every row carries the same date, so there is no direction here to contradict the declaration
        pytest.skip(f"{path} returned one date across every row ({dates[0]})")
    if not (ascending or descending):
        pytest.skip(f"{path} is not published in date order at all")
    assert recent is ascending, (
        f"{path} declares newest-kept={recent} but the source published {'oldest' if ascending else 'newest'} first; "
        f"a limit would keep the wrong end of {dates[0]}..{dates[-1]}")


@pytest.mark.live
def test_a_budget_narrowed_range_is_partial_and_read_reaches_the_whole_of_it(tmp_path):
    """Propositions 4 and 5: a paid response is not thrown away, and walking it back returns every row exactly once."""
    store = tmp_path / "store"
    proc, doc = run(["prices", "history", "AAPL", "--period", "5y", "--fields", "Close"], store)
    assert proc.returncode == 8, proc.stdout[:400]
    first = doc["results"][0]
    assert first["coverage"]["truncated_by"] == "budget" and first["coverage"]["kept"] == "newest"
    received, ident = first["coverage"]["received"], first["id"]

    seen, start, calls = [], 0, 0
    while calls < 15:
        proc, page = run(["read", ident, "--fields", "Close", "--start", str(start), "--limit", "400"], store)
        assert proc.returncode in (0, 8), proc.stdout[:400]
        result = page["results"][0]
        seen += result["data"]["index"]
        calls += 1
        following = result.get("continuation")
        if not following:
            break
        start = following["start"]
    assert len(seen) == len(set(seen)) == received, "reading back skipped or repeated rows"
    assert seen[-len(first["data"]["index"]):] == first["data"]["index"], "the printed window was not the newest rows"
    assert isinstance(page["results"][0]["stored_age_seconds"], (int, float))


@pytest.mark.live
def test_following_an_oversized_recovery_verbatim_recovers_the_same_question(tmp_path):
    """Proposition 2. The recovery is parsed out of the sentence and run as written; a fix that names a narrowing
    which does not fit is the same defect one step later."""
    store = tmp_path / "store"
    proc, doc = run(["analysts", "upgrades", "AAPL", "--limit", "900", "--max-chars", "4000"], store)
    assert proc.returncode in (8, 9), proc.stdout[:400]
    result = doc["results"][0]
    if proc.returncode == 9:
        fix = result["error"]["fix"]
        found = re.search(r"\bread ([0-9a-f]{16})((?: --\S+(?: [^\s,.]+)?)*)", fix)
        assert found, fix
        proc, back = run(["read", found[1], *shlex.split(found[2])], store)
        assert proc.returncode in (0, 8), fix + "\n" + proc.stdout[:400]
        assert back["results"][0]["data"]
        raised = re.search(r"--max-chars (\d+)", fix)
        proc, whole = run(["--max-chars", raised[1], "analysts", "upgrades", "AAPL", "--limit", "900"], store)
        assert proc.returncode in (0, 8) and len(proc.stdout.strip()) <= int(raised[1])
    else:
        assert result["coverage"]["truncated_by"] == "budget" and result["id"]


@pytest.mark.live
def test_a_statement_reports_the_currency_it_is_reported_in(tmp_path):
    """Proposition 6. A price in one currency over a profit in another is wrong by the exchange rate, and the value
    was one lookup away while the CLI reported null."""
    proc, doc = run(["financials", "income", "TM", "--periods", "2"], tmp_path / "store")
    assert proc.returncode == 0, proc.stdout[:400]
    context = doc["results"][0]["context"]
    assert context["currency"] == "JPY"
    assert context["quote_currency"] == "USD"
    assert context["currency"] != context["quote_currency"]


@pytest.mark.live
@pytest.mark.parametrize("interval,days", [("1m", 8), ("5m", 60), ("30m", 60)])
def test_every_declared_interval_limit_has_a_probe_behind_it(interval, days, tmp_path):
    """Each value in `limits` comes from the source's own refusal, and the fix names the argument to change rather
    than telling the reader to doubt the symbol."""
    declared = schema("prices", "history")["limits"]
    assert any(interval in key for key in declared), f"{interval} is probed here but not declared"
    proc, doc = run(["prices", "history", "AAPL", "--period", "1y", "--interval", interval], tmp_path / "store")
    assert proc.returncode == 6, proc.stdout[:400]
    error = doc["results"][0]["error"]
    assert str(days) in error["fix"], error["fix"]
    assert "--period" in error["fix"] or "--start" in error["fix"]
    assert "verify the symbol" not in error["fix"]


@pytest.mark.live
def test_an_inclusive_calendar_end_returns_that_day(tmp_path):
    """A single-day window answered "nothing" for days that had events, while the CLI declared the boundary inclusive
    and the validator explicitly allowed start == end."""
    proc, doc = run(["calendar", "earnings", "--start", "2026-10-01", "--end", "2026-10-01"], tmp_path / "store")
    assert proc.returncode in (0, 7), proc.stdout[:400]
    result = doc["results"][0]
    if result["status"] == "empty":
        pytest.skip("no earnings on the probed day")
    assert result["conditions"]["dates"]["status"] == "confirmed"
    assert result["conditions"]["dates"]["evidence"]["range"] == ["2026-10-01", "2026-10-01"]


@pytest.mark.live
def test_an_unserved_region_is_refused_instead_of_answering_with_another_country(tmp_path):
    """An unserved code returned the United States result with no warning, which is indistinguishable from a real
    answer. The closed choice list removes the invalid call rather than reporting it afterwards."""
    proc, doc = run(["market", "sector", "technology", "--region", "ZZ", "--dataset", "top-companies"], tmp_path / "store")
    assert proc.returncode == 2
    assert "invalid choice" in doc["results"][0]["error"]["message"]
    proc, served = run(["market", "sector", "technology", "--region", "KR", "--dataset", "top-companies"], tmp_path / "store")
    assert proc.returncode == 0, proc.stdout[:300]
    symbols = served["results"][0]["data"]["index"]
    assert any(str(s).endswith(".KS") for s in symbols), symbols[:5]


@pytest.mark.live
def test_the_two_sibling_leaves_share_one_observation(tmp_path):
    store = tmp_path / "store"
    proc, quote = run(["prices", "quote", "AAPL"], store)
    assert proc.returncode == 0, proc.stdout[:300]
    ident = quote["results"][0]["id"]
    proc, profile = run(["company", "profile", "AAPL", "--from", ident], store)
    assert proc.returncode == 0, proc.stdout[:300]
    assert profile["results"][0]["observed_at"] == quote["results"][0]["observed_at"]
    assert set(profile["results"][0]["data"]) != set(quote["results"][0]["data"])


@pytest.mark.live
def test_the_fund_multiples_really_are_reciprocals(tmp_path):
    """The declaration says these arrive inverted; if the source ever corrects that, the contract has to fail loudly
    rather than keep telling readers to invert a value that no longer needs it."""
    proc, doc = run(["fund", "equity", "SPY"], tmp_path / "store")
    assert proc.returncode == 0, proc.stdout[:300]
    data = doc["results"][0]["data"]
    row = data["index"].index("Price/Earnings")
    value = data["data"][row][0]
    assert value and 0 < value < 1, f"Price/Earnings came back as {value}"
    assert 5 < 1 / value < 80, "the reciprocal should be a plausible index multiple"


@pytest.mark.live
def test_a_growth_threshold_in_a_query_is_on_a_different_scale_from_the_same_field_in_a_quote(tmp_path):
    """Confirmed by measurement, and the reason it matters is that neither call fails: a reader who carries the quote's
    ratio into a query screens for a hundredth of what they meant and gets a plausible list back."""
    store = tmp_path / "store"
    points = '{"operator":"AND","operands":[{"operator":"EQ","operands":["region","us"]},{"operator":"BTWN","operands":["quarterlyrevenuegrowth.quarterly",20,30]}]}'
    proc, doc = run(["screen", "run", "--query", points, "--limit", "5", "--sort", "intradaymarketcap", "--no-ascending"], store)
    assert proc.returncode == 0, proc.stdout[:400]
    symbols = [row["symbol"] for row in doc["results"][0]["data"]]
    assert symbols, doc

    proc, quote = run(["prices", "quote", symbols[0], "--fields", "symbol"], store)
    assert proc.returncode == 0
    proc, listed = run(["prices", "quote", symbols[0], "--list-fields", "--filter", "revenueGrowth"], store)
    assert proc.returncode == 0
    proc, ratio = run(["prices", "quote", symbols[0], "--fields", "revenueGrowth"], store)
    assert proc.returncode == 0, proc.stdout[:300]
    growth = ratio["results"][0]["data"]["revenueGrowth"]
    assert growth is None or 0.15 < growth < 0.40, (
        f"the query bound 20..30 selected {symbols[0]}, whose quote reports {growth}; the two scales are 100x apart "
        "and the leaf's query_scale contract states it")
    assert "percentage points" in schema("screen", "run")["interpretation"]["query_scale"]
