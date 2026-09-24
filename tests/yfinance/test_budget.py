"""Recovery is tested by following it.

The test this replaces asserted that the sentence began with "Narrow" and did not contain "cannot". Both held while the
sentence recommended --fields to a payload --fields could not reach, so the check passed for a year on advice that
never worked. Here every recovery is parsed out of the error and executed, and the result has to answer the same
question the failed call asked.
"""
import json
import re
import shlex

import pytest

from conftest import inflate, shape

CHART = {"chart": {"error": None, "result": [{"meta": {"currency": "USD", "symbol": "AAPL", "exchangeName": "NMS", "instrumentType": "EQUITY", "firstTradeDate": 345479400, "regularMarketTime": 1704387600, "gmtoffset": -18000, "timezone": "EST", "exchangeTimezoneName": "America/New_York", "regularMarketPrice": 110, "chartPreviousClose": 100, "priceHint": 2, "dataGranularity": "1d", "validRanges": ["1d", "5d", "1mo", "max"]},
    "timestamp": [1704205800 + 86400 * i for i in range(300)],
    "indicators": {"quote": [{"open": [100.0 + i for i in range(300)], "high": [105.0 + i for i in range(300)], "low": [95.0 + i for i in range(300)], "close": [100.0 + i for i in range(300)], "volume": [1000 + i for i in range(300)]}], "adjclose": [{"adjclose": [50.0 + i for i in range(300)]}]},
    "events": {}}]}}


def chart_routes(symbol="AAPL"):
    return [{"path": f"/v8/finance/chart/{symbol}", "json": CHART}]


def news_routes(count=20):
    """Real nesting from the recorded shape, synthetic volume on top of it."""
    items = [{"id": f"id-{n}", "content": inflate(shape("news_item"), n, "w" * 120)["content"]} for n in range(count)]
    return [{"path": "/xhr/ncp", "json": {"data": {"tickerStream": {"stream": [{"content": i["content"], "id": i["id"]} for i in items]}}}}]


def fallback_routes(symbol):
    """A failed chart makes yfinance ask the quote endpoints whether the symbol exists at all; the fixture answers so
    the test observes the CLI's own handling rather than an unmatched request."""
    return [{"path": f"/quoteSummary/{symbol}", "json": {"quoteSummary": {"result": [], "error": None}}},
            {"path": "/v7/finance/quote", "json": {"quoteResponse": {"result": [], "error": None}}},
            {"path": f"/timeseries/{symbol}", "json": {"timeseries": {"result": [], "error": None}}}]


def parse(fix, kind):
    """Pull an executable command out of the recovery sentence, the way a reader following it would."""
    if kind == "read":
        found = re.search(r"\bread ([0-9a-f]{16})((?: --\S+(?: [^\s,.]+)?)*)", fix)
        return ["read", found[1], *shlex.split(found[2])] if found else None
    found = re.search(r"--max-chars (\d+)", fix)
    return ["--max-chars", found[1]] if found else None


# ---- E1 revised: the advice is executed ---------------------------------------------------------------------------


def test_following_the_read_recovery_returns_the_same_observation(cli, tmp_path):
    store = tmp_path / "shared"
    proc, doc = cli("prices", "history", "AAPL", "MSFT", "--period", "1y", "--max-chars", "1200", routes=chart_routes("AAPL") + chart_routes("MSFT"), store=store)
    assert proc.returncode == 9, proc.stdout[:400]
    fix = doc["results"][0]["error"]["fix"]
    ids = {r["target"]: r["id"] for r in doc["results"] if r.get("id")}
    assert set(ids) == {"AAPL", "MSFT"}, "a multi-target recovery that names one target turns a comparison into a single-symbol question"
    for target, ident in ids.items():
        assert ident in fix and target in fix
        proc, back = cli("read", ident, "--limit", "2", routes=[], store=store)
        assert proc.returncode in (0, 8), proc.stdout[:400]
        r = back["results"][0]
        assert r["target"] == target and r["data"]["data"], fix


def test_the_budget_the_fix_names_is_the_budget_that_works(cli, tmp_path):
    args = ("prices", "history", "AAPL", "--period", "1y", "--fields", "Close,Volume")
    proc, doc = cli(*args, "--max-chars", "1000", routes=chart_routes(), store=tmp_path / "s")
    assert proc.returncode == 9
    raised = parse(doc["results"][0]["error"]["fix"], "max-chars")
    proc, doc = cli(*args, *raised, routes=chart_routes(), store=tmp_path / "s")
    assert proc.returncode in (0, 8), proc.stdout[:400]
    assert len(proc.stdout.strip()) <= int(raised[1])


