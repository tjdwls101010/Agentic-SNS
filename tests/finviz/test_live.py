"""Opt-in checks against anonymous Finviz; run with `-m live`. No account, no SEC originals.

Every leaf is called the way a model first reaches for it — positional arguments only, every other
value left to the command's own default — because a first call that fails is what makes "the model
chooses the range" impossible. The recovery sentences are then executed verbatim, since a fix that
names a narrowing which does not fit is the same defect one step later.
"""

import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

CLI = Path(__file__).resolve().parents[2] / ".claude/skills/finviz/scripts/finviz.py"

# Positional arguments only: what a leaf answers before anyone narrows it.
DEFAULTS = [
    ["search", "Agilent"],
    ["screen", "filters"], ["screen", "signals"], ["screen", "columns"], ["screen", "views"], ["screen", "run"],
    ["stock", "snapshot", "A"], ["stock", "profile", "A"], ["stock", "ratings", "A"], ["stock", "news", "A"],
    ["stock", "insiders", "A"], ["stock", "ownership", "A"], ["stock", "flows", "SPY"], ["stock", "earnings", "A"],
    ["stock", "forecast", "A"], ["stock", "dividends", "A"], ["stock", "revenue", "A"], ["stock", "short-interest", "A"],
    ["stock", "options", "A"], ["stock", "filings", "A"], ["stock", "statement", "A"], ["stock", "prices", "A"],
    ["groups", "options"], ["groups", "table"], ["groups", "performance"],
    ["market", "quotes", "futures"], ["market", "performance", "futures"], ["market", "map"], ["market", "bubbles"],
    ["calendar", "earnings"], ["calendar", "dividends"], ["calendar", "economic"], ["calendar", "season"],
    ["news", "headlines"], ["news", "pulse"],
    ["insiders", "trades"],
    ["open", "https://finviz.com/quote.ashx?t=AAPL&p=d"],
    ["stock", "snapshot", "AAPL", "MSFT", "NVDA"],
]

# Calls that deliberately ask for more than one screenful: each must name a recovery that works.
OVERSIZED = [
    ["screen", "filters", "--options"],
    ["market", "quotes", "futures", "--sparkline"],
    ["market", "bubbles", "--index", "sp500"],
    ["insiders", "trades", "--limit", "200"],
    ["stock", "options", "A", "--strikes", "0"],
    ["stock", "earnings", "A", "--dataset", "revisions", "--limit", "5000"],
]


def run(arguments, tmp_path, timeout=180):
    proc = subprocess.run([sys.executable, str(CLI), "--store", str(tmp_path / "observations.sqlite3"), *arguments], text=True, capture_output=True, timeout=timeout)
    return proc, json.loads(proc.stdout) if proc.stdout else None


@pytest.mark.live
@pytest.mark.parametrize("arguments", DEFAULTS, ids=lambda x: " ".join(x))
def test_every_leaf_answers_at_its_own_defaults(arguments, tmp_path):
    proc, doc = run(arguments, tmp_path)
    assert proc.returncode == 0, proc.stdout[:1500] + proc.stderr
    assert doc["status"] == "ok", doc
    assert proc.stderr == ""
    assert len(proc.stdout.strip()) <= 20000, "a default answer has to fit the default budget"
    for result in doc["results"]:
        assert result["data"] not in (None, [], {})
        coverage = result.get("coverage") or {}
        if coverage.get("received") is not None and coverage.get("shown") is not None:
            assert coverage["shown"] <= coverage["received"]  # what a window left out is stated, never silent
    result = doc["results"][0]
    if arguments[:2] == ["stock", "snapshot"] and len(arguments) == 3:
        eps = [m for m in result["data"]["metrics"] if m["label"] == "EPS next Y"]
        assert len(eps) == 2 and len({m["definition"] for m in eps}) == 2
    if arguments[:2] == ["screen", "filters"]:
        assert result["coverage"]["shown"] == result["coverage"]["received"] >= 80  # the whole catalogue in one call
        assert all("definition" in f for f in result["data"])


