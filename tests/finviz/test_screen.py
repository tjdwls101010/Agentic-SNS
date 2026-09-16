import json
import re

import pytest

from pages import screener_filters, screener_table


def test_filters_list_ids_labels_definitions_and_combined_values_and_filter_narrows(client):
    client.add("https://finviz.com/screener?ft=4", screener_filters())
    result = client.one("screen", "filters")
    assert [f["id"] for f in result["data"]] == ["cap", "sec"]
    cap = result["data"][0]
    assert cap["label"] == "Market Cap."
    assert cap["definition"] == "Market Cap. Total market value of a company's outstanding shares."
    assert cap["options"] == [{"value": "cap_mega", "label": "Mega ($200bln and more)"}, {"value": "cap_largeover", "label": "+Large (over $10bln)"}]
    assert cap.get("elite_only") == ["Custom (Elite only)"]
    narrowed = client.one("screen", "filters", "--filter", "sector")
    assert [f["id"] for f in narrowed["data"]] == ["sec"]
    assert narrowed["coverage"] == {"received": 2, "shown": 1, "exhaustive": False}


def test_signals_list_values_and_labels_without_the_none_choice(client):
    client.add("https://finviz.com/screener?ft=4", screener_filters())
    result = client.one("screen", "signals")
    assert result["data"] == [{"value": "ta_topgainers", "label": "Top Gainers"}, {"value": "ta_newhigh", "label": "New High"}]


def test_columns_list_ids_titles_indices_and_categories(client):
    client.add("https://finviz.com/screener?v=152", screener_table([], columns=["ticker"]))
    result = client.one("screen", "columns", "--filter", "market")
    assert result["data"] == [{"id": "marketCap", "title": "Market Cap", "index": 6, "category": "Valuation"}]


def test_views_are_described_offline(client):
    result = client.one("screen", "views")
    names = {v["name"]: v for v in result["data"]}
    assert names["overview"]["view_id"] == "111" and names["custom"]["view_id"] == "152"
    assert "id" not in result and "source" not in result


ROWS = [("AAPL", ["Apple Inc", "4827.02B"]), ("MSFT", ["Microsoft Corp", "3500.10B"])]


def test_run_returns_header_keyed_rows_with_confirmed_filters_total_and_continuation(client):
    client.add("https://finviz.com/screener?v=111&ft=4&f=sec_technology,cap_largeover&r=1", screener_table(ROWS, total=166, selected_filters=("sec_technology", "cap_largeover")))
    result = client.one("screen", "run", "--filters", "sec_technology,cap_largeover")
    assert result["data"][0] == {"No.": "1", "Ticker": "AAPL", "Company": "Apple Inc", "Market Cap": "4827.02B", "ticker": "AAPL", "url": "https://finviz.com/stock?t=AAPL&ty=c&p=d&b=1"}
    assert result["data"][1]["ticker"] == "MSFT"
    assert result["conditions"]["filters"] == {"requested": "sec_technology,cap_largeover", "status": "confirmed", "evidence": ["cap_largeover", "sec_technology"]}
    assert result["coverage"] == {"received": 2, "shown": 2, "source_total": 166, "exhaustive": False, "pages": 1}
    assert result["continuation"] == {"start": 21}
    assert "start" not in result["conditions"] or result["conditions"]["start"]["status"] == "confirmed"


def test_run_reports_an_unknown_filter_as_not_applied_even_though_rows_come_back(client):
    client.add("https://finviz.com/screener?v=111&ft=4&f=cap_bogus&r=1", screener_table(ROWS, total=9000))
    result = client.one("screen", "run", "--filters", "cap_bogus")
    assert result["status"] == "ok" and len(result["data"]) == 2
    assert result["conditions"]["filters"]["status"] == "not_applied"
    assert result["conditions"]["filters"]["evidence"] is None