def test_an_oversized_nested_leaf_recovers_whichever_form_the_recovery_takes(cli, tmp_path):
    """A1. `company news` nests every article under content, so the old advice to narrow --fields could never be
    followed. Now the call either fits after the budget narrows it, or refuses with a recovery that runs; the point is
    that no path ends in advice that cannot be carried out."""
    store = tmp_path / "s"
    proc, doc = cli("company", "news", "AAPL", "--limit", "20", "--fields", "content.title,content.thumbnail", "--max-chars", "2500", routes=news_routes(), store=store)
    assert proc.returncode in (8, 9), proc.stdout[:300]
    r = doc["results"][0]
    if proc.returncode == 8:
        assert r["coverage"]["truncated_by"] == "budget" and r["id"] and r["data"]
        proc, back = cli("read", r["id"], "--fields", "content.title", "--limit", "5", routes=[], store=store)
        assert proc.returncode in (0, 8) and back["results"][0]["data"]
        return
    fix = r["error"]["fix"]
    assert "--fields" not in fix or "content." in fix, fix
    command = parse(fix, "read")
    assert command, fix
    proc, back = cli(*command, routes=[], store=store)
    assert proc.returncode in (0, 8), fix + "\n" + proc.stdout[:400]
    assert back["results"][0]["data"], fix


def test_a_dotted_projection_actually_narrows_this_leaf(cli, tmp_path):
    wide, _ = cli("company", "news", "AAPL", "--limit", "10", "--fields", "content.title,content.thumbnail", "--max-chars", "60000", routes=news_routes(), store=tmp_path / "s", raw=True), None
    narrow = cli("company", "news", "AAPL", "--limit", "10", "--fields", "content.title", "--max-chars", "60000", routes=news_routes(), store=tmp_path / "s", raw=True)
    assert len(narrow.stdout) < len(wide.stdout) / 2, "a narrowing the recovery names has to reduce the output"


# ---- R1: a window the budget imposed is not the window the leaf promised ------------------------------------------


def test_a_requested_range_cut_by_the_budget_is_partial_not_ok(cli, tmp_path):
    """Reported as ok, a budget-narrowed window is indistinguishable from this leaf's own default window, and a reader
    describes one screen as the whole five years."""
    proc, doc = cli("prices", "history", "AAPL", "--period", "1y", "--fields", "Close", "--max-chars", "3000", routes=chart_routes(), store=tmp_path / "s")
    assert proc.returncode == 8, proc.stdout[:300]
    r = doc["results"][0]
    assert doc["status"] == "partial"
    assert r["coverage"]["truncated_by"] == "budget" and r["coverage"]["shown"] < r["coverage"]["received"]
    assert r["coverage"]["kept"] == "newest"
    assert any("budget narrowed" in w for w in r["warnings"])
    assert r["id"], "the rest has to remain reachable"


def test_a_leaf_default_window_stays_ok(cli, tmp_path):
    proc, doc = cli("company", "news", "AAPL", routes=news_routes(30), store=tmp_path / "s")
    assert proc.returncode == 0, proc.stdout[:300]
    assert doc["results"][0]["coverage"]["truncated_by"] == "leaf_default"


def test_the_continuation_after_a_budget_cut_does_not_skip_the_rows_it_dropped(cli, tmp_path):
    """The continuation was computed before the budget narrowed the window, so following it stepped over every row
    between what was shown and what was originally planned."""
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--period", "1y", routes=chart_routes(), store=store)
    ident = doc["results"][0]["id"]
    seen, start, guard = [], 0, 0
    while guard < 20:
        guard += 1
        proc, page = cli("read", ident, "--fields", "Close", "--start", str(start), "--limit", "250", routes=[], store=store)
        r = page["results"][0]
        seen += r["data"]["index"]
        following = r.get("continuation")
        if not following:
            break
        start = following["start"]
    assert len(seen) == len(set(seen)) == r["coverage"]["received"], "windows overlapped or skipped rows"


# ---- R7-7: the error document is itself inside the budget ---------------------------------------------------------


@pytest.mark.parametrize("budget", [1000, 1500, 3000])
def test_the_refusal_fits_the_budget_it_reports(cli, tmp_path, budget):
    symbols = [f"S{i:02d}" for i in range(10)]
    routes = [r for s in symbols for r in chart_routes(s)]
    proc, doc = cli("prices", "history", *symbols, "--period", "1y", "--max-chars", str(budget), routes=routes, store=tmp_path / "s")
    assert proc.returncode == 9
    assert len(proc.stdout.strip()) <= budget, "the document reporting the boundary broke it"
    assert doc["results"][0]["error"]["fix"], "the recovery sentence is the last thing to be dropped"


