import json

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
    assert result["coverage"] == {"received": 5, "source_total": 5, "exhaustive": False, "pages": 3}
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
