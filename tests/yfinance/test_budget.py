"""Recovery is tested by following it.

The test this replaces asserted that the sentence began with "Narrow" and did not contain "cannot". Both held while the
sentence recommended --fields to a payload --fields could not reach, so the check passed for a year on advice that
never worked. Here every recovery is parsed out of the error and executed, and the result has to answer the same
question the failed call asked.
"""
import re
import shlex

import pytest

from conftest import inflate, shape
from test_selection import closes, series_routes

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
    symbols = [f"S{i:02d}" for i in range(6)]
    routes = [r for s in symbols for r in chart_routes(s)]
    args = ("prices", "history", *symbols, "--period", "1y", "--fields", "Close,Volume")
    proc, doc = cli(*args, "--max-chars", "1000", routes=routes, store=tmp_path / "s")
    assert proc.returncode == 9
    raised = parse(doc["results"][0]["error"]["fix"], "max-chars")
    proc, doc = cli(*args, *raised, routes=routes, store=tmp_path / "s")
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
    argument in the recovery that returns the same size again. market summary's exchanges are rows, so --limit does narrow it."""
    proc, doc = cli("schema", "fund", "description")
    assert "narrowing" not in doc["results"][0]["data"]
    proc, doc = cli("schema", "market", "summary")
    assert "--limit" in doc["results"][0]["data"]["narrowing"]


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


# ---- recoveries that leave the budget behind ------------------------------------------------------------------------


def test_a_budget_cut_series_names_the_file_and_the_coarser_view_and_both_work(cli, tmp_path):
    """A window is not the series. The warning names the two ways out that do not page through the whole thing on
    screen: the saved rows written to a file, and a coarser interval — which is a new request with a different
    meaning, and says so."""
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--period", "1y", "--max-chars", "3000", routes=chart_routes(), store=store)
    assert proc.returncode == 8, proc.stdout[:300]
    warning = next(w for w in doc["results"][0]["warnings"] if "budget narrowed" in w)
    found = re.search(r"\bread ([0-9a-f]{16})((?: --\S+(?: \S+)?)*?) --out FILE", warning)
    assert found, warning
    out = tmp_path / "all.csv"
    proc, back = cli("read", found[1], *shlex.split(found[2]), "--out", str(out), routes=[], store=store)
    assert proc.returncode == 0, proc.stdout[:300]
    assert back["results"][0]["data"]["rows"] == 300
    assert "--interval 1wk" in warning and "new request" in warning, warning
    proc, weekly = cli("prices", "history", "AAPL", "--period", "1y", "--interval", "1wk", routes=chart_routes(), store=store)
    assert proc.returncode in (0, 8), proc.stdout[:300]


def test_a_refusal_names_the_file_when_the_rows_can_go_to_one(cli, tmp_path):
    store = tmp_path / "s"
    huge = [{"path": "/xhr/ncp", "json": {"data": {"tickerStream": {"stream": [{"id": "x", "content": {"title": "t", "summary": "s" * 30000}}]}}}}]
    proc, doc = cli("company", "news", "AAPL", "--fields", "content.summary", routes=huge, store=store)
    assert proc.returncode == 9, proc.stdout[:300]
    fix = doc["results"][0]["error"]["fix"]
    found = re.search(r"\bread ([0-9a-f]{16})((?: --\S+(?: \S+)?)*?) --out FILE", fix)
    assert found, fix
    proc, back = cli("read", found[1], *shlex.split(found[2]), "--out", str(tmp_path / "news.csv"), routes=[], store=store)
    assert proc.returncode == 0, proc.stdout[:300]


def test_a_single_record_refusal_never_offers_a_file(cli, tmp_path):
    profile = {"quoteType": {"quoteType": "ETF"}, "summaryProfile": {"longBusinessSummary": "x" * 30000},
               "topHoldings": {"holdings": [], "sectorWeightings": [], "bondRatings": []}, "fundProfile": {"categoryName": "c", "family": "f", "legalType": "l"}}
    routes = [{"path": "/quoteSummary/SPY", "json": {"quoteSummary": {"result": [profile]}}}]
    proc, doc = cli("fund", "description", "SPY", routes=routes, store=tmp_path / "s")
    assert proc.returncode == 9, proc.stdout[:300]
    assert "--out" not in doc["results"][0]["error"]["fix"]


def test_reading_a_long_saved_series_under_a_small_budget_narrows_rather_than_crashing(cli, tmp_path):
    """read has no --interval, so a recovery built for the original command must not be built from read's arguments."""
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--period", "1y", "--limit", "1", routes=chart_routes(), store=store)
    proc, back = cli("read", doc["results"][0]["id"], "--max-chars", "1500", routes=[], store=store)
    assert proc.returncode == 8, proc.stdout[:400] + proc.stderr[-400:]
    assert back["results"][0]["continuation"]