def test_run_resolves_column_ids_through_the_catalog_and_confirms_selected_columns(client):
    client.add("https://finviz.com/screener?v=152", screener_table([], columns=["ticker"]))
    client.add("https://finviz.com/screener?v=152&ft=4&c=1,6&r=1", screener_table([("NVDA", ["4.2T"])], headers=("Ticker", "Market Cap"), columns=["ticker", "marketCap"]))
    result = client.one("screen", "run", "--columns", "ticker,marketCap")
    assert result["data"] == [{"Ticker": "NVDA", "Market Cap": "4.2T", "ticker": "NVDA", "url": "https://finviz.com/stock?t=NVDA&ty=c&p=d&b=1"}]
    assert result["conditions"]["columns"] == {"requested": "ticker,marketCap", "status": "confirmed", "evidence": ["ticker", "marketCap"]}
    client.add("https://finviz.com/screener?v=152&ft=4&f=sec_technology&c=1,6&r=1", screener_table([("NVDA", ["4.2T"])], headers=("Ticker", "Market Cap"), columns=["ticker", "marketCap"], filter_controls=False, echo="sec_technology"))
    filtered = client.one("screen", "run", "--columns", "ticker,marketCap", "--filters", "sec_technology")
    assert filtered["conditions"]["filters"] == {"requested": "sec_technology", "status": "unverified", "evidence": {"echoed_by_server": "sec_technology"}}
    assert "unverified" in filtered["warnings"][0]
    assert client.one("screen", "run", "--columns", "ticker,nope", code=2)["error"]["code"] == "invalid_columns"


def test_run_confirms_signal_and_sort_from_page_controls(client):
    client.add("https://finviz.com/screener?v=111&ft=4&s=ta_topgainers&o=-marketcap&r=1", screener_table(ROWS, signal="ta_topgainers", sort=("marketcap", "descending")))
    result = client.one("screen", "run", "--signal", "ta_topgainers", "--sort=-marketcap")
    assert result["conditions"]["signal"] == {"requested": "ta_topgainers", "status": "confirmed", "evidence": "ta_topgainers"}
    assert result["conditions"]["sort"] == {"requested": "-marketcap", "status": "confirmed", "evidence": {"column": "Market Cap", "key": "marketcap", "direction": "descending"}}
    client.add("https://finviz.com/screener?v=111&ft=4&o=pe&r=1", screener_table(ROWS))
    assert client.one("screen", "run", "--sort", "pe")["conditions"]["sort"]["status"] == "not_applied"


def test_run_follows_pages_into_a_jsonl_file_and_refuses_to_overwrite_it(client, tmp_path):
    pages = {1: ROWS, 21: [("GOOG", ["Alphabet", "2T"]), ("AMZN", ["Amazon", "2T"])], 41: [("META", ["Meta", "1T"])]}
    for start, rows in pages.items():
        client.add("https://finviz.com/screener?v=111&ft=4&f=sec_technology&r=%d" % start, screener_table(rows, total=5, current=start, selected_filters=("sec_technology",)))
    out = tmp_path / "rows.jsonl"
    result = client.one("screen", "run", "--filters", "sec_technology", "--pages", "3", "--out", str(out))
    assert result["data"] == {"path": str(out), "rows_written": 5, "pages": 3}
    assert result["coverage"] == {"received": 5, "shown": 5, "source_total": 5, "exhaustive": False, "pages": 3}
    assert "continuation" not in result
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["ticker"] for r in lines] == ["AAPL", "MSFT", "GOOG", "AMZN", "META"]
    assert len({r["observation_id"] for r in lines}) == 3
    assert client.one("screen", "run", "--filters", "sec_technology", "--out", str(out), code=2)["error"]["code"] == "export_exists"
    client.one("screen", "run", "--filters", "sec_technology", "--out", str(out), "--append")
    assert len(out.read_text().splitlines()) == 7
    partial = client.one("screen", "run", "--filters", "sec_technology", "--pages", "2")
    assert partial["continuation"] == {"start": 41} and partial["coverage"]["pages"] == 2 and len(partial["data"]) == 4
    error = client.run("--max-chars", "300", "screen", "run", "--filters", "sec_technology", "--pages", "2", code=9)["results"][0]["error"]
    assert "--out" in error["fix"]


