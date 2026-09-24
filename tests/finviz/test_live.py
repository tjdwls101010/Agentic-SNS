"""Opt-in checks against anonymous Finviz; run with `-m live`. No account, no SEC originals.

Every leaf is first called with positional arguments only, the way a model first reaches for it. Each source
control is then checked for its effect on the returned records, not only for its echo: an echo alone passes a
selector the source ignored. Continuations are followed verbatim and compared with the unbudgeted answer.
"""

import json
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import sys

import pytest

CLI = Path(__file__).resolve().parents[2] / ".claude/skills/finviz/scripts/finviz.py"

DEFAULTS = [
    ["search", "Agilent"],
    ["screen", "filters"], ["screen", "signals"], ["screen", "columns"], ["screen", "run"],
    ["stock", "overview", "A"], ["stock", "earnings", "A"], ["stock", "forecast", "A"], ["stock", "dividends", "A"], ["stock", "revenue", "A"],
    ["stock", "short-interest", "A"], ["stock", "options", "A"], ["stock", "filings", "A"], ["stock", "statement", "A"], ["stock", "prices", "A"], ["stock", "holdings", "SPY"],
    ["groups", "table"], ["groups", "performance"],
    ["market", "quotes", "futures"], ["market", "performance", "futures"], ["market", "map"], ["market", "bubbles"],
    ["calendar", "earnings"], ["calendar", "dividends"], ["calendar", "economic"], ["calendar", "season"], ["calendar", "event", "FDTR"],
    ["news", "headlines"], ["news", "pulse"],
    ["insiders", "trades"],
    ["stock", "overview", "AAPL", "MSFT", "NVDA"],
]


def run(arguments, tmp_path, timeout=180):
    proc = subprocess.run([sys.executable, str(CLI), "--store", str(tmp_path / "observations.sqlite3"), *arguments], text=True, capture_output=True, timeout=timeout)
    return proc, json.loads(proc.stdout) if proc.stdout else None


def one(arguments, tmp_path):
    proc, doc = run(arguments, tmp_path)
    assert proc.stderr == "" and doc is not None, proc.stderr
    assert doc["status"] in ("ok", "partial", "empty"), json.dumps(doc)[:1500]
    return doc["results"][0]


def requests(tmp_path):
    return sqlite3.connect(tmp_path / "observations.sqlite3").execute("SELECT COUNT(*) FROM observations").fetchone()[0]


def number(text):
    text = str(text).replace(",", "").replace("$", "").strip()
    scale = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}.get(text[-1:], 1)
    return float(text[:-1] if scale != 1 else text) * scale


@pytest.mark.live
@pytest.mark.parametrize("arguments", DEFAULTS, ids=lambda x: " ".join(x))
def test_every_leaf_answers_at_its_own_defaults_inside_the_default_budget(arguments, tmp_path):
    proc, doc = run(arguments, tmp_path)
    assert proc.returncode in (0, 7, 8), proc.stdout[:1500] + proc.stderr
    assert doc["status"] in ("ok", "partial", "empty") and proc.stderr == ""
    assert len(proc.stdout.strip()) <= 20000
    for result in doc["results"]:
        assert result["status"] != "error", result
        coverage = result.get("coverage") or {}
        for part in (coverage.values() if all(isinstance(v, dict) for v in coverage.values()) and coverage else [coverage]):
            if "received" in part:
                assert part["shown"] <= part["matched"] <= part["received"] or part.get("cut") or part["matched"] <= part["received"]


def gather(first, tmp_path, name):
    rows, doc = list(first["results"][0]["data"].get(name) or []), first
    while doc.get("continuation"):
        commands = doc["continuation"] if isinstance(doc["continuation"], list) else [doc["continuation"]]
        proc, doc = run(shlex.split(commands[0]), tmp_path)
        assert proc.returncode in (0, 8), proc.stdout[:800]
        rows += doc["results"][0]["data"].get(name) or []
    return rows


@pytest.mark.live
@pytest.mark.parametrize("arguments,name,selectors", [
    (["stock", "options", "AAPL"], "contracts", ["--strikes", "0", "--type", "put", "--fields", "strike,iv,openInterest"]),
    (["stock", "earnings", "AAPL", "--sections", "revisions"], "revisions", []),
    (["news", "headlines"], "headlines", ["--per-section", "0"]),
    (["insiders", "trades"], "trades", ["--limit", "60"]),
], ids=["options", "revisions", "headlines", "insiders"])
def test_following_every_continuation_equals_the_unbudgeted_answer(arguments, name, selectors, tmp_path):
    proc, first = run(arguments + selectors + ["--max-chars", "4000"], tmp_path)
    assert first["status"] == "partial" and first.get("continuation"), json.dumps(first)[:800]
    read = ["read", first["results"][0]["id"]] + (["--section", name] if "--sections" in arguments else [])
    whole = one(read + selectors + ["--max-chars", "10000000"], tmp_path)
    assert gather(first, tmp_path, name) == whole["data"][name]