def test_ten_targets_are_all_named_and_still_fit(cli, tmp_path):
    symbols = [f"S{i:02d}" for i in range(10)]
    routes = [r for s in symbols for r in chart_routes(s)]
    proc, doc = cli("prices", "history", *symbols, "--period", "1y", "--max-chars", "4000", routes=routes, store=tmp_path / "s")
    assert proc.returncode == 9
    fix = doc["results"][0]["error"]["fix"]
    assert len(re.findall(r"[0-9a-f]{16}", fix)) == 10, fix
    assert len(proc.stdout.strip()) <= 4000


# ---- A5: the source's own prescription becomes the fix -------------------------------------------------------------


def test_an_upstream_constraint_names_the_argument_to_change(cli, tmp_path):
    """Every upstream failure used to receive one sentence about verifying the symbol, including the ones where the
    source had already said exactly how many days it allows."""
    message = "$AAPL: 1m data not available for startTime=1 and endTime=2. Only 8 days worth of 1m granularity data are allowed to be fetched per request."
    routes = [{"path": "/v8/finance/chart/AAPL", "json": {"chart": {"result": None, "error": {"code": "Bad Request", "description": message}}}}] + fallback_routes("AAPL")
    proc, doc = cli("prices", "history", "AAPL", "--period", "1y", "--interval", "1m", routes=routes, store=tmp_path / "s")
    assert proc.returncode == 6, proc.stdout[:300]
    fix = doc["results"][0]["error"]["fix"]
    assert "--period 8d" in fix, fix
    assert "verify the symbol" not in fix and "Retry later" not in fix