@pytest.mark.live
@pytest.mark.parametrize("arguments", OVERSIZED, ids=lambda x: " ".join(x))
def test_following_a_too_large_fix_verbatim_recovers_the_data(arguments, tmp_path):
    proc, doc = run(arguments, tmp_path)
    assert proc.returncode == 9, proc.stdout[:800]
    fix = doc["results"][0]["error"]["fix"]
    named = re.search(r"read (\w+) --pointer (\S+) --start (\d+) --limit (\d+)", fix)
    assert named, fix
    proc, recovered = run(["read", named[1], "--pointer", named[2], "--start", named[3], "--limit", named[4]], tmp_path)
    assert proc.returncode == 0, fix + "\n" + proc.stdout[:800]
    assert recovered["results"][0]["data"]
    echoed = re.search(r"--max-chars (\d+)", fix)
    proc, whole = run(["--max-chars", echoed[1], *arguments], tmp_path)
    assert proc.returncode == 0 and len(proc.stdout.strip()) <= int(echoed[1])  # the size it names is the size it needs


@pytest.mark.live
def test_a_raw_response_over_the_budget_is_readable_in_windows(tmp_path):
    proc, doc = run(["market", "quotes", "futures", "--sparkline"], tmp_path)
    ident = doc["results"][0]["id"]
    proc, refused = run(["read", ident, "--raw"], tmp_path)
    assert proc.returncode == 9
    window = re.search(r"--chars (\d+-\d+)", refused["results"][0]["error"]["fix"])[1]
    text, windows = "", 0
    while window:
        proc, page = run(["read", ident, "--raw", "--chars", window], tmp_path)
        assert proc.returncode == 0, proc.stdout[:400]
        result = page["results"][0]
        text += result["data"]
        windows += 1
        window = (result.get("continuation") or {}).get("chars")
    assert windows > 1 and len(text) == result["selection"]["received"]
    assert isinstance(json.loads(text), dict)


@pytest.mark.live
def test_the_overview_sections_cost_one_request(tmp_path):
    proc, doc = run(["stock", "snapshot", "AAPL"], tmp_path)
    first = doc["results"][0]
    for leaf in ("news", "ratings", "insiders", "ownership"):
        proc, again = run(["stock", leaf, "AAPL", "--from", first["id"]], tmp_path)
        assert proc.returncode == 0, proc.stdout[:400]
        assert again["results"][0]["id"] == first["id"]
        assert again["results"][0]["observed_at"] == first["observed_at"]
    import sqlite3

    stored = sqlite3.connect(tmp_path / "observations.sqlite3").execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert stored == 1, "five sections were read from one saved page"


@pytest.mark.live
def test_a_selector_the_source_ignores_is_reported_as_not_applied(tmp_path):
    proc, doc = run(["calendar", "economic", "--date", "2026-01-05", "--limit", "1"], tmp_path)
    assert proc.returncode == 0
    condition = doc["results"][0]["conditions"]["date"]
    assert condition["status"] in ("confirmed", "not_applied")
    assert condition["evidence"]["source_date_from"], "the judgement comes from the source's own start date"
    if condition["status"] == "not_applied":
        assert condition["evidence"]["source_date_from"] != "2026-01-05"
    proc, screened = run(["screen", "run", "--filters", "cap_bogus", "--limit", "1"], tmp_path)
    assert screened["results"][0]["conditions"]["filters"]["status"] == "not_applied"


@pytest.mark.live
def test_saved_observations_are_rereadable_and_an_unknown_ticker_is_reported(tmp_path):
    proc, doc = run(["stock", "snapshot", "A"], tmp_path)
    saved = doc["results"][0]["id"]
    proc, again = run(["read", saved, "--pointer", "/data/metrics", "--limit", "1"], tmp_path)
    assert proc.returncode == 0 and again["results"][0]["data"][0]["label"]
    assert again["results"][0]["selection"]["context"]["ticker"] == "A"  # a slice keeps what it needs to be read
    proc, pointers = run(["inspect", saved], tmp_path)
    assert {"/data", "/data/metrics"} <= {entry["pointer"] for entry in pointers["results"][0]["data"]}
    proc, missing = run(["stock", "snapshot", "ZZZZQ"], tmp_path)
    assert proc.returncode == 6 and missing["results"][0]["error"]["code"] == "http_error"


@pytest.mark.live
def test_a_finviz_hosted_article_is_readable_when_one_is_listed(tmp_path):
    proc, doc = run(["news", "headlines", "--limit", "60"], tmp_path)
    hosted = next((item["url"] for item in doc["results"][0]["data"] if re.search(r"finviz\.com/news/\d+/", item["url"] or "")), None)
    if hosted is None:
        pytest.skip("no finviz-hosted article in the current headlines")
    proc, article = run(["news", "article", hosted], tmp_path)
    assert proc.returncode == 0 and article["results"][0]["data"]["paragraphs"]