@pytest.mark.live
def test_five_tickers_compare_in_one_screener_request(tmp_path):
    result = one(["screen", "run", "--tickers", "AAPL,MSFT,NVDA,GOOGL,AMZN", "--view", "valuation"], tmp_path)
    assert sorted(r["ticker"] for r in result["data"]["rows"]) == ["AAPL", "AMZN", "GOOGL", "MSFT", "NVDA"]
    assert result["conditions"]["tickers"]["status"] == "confirmed" and requests(tmp_path) == 1
    assert "P/E" in result["data"]["rows"][0]


@pytest.mark.live
def test_screener_controls_change_the_rows(tmp_path):
    mega = one(["screen", "run", "--filters", "cap_mega", "--fields", "ticker,Market Cap"], tmp_path)
    assert mega["conditions"]["filters"]["status"] == "confirmed" and all(number(r["Market Cap"]) >= 2e11 for r in mega["data"]["rows"])
    ordered = one(["screen", "run", "--sort=-marketcap", "--fields", "ticker,Market Cap"], tmp_path)
    caps = [number(r["Market Cap"]) for r in ordered["data"]["rows"]]
    assert ordered["conditions"]["sort"]["status"] == "confirmed" and caps == sorted(caps, reverse=True)
    gainers = one(["screen", "run", "--signal", "ta_topgainers", "--fields", "ticker,Change %"], tmp_path)
    assert gainers["conditions"]["signal"]["status"] == "confirmed" and all(number(r["Change %"].rstrip("%")) > 0 for r in gainers["data"]["rows"])
    later = one(["screen", "run", "--row", "21"], tmp_path)
    assert later["conditions"]["row"]["status"] == "confirmed" and later["data"]["rows"][0]["No."] == "21"
    custom = one(["screen", "run", "--columns", "ticker,marketCap,PE"], tmp_path)
    assert custom["conditions"]["columns"]["status"] == "confirmed" and set(custom["data"]["rows"][0]) >= {"Ticker", "Market Cap", "P/E"}
    bogus = one(["screen", "run", "--filters", "cap_bogus", "--limit", "1"], tmp_path)
    assert bogus["conditions"]["filters"]["status"] == "not_applied"


@pytest.mark.live
def test_option_controls_select_expiry_strike_and_every_expiry(tmp_path):
    chain = one(["stock", "options", "AAPL", "--strikes", "3"], tmp_path)
    expiry = chain["data"]["expiries"][1]
    dated = one(["stock", "options", "AAPL", "--expiry", expiry, "--strikes", "0", "--fields", "exDate"], tmp_path)
    assert dated["conditions"]["expiry"]["status"] == "confirmed" and {c["exDate"] for c in dated["data"]["contracts"]} == {int(expiry[2:].replace("-", ""))}
    strike = sorted({c["strike"] for c in chain["data"]["contracts"]})[0]
    across = one(["stock", "options", "AAPL", "--strike", str(strike), "--strikes", "0", "--limit", "500"], tmp_path)
    assert across["conditions"]["strike"]["status"] == "confirmed" and len({c["exDate"] for c in across["data"]["contracts"]}) > 1
    surface = one(["stock", "options", "AAPL", "--all-expiries", "--strikes", "1", "--limit", "500", "--fields", "exDate"], tmp_path)
    assert surface["conditions"]["all_expiries"]["status"] == "confirmed" and len({c["exDate"] for c in surface["data"]["contracts"]}) > 5


@pytest.mark.live
def test_filing_controls_order_filter_and_page_the_list(tmp_path):
    oldest = one(["stock", "filings", "AAPL", "--sort", "filingDate"], tmp_path)
    dates = [f["filingDate"] for f in oldest["data"]["filings"]]
    assert oldest["conditions"]["sort"]["status"] == "confirmed" and dates == sorted(dates) and dates[0] < "2016"
    insider = one(["stock", "filings", "AAPL", "--category", "insider-equity"], tmp_path)
    assert insider["conditions"]["category"]["status"] == "confirmed" and {f["form"] for f in insider["data"]["filings"]} <= {"3", "4", "5", "3/A", "4/A", "5/A"}
    second = one(["stock", "filings", "AAPL", "--page", "2"], tmp_path)
    assert second["conditions"]["page"]["status"] == "confirmed" and second["data"]["filings"][0] != one(["stock", "filings", "AAPL"], tmp_path)["data"]["filings"][0]