def test_an_upstream_failure_with_no_stated_constraint_still_says_where_to_look(cli, tmp_path):
    routes = [{"path": "/v8/finance/chart/ZZZZ", "json": {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found, symbol may be delisted"}}}}] + fallback_routes("ZZZZ")
    proc, doc = cli("prices", "history", "ZZZZ", "--period", "1mo", routes=routes, store=tmp_path / "s")
    assert proc.returncode == 6
    assert "search" in doc["results"][0]["error"]["fix"]


def test_schema_oversize_names_scoping_rather_than_a_selection_that_does_not_apply(cli):
    proc, doc = cli("schema", "--max-chars", "1000")
    assert proc.returncode == 9
    fix = doc["results"][0]["error"]["fix"]
    assert "schema GROUP" in fix and "--fields" not in fix and "--limit" not in fix


# ---- defects found by an independent review of this rewrite --------------------------------------------------------


def test_a_multi_target_recovery_keeps_the_projection_as_well_as_the_targets(cli, tmp_path):
    """Preserving every target but dropping --fields still changes the question: the recovery returns the default
    projection and reports ok, so the reader gets different values and no sign that anything was substituted."""
    store = tmp_path / "s"
    proc, doc = cli("company", "news", "AAPL", "MSFT", "--limit", "20", "--fields", "content.thumbnail.originalUrl",
                    "--max-chars", "1500", routes=news_routes() + [{"path": "/xhr/ncp", "json": {"data": {"tickerStream": {"stream": []}}}}], store=store)
    if proc.returncode != 9:
        pytest.skip("this payload fitted after the budget narrowed it")
    fix = doc["results"][0]["error"]["fix"]
    assert "--fields content.thumbnail.originalUrl" in fix, fix


def test_an_option_chain_reads_back_under_the_same_selection_contract(cli, tmp_path):
    """The chain is two tables under one result. Read as a mapping, a --limit found no rows to cut and --fields was
    checked against the side names, so the same observation answered differently depending on which command read it."""
    store = tmp_path / "s"
    expirations = {"optionChain": {"result": [{"expirationDates": [1735689600], "quote": {"symbol": "AAPL", "regularMarketPrice": 100},
        "options": [{"expirationDate": 1735689600,
                     "calls": [{"contractSymbol": f"C{i}", "strike": 100.0 + i, "lastPrice": 1.0 + i, "impliedVolatility": 0.2, "inTheMoney": False, "currency": "USD"} for i in range(6)],
                     "puts": [{"contractSymbol": f"P{i}", "strike": 100.0 + i, "lastPrice": 2.0 + i, "impliedVolatility": 0.3, "inTheMoney": False, "currency": "USD"} for i in range(6)]}]}], "error": None}}
    routes = [{"path": "/v7/finance/options/AAPL", "json": expirations}]
    proc, doc = cli("options", "chain", "AAPL", "--limit", "2", "--fields", "strike", routes=routes, store=store)
    assert proc.returncode == 0, proc.stdout[:300]
    ident = doc["results"][0]["id"]
    assert len(doc["results"][0]["data"]["calls"]["data"]) == 2

    proc, back = cli("read", ident, "--limit", "2", "--fields", "strike", routes=[], store=store)
    assert proc.returncode in (0, 8), proc.stdout[:400]
    r = back["results"][0]
    assert len(r["data"]["calls"]["data"]) == 2, "read returned every row for a limit the first call honoured"
    assert r["data"]["calls"]["columns"] == ["strike"], "a field the first call accepted was refused on read"


def test_a_leaf_that_cannot_be_narrowed_does_not_claim_it_can(cli):
    """fund description returns one string: neither --fields nor --limit reduces it, so declaring either would put an
    argument in the recovery that returns the same size again."""
    proc, doc = cli("schema", "fund", "description")
    assert "narrowing" not in doc["results"][0]["data"]
    proc, doc = cli("schema", "market", "summary")
    assert "--limit" not in doc["results"][0]["data"]["narrowing"]


def earnings_page_routes(count=25):
    head = "<table><thead><tr><th>Symbol</th><th>Company</th><th>Earnings Date</th><th>EPS Estimate</th><th>Reported EPS</th><th>Surprise (%)</th></tr></thead><tbody>"
    rows = "".join(f"<tr><td>AAPL</td><td>Apple</td><td>January {25 - i:02d}, 2024 at 4 PM EST</td><td>1</td><td>1</td><td>0</td></tr>" for i in range(count))
    return [{"path": "/calendar/earnings", "text": head + rows + "</tbody></table>"}]


def test_a_single_symbol_earnings_recovery_never_names_a_date_range(cli, tmp_path):
    """--start/--end is a real narrowing for market-wide calendar earnings and rejected outright for the
    single-symbol form. An explicit store lengthens the continuation enough that even one row refuses, so the
    recovery sentence lists this leaf's narrowings."""
    store = tmp_path / "an-explicitly-chosen-store"
    proc, doc = cli("calendar", "earnings", "AAPL", "--max-chars", "1000", "--store", str(store), routes=earnings_page_routes(), store=tmp_path / "s")
    assert proc.returncode == 9, proc.stdout[:300]
    fix = doc["results"][0]["error"]["fix"]
    assert "Narrow with" in fix and "--start" not in fix and "--end" not in fix, fix


def test_a_recovery_never_names_an_argument_this_mode_forbids(cli, tmp_path):
    """--type is a real narrowing for instrument search and rejected outright for the other datasets; naming it there
    sends the reader into an invalid-argument error."""
    news = [{"uuid": f"u{i}", "title": "headline " * 30, "publisher": "p", "link": "l", "providerPublishTime": 1704067200, "type": "STORY"} for i in range(10)]
    routes = [{"path": "/v1/finance/search", "json": {"quotes": [], "news": news, "lists": [], "researchReports": [], "nav": []}}]
    proc, doc = cli("search", "apple", "--dataset", "news", "--max-chars", "1000", routes=routes, store=tmp_path / "s")
    assert proc.returncode == 9, proc.stdout[:300]
    fix = doc["results"][0]["error"]["fix"]
    assert "Narrow with" in fix and "--type" not in fix, fix


def test_a_single_row_over_the_budget_is_told_so_rather_than_sent_round_again(cli, tmp_path):
    """Advising a smaller --limit when one row already exceeds the budget repeats the same failure and calls it a
    recovery."""
    store = tmp_path / "s"
    huge = [{"path": "/xhr/ncp", "json": {"data": {"tickerStream": {"stream": [{"id": "x", "content": {"title": "t", "summary": "s" * 30000}}]}}}}]
    proc, doc = cli("company", "news", "AAPL", "--fields", "content.summary", routes=huge, store=store)
    assert proc.returncode == 9, proc.stdout[:300]
    fix = doc["results"][0]["error"]["fix"]
    assert "single entry" in fix and "--max-chars" in fix, fix
    assert "--start 0 --limit 1" not in fix, "the recovery promises a slice that fails identically"


def test_a_generated_recovery_points_at_the_store_the_observation_is_in(cli, tmp_path):
    """An explicitly chosen store has to appear in the command the recovery names, or that command reads the default
    cache, where the id it just printed does not exist."""
    store = tmp_path / "custom-cache"
    proc, doc = cli("prices", "history", "AAPL", "--period", "1y", "--max-chars", "1500", "--store", str(store), routes=chart_routes(), store=tmp_path / "unused")
    assert proc.returncode in (8, 9), proc.stdout[:300]
    text = json.dumps(doc, ensure_ascii=False)
    assert str(store) in text, "a recovery command that omits --store sends the reader to a different cache"
    assert (store / (doc["results"][0]["id"] + ".json")).exists()
