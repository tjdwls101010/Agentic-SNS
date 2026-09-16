"""Opt-in checks against anonymous Finviz, one per command; run with `-m live`. No account, no SEC originals."""

import json
from pathlib import Path
import subprocess
import sys

import pytest

CLI = Path(__file__).resolve().parents[2] / ".claude/skills/finviz/scripts/finviz.py"
CASES = [
    (["search", "Agilent"], "ok"),
    (["screen", "filters", "--filter", "cap"], "ok"),
    (["screen", "signals"], "ok"),
    (["screen", "columns", "--filter", "valuation"], "ok"),
    (["screen", "run", "--filters", "sec_technology,cap_largeover", "--limit", "3"], "ok"),
    (["screen", "run", "--columns", "ticker,marketCap", "--sort=-marketcap", "--limit", "2"], "ok"),
    (["stock", "snapshot", "A", "--filter", "eps"], "ok"),
    (["stock", "profile", "A"], "ok"),
    (["stock", "ratings", "A", "--limit", "2"], "ok"),
    (["stock", "news", "A", "--limit", "2"], "ok"),
    (["stock", "insiders", "A", "--limit", "2"], "ok"),
    (["stock", "ownership", "A"], "ok"),
    (["stock", "flows", "SPY", "--limit", "2"], "ok"),
    (["stock", "earnings", "A", "--limit", "2"], "ok"),
    (["stock", "earnings", "A", "--dataset", "revisions", "--fiscal-period", "2025FY", "--limit", "2"], "ok"),
    (["stock", "forecast", "A", "--limit", "1"], "ok"),
    (["stock", "dividends", "A", "--limit", "1"], "ok"),
    (["stock", "revenue", "A", "--by", "regions"], "ok"),
    (["stock", "short-interest", "A", "--limit", "1"], "ok"),
    (["stock", "options", "A", "--type", "call", "--limit", "1"], "ok"),
    (["stock", "filings", "A", "--limit", "2"], "ok"),
    (["stock", "statement", "A", "--kind", "income", "--fields", "currency,periods"], "ok"),
    (["stock", "prices", "A", "--bars", "3"], "ok"),
    (["stock", "prices", "ES", "--instrument", "futures", "--bars", "2"], "ok"),
    (["groups", "options"], "ok"),
    (["groups", "table", "--group", "industry/technology", "--view", "valuation", "--limit", "1"], "ok"),
    (["groups", "performance", "--group", "country", "--limit", "1"], "ok"),
    (["market", "quotes", "forex", "--limit", "1"], "ok"),
    (["market", "performance", "crypto"], "ok"),
    (["market", "map", "--type", "geo", "--fields", "classification_source,period"], "ok"),
    (["market", "bubbles", "--limit", "1"], "ok"),
    (["calendar", "earnings", "--limit", "1"], "ok"),
    (["calendar", "dividends", "--page", "2", "--limit", "1"], "ok"),
    (["calendar", "economic", "--limit", "1"], "ok"),
    (["calendar", "season", "--limit", "1"], "ok"),
    (["news", "headlines", "--limit", "1"], "ok"),
    (["news", "headlines", "--kind", "stocks", "--limit", "1"], "ok"),
    (["news", "pulse", "--limit", "1"], "ok"),
    (["insiders", "trades", "--transaction", "sale", "--limit", "1"], "ok"),
    (["open", "https://finviz.com/quote.ashx?t=AAPL&p=d", "--fields", "metrics", "--limit", "1"], "ok"),
]


def run(arguments, tmp_path):
    proc = subprocess.run([sys.executable, str(CLI), "--store", str(tmp_path / "observations.sqlite3"), "--timeout", "30", *arguments], text=True, capture_output=True, timeout=180)
    return proc, json.loads(proc.stdout) if proc.stdout else None


@pytest.mark.live
@pytest.mark.parametrize("arguments, expected", CASES, ids=lambda x: " ".join(x) if isinstance(x, list) else x)
def test_anonymous_source_provides_usable_data(arguments, expected, tmp_path):
    proc, doc = run(arguments, tmp_path)
    assert proc.returncode == 0, proc.stdout[:1500] + proc.stderr
    assert doc["status"] == expected, doc
    result = doc["results"][0]
    assert result["data"] not in (None, [], {})
    if arguments[:2] == ["stock", "snapshot"]:
        eps = [m for m in result["data"]["metrics"] if m["label"] == "EPS next Y"]
        assert len(eps) == 2 and len({m["definition"] for m in eps}) == 2
    if arguments[:2] == ["screen", "run"] and "--filters" in arguments:
        assert result["conditions"]["filters"]["status"] == "confirmed"


@pytest.mark.live
def test_saved_observation_is_rereadable_and_unknown_ticker_is_reported(tmp_path):
    proc, doc = run(["stock", "snapshot", "A", "--limit", "1"], tmp_path)
    saved = doc["results"][0]["id"]
    proc, again = run(["read", saved, "--pointer", "/data/metrics", "--limit", "1"], tmp_path)
    assert proc.returncode == 0 and again["results"][0]["data"][0]["label"]
    proc, missing = run(["stock", "snapshot", "ZZZZQ"], tmp_path)
    assert proc.returncode == 6 and missing["results"][0]["error"]["code"] == "http_error"