@pytest.mark.live
def test_statement_kind_and_period_and_etf_holdings(tmp_path):
    balance = one(["stock", "statement", "AAPL", "--kind", "balance", "--period", "quarterly"], tmp_path)
    assert all("Q" in p for p in balance["data"]["periods"]) and any("Assets" in i["item"] for i in balance["data"]["items"])
    held = one(["stock", "holdings", "SPY"], tmp_path)
    assert len(held["data"]["holdings"]) == 10 and held["data"]["total_holdings"] > 400 and requests(tmp_path) == 2


@pytest.mark.live
def test_group_controls_change_the_universe_view_and_order(tmp_path):
    tech = one(["groups", "table", "--group", "industry/technology", "--sort=-marketcap", "--fields", "Name,Market Cap"], tmp_path)
    caps = [number(r["Market Cap"]) for r in tech["data"]["groups"]]
    assert tech["conditions"]["group"]["status"] == "confirmed" and tech["conditions"]["sort"]["status"] == "confirmed" and caps == sorted(caps, reverse=True)
    perf = one(["groups", "table", "--view", "performance"], tmp_path)
    assert any(k.startswith("Perf") for k in perf["data"]["groups"][0])


@pytest.mark.live
def test_insider_controls_filter_and_order_the_trades(tmp_path):
    buys = one(["insiders", "trades", "--transaction", "buy", "--fields", "Transaction"], tmp_path)
    assert buys["conditions"]["transaction"]["status"] == "confirmed" and {r["Transaction"] for r in buys["data"]["trades"]} == {"Buy"}
    owners = one(["insiders", "trades", "--preset", "top-owner", "--fields", "Relationship,Value ($)"], tmp_path)
    assert owners["conditions"]["preset"]["status"] == "confirmed" and all("10%" in r["Relationship"] for r in owners["data"]["trades"])
    owner = re.search(r"oc=(\d+)", buys["data"]["trades"][0]["owner_url"] if "owner_url" in buys["data"]["trades"][0] else one(["insiders", "trades", "--limit", "1"], tmp_path)["data"]["trades"][0]["owner_url"])[1]
    one_owner = one(["insiders", "trades", "--owner", owner, "--fields", "owner_url"], tmp_path)
    assert {re.search(r"oc=(\d+)", r["owner_url"])[1] for r in one_owner["data"]["trades"]} == {owner}
    large = one(["insiders", "trades", "--value", "1000000", "--sort=-transactionvalue", "--fields", "Value ($)"], tmp_path)
    values = [number(r["Value ($)"]) for r in large["data"]["trades"]]
    assert all(v >= 1e6 for v in values) and values == sorted(values, reverse=True)


@pytest.mark.live
def test_calendar_controls_move_the_date_order_page_series_and_day(tmp_path):
    first = one(["calendar", "earnings"], tmp_path)
    moved = one(["calendar", "earnings", "--date", first["data"]["date_from"], "--sort=-ticker", "--fields", "ticker"], tmp_path)
    tickers = [r["ticker"] for r in moved["data"]["items"]]
    assert moved["conditions"]["date"]["status"] == "confirmed" and tickers == sorted(tickers, reverse=True)
    if first["coverage"].get("source_total", 0) > len(first["data"]["items"]):
        second = one(["calendar", "earnings", "--date", first["data"]["date_from"], "--page", "2"], tmp_path)
        assert second["conditions"]["page"]["status"] == "confirmed" and second["data"]["items"][0] != first["data"]["items"][0]
    dividends = one(["calendar", "dividends", "--sort", "ticker", "--fields", "ticker"], tmp_path)
    assert [r["ticker"] for r in dividends["data"]["items"]] == sorted(r["ticker"] for r in dividends["data"]["items"])
    series = one(["calendar", "event", "FDTR"], tmp_path)
    assert series["conditions"]["ticker"]["status"] == "confirmed" and len(series["data"]["history"]) > 10 and series["data"]["history"][0]["refDate"] > "2025"
    season = one(["calendar", "season"], tmp_path)
    busy = next((day for day, count in (season["data"]["totals_per_day"] or {}).items() if count), None)
    if busy:
        day = one(["calendar", "season", "--day", busy], tmp_path)
        assert day["conditions"]["day"]["status"] == "confirmed"


@pytest.mark.live
def test_news_and_pulse_controls(tmp_path):
    by_source = one(["news", "headlines", "--kind", "by-source"], tmp_path)
    assert len({h["section"] for h in by_source["data"]["headlines"]}) >= 3
    listed = one(["news", "pulse"], tmp_path)
    ticker = next(t for e in listed["data"]["entries"] for t in e["tickers"] if re.fullmatch(r"[A-Z.]+", t))
    newest = one(["news", "pulse", "--ticker", ticker], tmp_path)
    assert newest["status"] == "empty" or newest["conditions"]["ticker"]["status"] == "confirmed"