def test_run_starts_at_a_continuation_and_confirms_the_page_offset(client):
    client.add("https://finviz.com/screener?v=111&ft=4&r=21", screener_table(ROWS, current=21, total=166))
    result = client.one("screen", "run", "--start", "21")
    assert result["conditions"]["start"] == {"requested": 21, "status": "confirmed", "evidence": 21}
    assert result["data"][0]["No."] == "21"
    assert result["continuation"] == {"start": 41}


def test_each_page_observation_keeps_its_own_rows_and_conditions(client):
    client.add("https://finviz.com/screener?v=111&ft=4&f=cap_largeover&r=1", screener_table(ROWS, total=4, current=1, page_values=(1, 21), selected_filters=("cap_largeover",)))
    client.add("https://finviz.com/screener?v=111&ft=4&f=cap_largeover&r=21", screener_table([("GOOG", ["Alphabet", "2T"])], total=4, current=21, page_values=(1, 21)))
    result = client.one("screen", "run", "--filters", "cap_largeover", "--pages", "2")
    first, second = result["source"]["pages"]
    assert [r["ticker"] for r in client.one("read", second, "--pointer", "/data")["data"]] == ["GOOG"]
    assert client.one("read", second)["data"]["conditions"]["filters"]["status"] == "not_applied"
    assert result["conditions"]["filters"]["status"] == "not_applied"
    assert result["conditions"]["filters"]["evidence"] == {first: ["cap_largeover"], second: None}


def test_a_failing_later_page_keeps_earlier_rows_and_names_the_resume_offset(client, tmp_path):
    client.add("https://finviz.com/screener?v=111&ft=4&f=sec_technology&r=1", screener_table(ROWS, total=40, current=1, page_values=(1, 21)))
    client.add("https://finviz.com/screener?v=111&ft=4&f=sec_technology&r=21", "", status=429, headers={"Retry-After": "30"})
    out = tmp_path / "rows.jsonl"
    result = client.one("screen", "run", "--filters", "sec_technology", "--pages", "2", "--out", str(out), code=8)
    assert result["status"] == "partial" and result["data"]["rows_written"] == 2
    assert result["continuation"] == {"start": 21}
    assert result["error"]["code"] == "access_restricted" and "21" in result["warnings"][0]
    assert len(out.read_text().splitlines()) == 2
    plain = client.one("screen", "run", "--filters", "sec_technology", "--pages", "2", code=8)
    assert [r["ticker"] for r in plain["data"]] == ["AAPL", "MSFT"] and plain["continuation"] == {"start": 21}


def test_export_applies_selection_and_reports_empty_when_nothing_matched(client, tmp_path):
    client.add("https://finviz.com/screener?v=111&ft=4&r=1", screener_table(ROWS, total=2, page_values=(1,)))
    out = tmp_path / "rows.jsonl"
    result = client.one("screen", "run", "--fields", "ticker", "--limit", "1", "--out", str(out))
    assert [json.loads(line) for line in out.read_text().splitlines()] == [{"ticker": "AAPL", "observation_id": result["source"]["pages"][0]}]
    assert result["coverage"] == {"received": 2, "shown": 1, "source_total": 2, "exhaustive": False, "pages": 1}
    empty = client.one("screen", "run", "--filter", "nomatch", "--out", str(tmp_path / "none.jsonl"), code=7)
    assert empty["status"] == "empty" and empty["data"]["rows_written"] == 0


def test_missing_column_catalog_is_a_structure_change_not_an_empty_list(client):
    client.add("https://finviz.com/screener?v=152", '<html><body><script id="route-init-data" type="application/json">{}</script></body></html>')
    assert client.one("screen", "columns", code=6)["error"]["code"] == "structure_changed"


def test_sort_falls_back_to_the_order_control_when_no_header_is_marked(client):
    page = screener_table(ROWS).replace('is-selected is-ascending', '') + '<select id="orderSelect"><option selected="selected" value="screener?v=111&ft=4&o=-marketcap">Market Capitalization</option></select>'
    client.add("https://finviz.com/screener?v=111&ft=4&o=-marketcap&r=1", page)
    result = client.one("screen", "run", "--sort=-marketcap")
    assert result["conditions"]["sort"] == {"requested": "-marketcap", "status": "confirmed", "evidence": {"key": "marketcap", "direction": "descending", "column": "Market Capitalization"}}


