"""A result over --max-chars shows the window that fits, says partial, and continues the same selection to the end of the request."""

import json
import shlex

import pytest

from pages import stock_section


def follow(client, first, budget):
    """Run each continuation verbatim until the request is finished; returns every result document seen."""
    documents, command = [first], first.get("continuation")
    while command:
        doc = client.run(*shlex.split(command), "--max-chars", str(budget), code=None)
        documents.append(doc)
        command = doc.get("continuation")
    return documents


CHAIN = {"expiries": ["2026-10-16"], "currentExpiry": "2026-10-16", "lastClose": 152.0, "lastTime": 1789415995, "options": [{"ticker": "A", "strike": strike, "type": kind, "iv": 1.0 + strike / 1000, "delta": 0.5, "openInterest": strike * 3} for strike in range(100, 200, 5) for kind in ("call", "put")]}


def test_continuing_a_budgeted_option_chain_returns_exactly_the_unbudgeted_selection(client):
    client.add("https://finviz.com/stock?t=A&ty=oc", stock_section(CHAIN))
    selection = ["stock", "options", "A", "--type", "put", "--strikes", "0", "--fields", "strike,type,iv"]
    whole = client.one(*selection, "--max-chars", "100000")["data"]["contracts"]
    assert len(whole) == 20 and {c["type"] for c in whole} == {"put"}
    first = client.run(*selection, "--max-chars", "900", code=8)
    assert first["status"] == "partial" and first["results"][0]["coverage"]["cut"] == "budget"
    pieces = [c for doc in follow(client, first, 900) for c in doc["results"][0]["data"]["contracts"]]
    assert pieces == whole
    assert all(len(json.dumps(doc, ensure_ascii=False, separators=(",", ":"))) <= 900 for doc in follow(client, first, 900))


from collections import defaultdict  # noqa: E402

from pages import calendar_page, groups_page, insiders_page, news_page, pulse_page, screener_filters, screener_table, stock_overview  # noqa: E402

NOTE = "n" * 60


def rows(count, **fields):
    return [dict({"id": n, "note": NOTE}, **{k: (v % n if isinstance(v, str) and "%" in v else v) for k, v in fields.items()}) for n in range(count)]


