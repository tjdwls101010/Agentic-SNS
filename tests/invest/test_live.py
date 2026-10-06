"""Opt-in checks against the real Yahoo Finance; run with `-m live`.

Two kinds of check. Every kind answers at its own defaults, the way a model first calls it. And the relations behind each `verified` unit, the measured screen scales and the source's own limits are measured again with the same formulas and tolerances as tests/invest/test_units.py: a relation the live data cannot decide (missing values, a rate limit, a quote between sessions) is inconclusive and skipped, never counted as a pass. One retry, then stop.
"""
import csv
import json
import math
import os
from pathlib import Path
import subprocess

import pytest

from invest import load

CLI = Path(__file__).resolve().parents[2] / ".claude/skills/invest/scripts/cli.py"
POSITIONAL = {"search": ["Apple"], "market": {"summary": [], "sector": ["technology"], "industry": ["software-infrastructure"]},
              "screen": {"run": ["--preset", "day_gainers"]}, "calendar": {}, "fund": "SPY"}


def run(arguments, tmp_path, retry=True):
    proc = subprocess.run(["uv", "run", "--quiet", str(CLI), *arguments], capture_output=True, text=True, timeout=300,
                          env=dict(os.environ, INVEST_DATA=str(tmp_path / "data")), cwd=tmp_path)
    doc = json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else None
    if retry and doc and any((r.get("error") or {}).get("code") == "rate_limited" for r in doc["results"]):
        return run(arguments, tmp_path, retry=False)
    if doc and any((r.get("error") or {}).get("code") == "rate_limited" for r in doc["results"]):
        pytest.skip("inconclusive: Yahoo rate-limited the call twice")
    return proc, doc


def records(doc):
    return json.loads(Path(doc["file"]["path"]).read_text())


def rows(doc):
    with open(doc["file"]["path"], newline="") as handle:
        return list(csv.DictReader(handle))


def every_kind():
    for command, kinds in sorted(load.kinds().items()):
        for kind in kinds or [""]:
            yield command, kind


def defaults_for(command, kind):
    spec = POSITIONAL.get(command)
    if isinstance(spec, dict):
        return spec.get(kind, [])
    if isinstance(spec, list):
        return spec
    return [spec or "AAPL"] if command not in ("screen", "calendar") else []


@pytest.mark.live
@pytest.mark.parametrize("command,kind", list(every_kind()), ids=lambda v: v or "-")
def test_every_kind_answers_at_its_own_defaults(command, kind, tmp_path):
    proc, doc = run([command] + ([kind] if kind else []) + defaults_for(command, kind), tmp_path)
    assert proc.returncode in (0, 7, 8), proc.stdout[:800] + proc.stderr[-400:]
    assert len(proc.stdout.strip()) <= 8000, "the default receipt fits the default --max-chars"
    receipt = json.loads(Path(doc["receipt_path"]).read_text())
    assert not [n for n, s in receipt["unit_status"].items() if s == "undeclared"], f"{command} {kind}: a column Yahoo added has no declared unit"


@pytest.mark.live
def test_ko_dividend_yield_is_the_rate_over_the_price(tmp_path):
    _, doc = run(["quote", "KO"], tmp_path)
    data = records(doc)[0]["data"]
    if not all(data.get(k) for k in ("dividendYield", "dividendRate", "regularMarketPrice")):
        pytest.skip("inconclusive: a field is missing")
    assert math.isclose(data["dividendYield"], data["dividendRate"] / data["regularMarketPrice"], abs_tol=0.0005)


@pytest.mark.live
def test_the_two_surprise_scales_still_meet(tmp_path):
    _, history = run(["analysts", "eps-history", "AAPL"], tmp_path)
    latest = max(rows(history), key=lambda r: r["quarter"])
    actual, estimate, surprise = (float(latest[k]) for k in ("epsActual", "epsEstimate", "surprisePercent"))
    assert math.isclose(surprise, (actual - estimate) / abs(estimate), abs_tol=0.0005)
    _, dates = run(["calendar", "earnings", "AAPL", "--limit", "25"], tmp_path)
    reported = [r for r in rows(dates) if r.get("Surprise(%)")]
    if not reported:
        pytest.skip("inconclusive: no reported surprise in the calendar")
    assert any(math.isclose(float(r["Surprise(%)"]), surprise, abs_tol=0.0005) for r in reported), "the calendar's surprise is no longer surprisePercent x 100"