def test_aggregate_reports_a_later_page_returning_the_wrong_start(client):
    for start in (1, 21):
        client.add(f"https://finviz.com/screener?v=111&ft=4&r={start}", screener_table(ROWS, current=1, page_values=(1, 21)))
    result = client.one("screen", "run", "--pages", "2")
    first, second = result["source"]["pages"]
    assert result["conditions"]["start"] == {"requested": 1, "status": "not_applied", "evidence": {first: 1, second: 1}}
    assert client.one("read", second)["data"]["conditions"]["start"] == {"requested": 21, "status": "not_applied", "evidence": 1}
    assert len(result["data"]) == 4  # Keep the received rows; do not silently deduplicate the source.


def test_oversized_aggregate_and_every_page_are_recoverable_without_fetching(client):
    for start, ticker in ((1, "FIRST"), (21, "SECOND")):
        client.add(f"https://finviz.com/screener?v=111&ft=4&r={start}", screener_table([(ticker, [ticker * 2200, "2T"])], current=start, page_values=(1, 21)))
    result = client.one("screen", "run", "--pages", "2", code=9)
    assert result["error"]["code"] == "too_large"
    client.responses.clear()
    pointers = client.one("inspect", result["id"])["data"]
    assert "/source/pages" in {entry["pointer"] for entry in pointers}
    ids = client.one("read", result["id"], "--pointer", "/source/pages")["data"]
    assert len(ids) == 2 and result["id"] not in ids
    for offset, (page_id, ticker) in enumerate(zip(ids, ("FIRST", "SECOND"))):
        recovered = client.one("read", result["id"], "--pointer", "/data", "--start", str(offset), "--limit", "1")
        assert recovered["data"][0]["ticker"] == ticker
        assert recovered["data"][0]["observation_id"] == page_id
        page = client.one("read", page_id, "--pointer", "/data")
        assert page["data"][0]["ticker"] == ticker and page["data"][0]["Market Cap"] == "2T"
        assert ticker in client.one("read", page_id, "--raw")["data"]


@pytest.mark.parametrize("body,status,code", [("wait", 429, "access_restricted"), ("<html>Changed layout</html>", 200, "structure_changed")])
def test_caught_later_page_failure_is_saved_with_original_error(client, body, status, code):
    client.add("https://finviz.com/screener?v=111&ft=4&r=1", screener_table(ROWS, page_values=(1, 21)))
    client.add("https://finviz.com/screener?v=111&ft=4&r=21", body, status=status, headers={"Retry-After": "30"})
    result = client.one("screen", "run", "--pages", "2", code=8)
    failed_id = re.search(r"observation ([a-f0-9]+)", " ".join(result["warnings"]))[1]
    saved = client.one("read", failed_id)
    assert saved["data"]["status"] == "error" and saved["data"]["error"]["code"] == code
    assert saved["data"]["error"] == result["error"]
    raw = client.one("read", failed_id, "--raw")
    assert raw["data"] == body and any("original observation failed" in warning for warning in raw["warnings"])
    assert client.one("read", result["id"])["data"]["status"] == "partial"


def test_aggregate_keeps_unselected_rows_even_when_export_selection_is_empty(client, tmp_path):
    for start, rows in ((1, ROWS), (21, [("GOOG", ["Alphabet", "2T"])])):
        client.add(f"https://finviz.com/screener?v=111&ft=4&r={start}", screener_table(rows, current=start, page_values=(1, 21)))
    out = tmp_path / "empty.jsonl"
    result = client.one("screen", "run", "--pages", "2", "--filter", "missing", "--fields", "ticker", "--out", str(out), code=7)
    assert out.read_text() == "" and result["coverage"]["shown"] == 0
    saved = client.one("read", result["id"])["data"]
    assert saved["status"] == "ok" and saved["coverage"]["shown"] == 3
    assert [row["ticker"] for row in saved["data"]] == ["AAPL", "MSFT", "GOOG"]
    assert saved["data"][2]["Market Cap"] == "2T"
    assert json.loads(client.one("read", result["id"], "--raw")["data"]) == saved