@pytest.mark.live
def test_market_controls_change_universe_metric_currency_and_bubble_filters(tmp_path):
    dow = one(["market", "map", "--type", "sec_dji", "--limit", "100"], tmp_path)
    assert len(dow["data"]["tickers"]) == 30
    pe = one(["market", "map", "--type", "sec_dji", "--period", "pe", "--limit", "100"], tmp_path)
    assert pe["conditions"]["period"]["status"] == "confirmed" and "pe" in pe["data"]["tickers"][0]
    btc = one(["market", "quotes", "crypto", "--currency", "BTC", "--fields", "ticker", "--limit", "100"], tmp_path)
    assert all(r["ticker"].endswith("BTC") or r["ticker"] == "BTCUSD" for r in btc["data"]["quotes"])  # bitcoin itself stays quoted in USD
    daily = one(["market", "quotes", "futures", "--sparkline", "--fields", "ticker,sparklineDateChanges", "--limit", "1"], tmp_path)
    weekly = one(["market", "quotes", "futures", "--timeframe", "w", "--sparkline", "--fields", "ticker,sparklineDateChanges", "--limit", "1"], tmp_path)
    assert daily["data"]["quotes"][0]["sparklineDateChanges"] != weekly["data"]["quotes"][0]["sparklineDateChanges"]
    perf = one(["market", "performance", "crypto", "--currency", "BTC"], tmp_path)
    assert perf["conditions"]["currency"]["status"] == "confirmed"
    tech = one(["market", "bubbles", "--index", "sp500", "--sector", "technology", "--fields", "ticker,color", "--limit", "600"], tmp_path)
    assert tech["conditions"]["sector"]["status"] == "confirmed"
    mega = one(["market", "bubbles", "--index", "sp500", "--cap", "mega", "--fields", "size", "--limit", "600"], tmp_path)
    assert all(r["size"] >= 2e11 for r in mega["data"]["stocks"])
    liquid = one(["market", "bubbles", "--index", "sp500", "--avg-volume", "o1000", "--y", "averageVolume", "--fields", "y", "--limit", "600"], tmp_path)
    assert all(r["y"] >= 1e6 for r in liquid["data"]["stocks"])
    named = one(["market", "bubbles", "--tickers", "AAPL,MSFT"], tmp_path)
    assert named["conditions"]["tickers"]["status"] == "confirmed" and len(named["data"]["stocks"]) == 2
    rest = one(["market", "bubbles", "--exclude", "AAPL,MSFT", "--limit", "100"], tmp_path)
    assert rest["conditions"]["exclude"]["status"] == "confirmed" and len(rest["data"]["stocks"]) == 28
    axis = one(["market", "bubbles", "--x", "PE", "--limit", "1", "--fields", "x"], tmp_path)
    assert isinstance(axis["data"]["stocks"][0]["x"], (int, float))


@pytest.mark.live
def test_one_overview_observation_answers_several_sections_and_read_costs_nothing(tmp_path):
    first = one(["stock", "overview", "AAPL", "--sections", "snapshot,news,insiders"], tmp_path)
    again = one(["read", first["id"], "--section", "ratings"], tmp_path)
    assert again["observed_at"] == first["observed_at"] and requests(tmp_path) == 1
    news = first["data"]["news"]
    assert news and all(h["date"] for h in news)


@pytest.mark.live
def test_revisions_default_to_the_newest_estimate_per_period_and_type(tmp_path):
    result = one(["stock", "earnings", "AAPL", "--sections", "revisions"], tmp_path)
    rows = result["data"]["revisions"]
    assert len({(r["fiscalPeriod"], r["estimateType"]) for r in rows}) == len(rows) and all(r["history_count"] >= 1 for r in rows)
    assert max(r["estimateDate"] for r in rows) > "2026"


@pytest.mark.live
def test_a_finviz_hosted_article_is_readable_when_one_is_listed(tmp_path):
    listed = one(["news", "headlines", "--per-section", "0", "--limit", "300", "--fields", "url"], tmp_path)
    hosted = next((h["url"] for h in listed["data"]["headlines"] if re.search(r"finviz\.com/news/\d+/", h["url"] or "")), None)
    if hosted is None:
        pytest.skip("no finviz-hosted article in the current headlines")
    assert one(["news", "article", hosted], tmp_path)["data"]["paragraphs"]


@pytest.mark.live
def test_an_unknown_ticker_is_reported_and_its_response_is_saved(tmp_path):
    proc, missing = run(["stock", "overview", "ZZZZQ"], tmp_path)
    assert proc.returncode == 6 and missing["results"][0]["error"]["code"] == "http_error" and missing["results"][0]["id"]