@pytest.mark.live
def test_52_week_change_still_changes_scale_with_the_instrument_type(tmp_path):
    _, index = run(["quote", "^GSPC"], tmp_path)
    i = records(index)[0]["data"]
    assert i["quoteType"] == "INDEX" and math.isclose(i["52WeekChange"], i["fiftyTwoWeekChangePercent"], abs_tol=1e-6)
    _, stock = run(["quote", "AAPL"], tmp_path)
    s = records(stock)[0]["data"]
    assert math.isclose(s["52WeekChange"], s["fiftyTwoWeekChangePercent"], abs_tol=1e-4)


@pytest.mark.live
def test_the_fund_reported_pe_is_still_a_plausible_multiple(tmp_path):
    """A plausibility check, not verification: the declaration stays `declared`."""
    _, doc = run(["fund", "equity", "SPY"], tmp_path)
    pe = next(r for r in rows(doc) if r["metric"] == "Price/Earnings" and r["source_column"] == "SPY")
    if not pe["value"]:
        pytest.skip("inconclusive: no P/E reported")
    assert 5 < float(pe["value"]) < 80


@pytest.mark.live
def test_a_growth_bound_written_as_a_ratio_still_screens_that_growth(tmp_path):
    query = '{"operator":"AND","operands":[{"operator":"EQ","operands":["region","us"]},{"operator":"BTWN","operands":["quarterlyrevenuegrowth.quarterly",0.2,0.3]},{"operator":"GT","operands":["intradaymarketcap",10000000000]}]}'
    _, doc = run(["screen", "run", "--query", query, "--limit", "5"], tmp_path)
    symbols = [r["symbol"] for r in rows(doc)]
    if not symbols:
        pytest.skip("inconclusive: nothing matched")
    _, quote = run(["quote", symbols[0], "--fields", "revenueGrowth"], tmp_path)
    growth = records(quote)[0]["data"].get("revenueGrowth")
    if growth is None:
        pytest.skip("inconclusive: no revenueGrowth for the first match")
    assert 0.15 < growth < 0.35, f"{symbols[0]} matched 0.2-0.3 but its revenueGrowth is {growth}: the screener's scale moved"


@pytest.mark.live
@pytest.mark.parametrize("interval,days", [("1m", 8), ("5m", 60)])
def test_intraday_refusals_still_state_their_limit(interval, days, tmp_path):
    proc, doc = run(["history", "AAPL", "--period", "1y", "--interval", interval], tmp_path)
    assert proc.returncode == 6, proc.stdout[:400]
    error = doc["results"][0]["error"]
    assert error["code"] == "source_constraint" and str(days) in error["fix"]


@pytest.mark.live
def test_an_unserved_region_is_refused_and_a_served_one_answers_with_its_own_companies(tmp_path):
    proc, doc = run(["market", "sector", "technology", "--region", "ZZ", "--dataset", "top-companies"], tmp_path)
    assert proc.returncode == 2
    proc, served = run(["market", "sector", "technology", "--region", "KR", "--dataset", "top-companies"], tmp_path)
    assert proc.returncode == 0, proc.stdout[:300]
    assert any(r["symbol"].endswith(".KS") for r in rows(served))


@pytest.mark.live
def test_an_inclusive_calendar_end_returns_that_day(tmp_path):
    proc, doc = run(["calendar", "earnings", "--start", "2026-10-01", "--end", "2026-10-01"], tmp_path)
    if doc["results"][0]["status"] == "empty":
        pytest.skip("inconclusive: no earnings on the probed day")
    dates = doc["results"][0]["conditions"]["dates"]
    assert dates["status"] == "confirmed" and dates["evidence"]["range"] == ["2026-10-01", "2026-10-01"]


@pytest.mark.live
def test_a_statement_is_still_reported_in_its_own_currency(tmp_path):
    _, doc = run(["financials", "income", "TM"], tmp_path)
    result = doc["results"][0]
    assert (result["financial_currency"], result["currency"]) == ("JPY", "USD")