# One fixture per leaf that returns records: enough of them that a small budget cannot show them all.
LEAVES = {
    "search": (["search", "A"], {"https://finviz.com/api/suggestions?input=A": rows(14, ticker="T%d")}),
    "screen filters": (["screen", "filters"], {"https://finviz.com/screener?ft=4": screener_filters(filters=[("f%d" % n, "Filter %d" % n, NOTE, [("a", "A")]) for n in range(14)])}),
    "screen run": (["screen", "run"], {"https://finviz.com/screener?v=111&ft=4&r=1": screener_table([("T%d" % n, ["Company " + NOTE, "1B"]) for n in range(14)], page_values=(1,))}),
    "stock overview": (["stock", "overview", "A"], {"https://finviz.com/stock?t=A&ty=c": stock_overview(metrics=[("M%d" % n, "1", NOTE) for n in range(14)])}),
    "stock earnings": (["stock", "earnings", "A", "--sections", "revisions", "--fiscal-period", "2026Q4"], {"https://finviz.com/stock?t=A&ty=ea": stock_section({"earningsData": [], "earningsRevisionsData": [{"fiscalPeriod": "2026Q4", "estimateType": "E", "estimateDate": "2026-09-%02d" % (n + 1), "mean": n, "note": NOTE} for n in range(14)]})}),
    "stock forecast": (["stock", "forecast", "A"], {"https://finviz.com/stock?t=A&ty=fc": stock_section({"targetPrice": 1, "recommendationsData": rows(14, recomDate="2026-01-%02d")})}),
    "stock dividends": (["stock", "dividends", "A"], {"https://finviz.com/stock?t=A&ty=dv": stock_section({"dividendsData": rows(14), "dividendsAnnualData": rows(14)})}),
    "stock revenue": (["stock", "revenue", "A"], {"https://finviz.com/stock?t=A&ty=rv": stock_section({"products_and_services": {"unit": "USD", "revenues": {"S%d" % n: [{"fiscal_year": "2025", "value": n, "note": NOTE}] for n in range(14)}}})}),
    "stock short-interest": (["stock", "short-interest", "A"], {"https://finviz.com/stock?t=A&ty=si": stock_section(rows(14, timestamp=1))}),
    "stock options": (["stock", "options", "A", "--strikes", "0"], {"https://finviz.com/stock?t=A&ty=oc": stock_section(CHAIN)}),
    "stock filings": (["stock", "filings", "A"], {"https://finviz.com/stock?t=A&ty=lf": stock_section({"entries": {"items": rows(14, form="4"), "page": 1, "totalPages": 1}})}),
    "stock statement": (["stock", "statement", "A"], {"https://finviz.com/api/statement?t=A&so=F&s=IA": {"currency": "USD", "data": dict({"Period": ["TTM", "2025FY"]}, **{"Line item %d %s" % (n, NOTE): ["1", "2"] for n in range(14)})}}),
    "stock prices": (["stock", "prices", "A", "--bars", "14"], {"https://finviz.com/api/quote?instrument=stock&ticker=A&timeframe=d&barsCount=14": {k: list(range(14)) for k in ("date", "open", "high", "low", "close", "volume")}}),
    "groups table": (["groups", "table"], {"https://finviz.com/groups?g=sector&v=110": groups_page(rows=[("Group %d %s" % (n, NOTE[:20]), "sec_%d" % n, ["1", "2B", "1%"]) for n in range(14)])}),
    "groups performance": (["groups", "performance"], {"https://finviz.com/api/groups_perf?g=sector": rows(14, label="G%d")}),
    "market quotes": (["market", "quotes", "futures"], {"https://finviz.com/api/futures_all?timeframe=d": {"F%d" % n: {"label": NOTE, "last": n} for n in range(14)}}),
    "market performance": (["market", "performance", "futures"], {"https://finviz.com/api/futures/performance": {"rows": rows(14, ticker="F%d")}}),
    "market map": (["market", "map"], {"https://finviz.com/api/map_perf?t=sec&st=d1": {"nodes": {"TICKER%d%s" % (n, NOTE[:30]): n for n in range(14)}, "subtype": "d1"}}),
    "market bubbles": (["market", "bubbles"], {"https://finviz.com/api/bubbles?x=sector&y=lastChange&size=marketCap&color=sector&idx=dji": rows(14, ticker="T%d")}),
    "calendar earnings": (["calendar", "earnings"], {"https://finviz.com/calendar/earnings": calendar_page({"data": {"initialDateFrom": "2026-09-15", "entries": {"items": rows(14, ticker="T%d"), "page": 1, "totalPages": 1}}})}),
    "news headlines": (["news", "headlines"], {"https://finviz.com/news": news_page(items=tuple(("0%d:00AM" % (n % 10), "Headline %d %s" % (n, NOTE), "https://example.com/%d" % n, "Source", ()) for n in range(14)))}),
    "news pulse": (["news", "pulse"], {"https://finviz.com/news?v=6": pulse_page(items=tuple((n + 1, "1 min", "Pulse %d %s" % (n, NOTE), ("A",)) for n in range(14)))}),
    "news article": (["news", "article", "https://finviz.com/news/1/a"], {"https://finviz.com/news/1/a": "<html><body><h1>T</h1><article>" + "".join("<p>Paragraph %d %s</p>" % (n, NOTE) for n in range(14)) + "</article></body></html>"}),
    "insiders trades": (["insiders", "trades", "--limit", "14"], {"https://finviz.com/insidertrading?tc=7": insiders_page(rows=tuple(("T%d" % n, "Owner " + NOTE[:30], str(n), "Director", "Sep 12 '26", "Sale", "1", "1", "1", "1", "Sep 14", "http://www.sec.gov/x.xml") for n in range(14)))}),
}