# ---- B8: a refusal promises only the saves that happened ------------------------------------------------------------


@pytest.mark.parametrize("budget", [1000, 1500, 3000])
def test_a_refusal_counts_only_the_targets_that_were_saved(cli, tmp_path, budget):
    """A target that failed has no saved response; counting it among the saved ones sends the reader after an id that
    does not exist, and reporting it as refused for size hides the failure it actually had."""
    store = tmp_path / "s"
    symbols = ["S00", "S01", "S02", "S03", "ZZZZ", "S04", "S05", "S06", "S07", "S08"]
    missing = [{"path": "/v8/finance/chart/ZZZZ", "json": {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found, symbol may be delisted"}}}}]
    routes = [r for s in symbols if s != "ZZZZ" for r in chart_routes(s)] + missing + fallback_routes("ZZZZ")
    proc, doc = cli("prices", "history", *symbols, "--period", "1y", "--max-chars", str(budget), routes=routes, store=store)
    assert proc.returncode == 9, proc.stdout[:300]
    saved = {p.stem for p in store.glob("*.json")}
    assert len(saved) == 9
    assert set(re.findall(r"\b[0-9a-f]{16}\b", proc.stdout)) <= saved
    for found in re.findall(r"(\d+) further targets were saved", proc.stdout):
        assert int(found) == 8, proc.stdout
    for found in re.findall(r"all (\d+) targets were saved|(\d+) targets were saved and none", proc.stdout):
        assert int(next(n for n in found if n)) == 9, proc.stdout
    for row in doc["results"]:
        if row["target"] == "ZZZZ":
            assert row.get("id") is None and row["error"]["code"] == "upstream", row


@pytest.mark.parametrize("interval,message,own,other", [
    ("1m", "$AAPL: 1m data not available for startTime=1 and endTime=2. Only 8 days worth of 1m granularity data are allowed to be fetched per request.",
     ["--period 8d", "per request"], ["within the last", "inside the last"]),
    ("5m", "$AAPL: 5m data not available for startTime=1 and endTime=2. The requested range must be within the last 60 days.",
     ["--period 60d", "last 60 days"], ["per request"]),
])
def test_each_upstream_range_constraint_is_answered_with_its_own_remedy(cli, tmp_path, interval, message, own, other):
    """A span per request and a reach into the past are different limits: a shorter span does not reach older bars,
    and a recent start does not make a long span legal. Neither is evidence that a coarser interval has no limit."""
    routes = [{"path": "/v8/finance/chart/AAPL", "json": {"chart": {"result": None, "error": {"code": "Bad Request", "description": message}}}}] + fallback_routes("AAPL")
    proc, doc = cli("prices", "history", "AAPL", "--period", "1y", "--interval", interval, routes=routes, store=tmp_path / "s")
    assert proc.returncode == 6, proc.stdout[:300]
    fix = doc["results"][0]["error"]["fix"]
    assert all(phrase in fix for phrase in own), fix
    assert not any(phrase in fix for phrase in other), fix
    assert "no such limit" not in fix, fix


def test_a_refusal_points_at_the_target_that_carries_the_recovery(cli, tmp_path):
    """With the failed target first, "the fix on the first result" named a failure's advice instead of the recovery."""
    def body(symbol):
        return {"serviceConfig": {"snippetCount": 10, "s": [symbol]}}
    huge = {"data": {"tickerStream": {"stream": [{"id": "x", "content": {"title": "t", "summary": "s" * 30000}}]}}}
    routes = [{"path": "/xhr/ncp", "body": body("ZZZ"), "status": 500, "text": "Internal Server Error"},
              {"path": "/xhr/ncp", "body": body("AAA"), "json": huge}, {"path": "/xhr/ncp", "body": body("BBB"), "json": huge}]
    proc, doc = cli("company", "news", "ZZZ", "AAA", "BBB", "--fields", "content.summary", "--max-chars", "3000", routes=routes, store=tmp_path / "s")
    assert proc.returncode == 9, proc.stdout[:300]
    carrier = next(r for r in doc["results"] if r.get("error", {}).get("code") == "too_large" and "--max-chars" in r["error"]["fix"])
    pointers = [r["error"]["fix"] for r in doc["results"] if r.get("error", {}).get("fix", "").startswith("Recover with the fix on")]
    assert carrier["target"] == "AAA" and pointers, proc.stdout[:800]
    assert all("AAA" in fix for fix in pointers), pointers


# ---- following a cut never skips a row --------------------------------------------------------------------------------


def follow(cli, store, continuation, extra=()):
    """Run each continuation's command until none is left; returns every page's result."""
    pages = []
    while continuation:
        command = shlex.split(continuation["command"])
        assert len(pages) < 60, "the continuation never ends"
        proc, page = cli(*command, *extra, routes=[], store=store)
        assert proc.returncode in (0, 8), proc.stdout[:400]
        pages.append(page["results"][0])
        continuation = pages[-1].get("continuation")
    return pages


def test_the_continuation_after_a_newest_tail_starts_over_and_reaches_every_row(cli, tmp_path):
    """The first cut of an oldest-first series keeps its newest rows, so a continuation that starts after the number shown never reaches the rows before the tail."""
    store = tmp_path / "s"
    proc, doc = cli("prices", "history", "AAPL", "--period", "1y", "--fields", "Close", "--max-chars", "1500", routes=series_routes(100), store=store)
    assert proc.returncode == 8, proc.stdout[:400]
    first = doc["results"][0]
    shown = closes(first)
    assert first["coverage"]["kept"] == "newest" and shown == list(range(100 - len(shown), 100)), shown
    assert first["continuation"] == {"start": 0, "restart": True, "shown": [100 - len(shown), 100],
                                     "command": f"read {first['id']} --fields Close --start 0 --limit {len(shown)}"}
    read = [value for page in follow(cli, store, first["continuation"], ("--max-chars", "1500")) for value in closes(page)]
    assert read == list(range(100)), "rows were skipped or read twice"


def chain_routes(calls, puts, wide=0):
    """An option chain whose calls carry strikes 100, 101, … and whose puts carry 200, 201, …; `wide` pads each contract symbol."""
    def contract(prefix, strike, i):
        return {"contractSymbol": f"{prefix}{i}" + "x" * wide, "strike": strike + i, "lastPrice": 1.0, "currency": "USD"}
    chain = {"optionChain": {"result": [{"expirationDates": [1735689600], "quote": {"symbol": "AAPL", "regularMarketPrice": 100},
             "options": [{"expirationDate": 1735689600, "calls": [contract("C", 100.0, i) for i in range(calls)],
                          "puts": [contract("P", 200.0, i) for i in range(puts)]}]}], "error": None}}
    return [{"path": "/v7/finance/options/AAPL", "json": chain}]


def strikes(result, side):
    return [row[0] for row in result["data"][side]["data"]]


@pytest.mark.parametrize("calls,puts", [(60, 45), (60, 25), (5, 0)])
def test_reading_a_chain_page_by_page_reaches_every_contract_of_both_sides_once(cli, tmp_path, calls, puts):
    """Each side is cut from the same start, so the next start is the furthest row any side reached; adding the two sides' counts skipped rows of both, and a side that ran out first was refused."""
    store = tmp_path / "s"
    proc, doc = cli("options", "chain", "AAPL", "--fields", "strike", routes=chain_routes(calls, puts), store=store)
    assert proc.returncode == 0, proc.stdout[:400]
    ident = doc["results"][0]["id"]
    proc, page = cli("read", ident, "--fields", "strike", "--start", "0", "--limit", "20", routes=[], store=store)
    assert proc.returncode == 0, proc.stdout[:400]
    pages = [page["results"][0]] + follow(cli, store, page["results"][0].get("continuation"))
    assert [s for p in pages for s in strikes(p, "calls")] == [100 + i for i in range(calls)]
    assert [s for p in pages for s in strikes(p, "puts")] == [200 + i for i in range(puts)]


def test_a_chain_read_the_budget_narrows_page_by_page_still_reaches_every_contract_once(cli, tmp_path):
    """Padded symbols make every 20-row page too large for 1,500 characters, so each page is narrowed below the --limit asked for and the next start has to follow what was actually shown."""
    store = tmp_path / "s"
    proc, doc = cli("options", "chain", "AAPL", "--fields", "contractSymbol,strike", "--limit", "1", routes=chain_routes(60, 45, wide=40), store=store)
    assert proc.returncode == 0, proc.stdout[:400]
    ident = doc["results"][0]["id"]
    proc, page = cli("read", ident, "--fields", "contractSymbol,strike", "--start", "0", "--limit", "20", "--max-chars", "1500", routes=[], store=store)
    assert proc.returncode == 8, proc.stdout[:400]
    first = page["results"][0]
    assert first["coverage"]["calls"]["truncated_by"] == "budget" and first["coverage"]["calls"]["shown"] < 20
    pages = [first] + follow(cli, store, first.get("continuation"), ("--max-chars", "1500"))
    assert [row[1] for p in pages for row in p["data"]["calls"]["data"]] == [100 + i for i in range(60)]
    assert [row[1] for p in pages for row in p["data"]["puts"]["data"]] == [200 + i for i in range(45)]


def test_a_chain_whose_smallest_page_is_too_large_is_told_so_and_the_size_it_names_works(cli, tmp_path):
    """One contract per side is the smallest page, so a recovery that names --limit 1 repeats the same refusal."""
    store = tmp_path / "s"
    routes = chain_routes(3, 3, wide=30000)
    proc, doc = cli("options", "chain", "AAPL", "--max-chars", "3000", routes=routes, store=store)
    assert proc.returncode == 9, proc.stdout[:400]
    fix = doc["results"][0]["error"]["fix"]
    assert "single entry" in fix and "--limit 1" not in fix, fix
    proc, doc = cli("options", "chain", "AAPL", *parse(fix, "max-chars"), routes=routes, store=store)
    assert proc.returncode == 0, proc.stdout[:400]


CHAIN_COLUMNS = ["contractSymbol", "lastTradeDate", "strike", "lastPrice", "bid", "ask", "change", "percentChange", "volume", "openInterest",
                 "impliedVolatility", "inTheMoney", "contractSize", "currency"]  # the columns yfinance 1.7.0 reindexes every chain side to


def test_a_chain_lists_the_columns_its_sides_have_and_selects_them_on_both_sides(cli, tmp_path):
    store = tmp_path / "s"
    proc, doc = cli("options", "chain", "AAPL", "--list-fields", routes=chain_routes(3, 2), store=store)
    assert proc.returncode == 0, proc.stdout[:400]
    assert doc["results"][0]["data"] == CHAIN_COLUMNS
    proc, back = cli("read", doc["results"][0]["id"], "--list-fields", routes=[], store=store)
    assert back["results"][0]["data"] == CHAIN_COLUMNS
    proc, doc = cli("options", "chain", "AAPL", "--fields", "strike", routes=chain_routes(3, 2), store=store)
    assert proc.returncode == 0, proc.stdout[:400]
    assert strikes(doc["results"][0], "calls") == [100, 101, 102] and strikes(doc["results"][0], "puts") == [200, 201]


def test_a_chain_over_the_budget_is_narrowed_on_both_sides_and_keeps_its_id(cli, tmp_path):
    """One padded contract per side fits 3,500 characters and two per side do not, so the budget keeps exactly the first contract of each side — on the first call and on a read of the same observation."""
    store = tmp_path / "s"

    def narrowed(proc, doc, kept):
        assert proc.returncode == 8, proc.stdout[:400]
        assert len(proc.stdout.strip()) <= 3500
        r = doc["results"][0]
        assert [row[1] for row in r["data"]["calls"]["data"]] == [100] and [row[1] for row in r["data"]["puts"]["data"]] == [200]
        assert r["data"]["calls"]["data"][0][0] == "C0" + "x" * 900
        for side in ("calls", "puts"):
            assert r["coverage"][side] == {"received": 6, "fields": {"received": 14, "shown": 2, "source": "requested"}, "kept": kept, "truncated_by": "budget", "shown": 1}
        assert r["continuation"] == {"start": 1, "command": f"read {r['id']} --fields contractSymbol,strike --start 1 --limit 1"}
        return r["id"]

    proc, doc = cli("options", "chain", "AAPL", "--fields", "contractSymbol,strike", "--max-chars", "3500", routes=chain_routes(6, 6, wide=900), store=store)
    ident = narrowed(proc, doc, "first")
    proc, doc = cli("read", ident, "--fields", "contractSymbol,strike", "--max-chars", "3500", routes=[], store=store)
    assert narrowed(proc, doc, "window") == ident
    assert (store / f"{ident}.json").exists()


def test_a_chain_whose_single_contract_exceeds_the_budget_is_refused_with_its_id(cli, tmp_path):
    store = tmp_path / "s"
    proc, doc = cli("options", "chain", "AAPL", "--max-chars", "3000", routes=chain_routes(3, 3, wide=5000), store=store)
    assert proc.returncode == 9, proc.stdout[:400]
    assert len(proc.stdout.strip()) <= 3000
    ident = doc["results"][0]["id"]
    assert ident and doc["results"][0]["error"]["code"] == "too_large"
    proc, back = cli("read", ident, "--max-chars", "100000", routes=[], store=store)
    assert proc.returncode == 0, proc.stdout[:400]
    assert len(back["results"][0]["data"]["calls"]["data"]) == 3 and len(back["results"][0]["data"]["puts"]["data"]) == 3