def collections_in(client, arguments):
    return list(client.one("schema", *arguments[:2] if arguments[0] not in ("search",) else arguments[:1])["data"].get("collections") or {})


def gathered(client, arguments, budget):
    """Records per (result, collection) from a budgeted call and every continuation after it, followed verbatim."""
    names = collections_in(client, arguments)
    got, queue, seen = defaultdict(list), [], []
    first = client.run(*arguments, "--max-chars", str(budget), code=None)
    documents = [first]
    while documents:
        doc = documents.pop(0)
        seen.append(doc)
        for index, result in enumerate(doc["results"]):
            for name in names:
                got[(index, name)] += (result.get("data") or {}).get(name) or []
        found = doc.get("continuation") or []
        queue += [found] if isinstance(found, str) else found
        while queue:
            documents.append(client.run(*shlex.split(queue.pop(0)), code=None))
    return first, dict(got), seen


@pytest.mark.parametrize("leaf", list(LEAVES))
def test_every_leaf_over_the_budget_shows_a_window_and_continues_to_exactly_the_unbudgeted_answer(client, leaf):
    arguments, responses = LEAVES[leaf]
    for url, body in responses.items():
        client.add(url, body)
    whole = client.run(*arguments, "--max-chars", "1000000")
    names = collections_in(client, arguments)
    expected = {(i, n): r["data"][n] for i, r in enumerate(whole["results"]) for n in names if n in r["data"]}
    assert any(len(v) >= 10 for v in expected.values()), leaf
    envelope = len(json.dumps(client.run(*arguments, "--limit", "0", "--max-chars", "1000000"), ensure_ascii=False, separators=(",", ":")))
    budget = envelope + (len(json.dumps(whole, ensure_ascii=False, separators=(",", ":"))) - envelope) // 2 + 150  # room for the continuation line
    first, got, documents = gathered(client, arguments, budget)
    assert first["status"] == "partial" and first.get("continuation"), leaf
    assert {k: v for k, v in got.items() if v or k in expected} == expected, leaf
    assert all(len(json.dumps(d, ensure_ascii=False, separators=(",", ":"))) <= budget for d in documents)


def test_a_limit_cut_by_the_budget_continues_to_exactly_that_limit(client):
    client.add("https://finviz.com/api/suggestions?input=A", rows(40, ticker="T%d"))
    whole = client.one("search", "A", "--limit", "10", "--max-chars", "100000")["data"]["candidates"]
    size = len(json.dumps(client.run("search", "A", "--limit", "4", "--max-chars", "100000"), separators=(",", ":")))
    first, got, _ = gathered(client, ["search", "A", "--limit", "10"], size + 40)
    assert first["results"][0]["coverage"]["shown"] < 10 and got[(0, "candidates")] == whole and len(whole) == 10


def test_several_targets_are_cut_to_the_same_count_and_one_continuation_carries_all(client):
    for ticker, count in (("A", 30), ("B", 12)):
        news = tuple(("Sep-%02d-26 04:30PM" % (n + 1), "%s headline %d %s" % (ticker, n, NOTE), "https://example.com/%s%d" % (ticker, n), "S") for n in range(count))
        client.add("https://finviz.com/stock?t=%s&ty=c" % ticker, stock_overview(ticker=ticker, news=news))
    arguments = ["stock", "overview", "A", "B", "--sections", "news", "--limit", "25"]
    whole = client.run(*arguments, "--max-chars", "1000000")
    first, got, _ = gathered(client, arguments, 4000)
    shown = [r["coverage"]["news"]["shown"] for r in first["results"]]
    assert shown[0] == shown[1] < 12 and isinstance(first["continuation"], str)
    assert got[(0, "news")] == whole["results"][0]["data"]["news"] and got[(1, "news")] == whole["results"][1]["data"]["news"]


def test_two_sections_cut_by_the_budget_continue_to_exactly_the_unbudgeted_answer(client):
    news = tuple(("Sep-%02d-26 04:30PM" % (n + 1), "Headline %d %s" % (n, NOTE), "https://example.com/%d" % n, "S") for n in range(15))
    ratings = tuple(("Sep-%02d-26" % (n + 1), "Upgrade", "Analyst " + NOTE, "Buy", "$1") for n in range(15))
    client.add("https://finviz.com/stock?t=A&ty=c", stock_overview(news=news, ratings=ratings))
    arguments = ["stock", "overview", "A", "--sections", "news,ratings", "--limit", "15"]
    whole = client.one(*arguments, "--max-chars", "1000000")["data"]
    first, got, _ = gathered(client, arguments, 3000)
    assert first["continuation"]
    assert got[(0, "news")] == whole["news"] and got[(0, "ratings")] == whole["ratings"]


def test_too_large_is_only_for_a_record_that_cannot_fit_alone_and_its_fix_fits(client):
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A", "exchange": "NYSE", "company": "x" * 3000}, {"ticker": "B", "company": "y"}])
    doc = client.run("search", "A", "--max-chars", "1500", code=9)
    error = doc["results"][0]["error"]
    assert error["code"] == "too_large" and len(json.dumps(doc, separators=(",", ":"))) <= 1500
    command = shlex.split(error["fix"].split("Project it: ")[1].split(" (fields:")[0])
    assert command[0] == "read" and "--fields" in command
    recovered = client.one(*command, "--max-chars", "1500")
    assert recovered["data"]["candidates"][0]["ticker"] == "A" and "company" not in recovered["data"]["candidates"][0]
    tiny = client.raw("search", "A", "--max-chars", "250", code=9)
    assert len(tiny.stdout.strip()) <= 250 and json.loads(tiny.stdout)["results"][0]["id"]


def test_an_error_document_for_many_failed_targets_stays_inside_the_budget(client):
    tickers = ["T%d" % n for n in range(10)]
    for ticker in tickers:
        client.add("https://finviz.com/stock?t=%s&ty=c" % ticker, "missing", status=404)
    doc = client.run("stock", "overview", *tickers, "--max-chars", "600", code=6)
    assert len(json.dumps(doc, separators=(",", ":"))) <= 600 and doc["results"][0]["error"]["code"] == "http_error"


def test_the_smallest_budget_is_refused_where_it_is_given_and_the_next_one_still_parses(client):
    refused = client.one("--max-chars", "120", "schema", code=2)
    assert refused["error"]["code"] == "invalid_argument" and "200" in refused["error"]["message"]
    doc = client.run("--max-chars", "200", "schema", code=9)
    assert len(json.dumps(doc, separators=(",", ":"))) <= 200 and doc["results"][0]["status"] == "error"
    assert "read " not in doc["results"][0]["error"]["fix"]  # there is no saved observation to offer


def test_a_section_that_fits_is_shown_even_when_another_sections_first_record_does_not(client):
    news = tuple(("Sep-%02d-26 04:30PM" % (n + 1), "Headline %d" % n, "https://example.com/%d" % n, "S") for n in range(5))
    client.add("https://finviz.com/stock?t=A&ty=c", stock_overview(metrics=[("M%d" % n, "1", "d" * 40) for n in range(3)], news=news, insiders=(("Owner " + "o" * 900, "Director", "Sep 04 '26", "Sale", "1", "1", "1", "1", "Sep 09 04:01 PM", "http://www.sec.gov/x.xml"),)))
    arguments = ["stock", "overview", "A", "--sections", "news,insiders"]
    alone = len(json.dumps(client.run(*arguments, "--max-chars", "1000000", "--limit", "0"), separators=(",", ":")))
    first = client.run(*arguments, "--max-chars", str(alone + 450), code=8)
    assert first["results"][0]["data"]["news"] and first["results"][0]["coverage"]["insiders"]["cut"] == "budget"
    assert any("--section insiders" in c for c in ([first["continuation"]] if isinstance(first["continuation"], str) else first["continuation"]))
