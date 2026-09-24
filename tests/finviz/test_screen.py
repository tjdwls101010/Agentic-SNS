import json
import re

import pytest

from pages import screener_filters, screener_table


def test_filters_list_ids_labels_definitions_and_combined_values_and_filter_narrows(client):
    client.add("https://finviz.com/screener?ft=4", screener_filters())
    result = client.one("screen", "filters", "--options")
    assert [f["id"] for f in result["data"]["filters"]] == ["cap", "sec"]
    cap = result["data"]["filters"][0]
    assert cap["label"] == "Market Cap."
    assert cap["definition"] == "Market Cap. Total market value of a company's outstanding shares."
    assert cap["options"] == [{"value": "cap_mega", "label": "Mega ($200bln and more)"}, {"value": "cap_largeover", "label": "+Large (over $10bln)"}]
    assert cap.get("elite_only") == ["Custom (Elite only)"]
    narrowed = client.one("screen", "filters", "--filter", "sector")
    assert [f["id"] for f in narrowed["data"]["filters"]] == ["sec"]
    assert narrowed["coverage"] == {"received": 2, "matched": 1, "shown": 1, "start": 0}


def test_filters_default_to_the_catalog_without_option_lists_and_attach_them_on_request(client):
    """The option lists are 14x the catalog: the first call has to answer "which filters exist" inside the budget."""
    client.add("https://finviz.com/screener?ft=4", screener_filters())
    default = client.one("screen", "filters")
    assert default["data"]["filters"] == [
        {"id": "cap", "label": "Market Cap.", "definition": "Market Cap. Total market value of a company's outstanding shares.", "option_count": 2},
        {"id": "sec", "label": "Sector", "definition": "Sector Company sector.", "option_count": 1},
    ]
    assert default["coverage"] == {"received": 2, "matched": 2, "shown": 2, "start": 0}
    attached = client.one("read", default["id"], "--options")
    assert attached["data"]["filters"][0]["options"] == [{"value": "cap_mega", "label": "Mega ($200bln and more)"}, {"value": "cap_largeover", "label": "+Large (over $10bln)"}]
    one = client.one("screen", "filters", "--filter", "sector", "--options")
    assert [f["id"] for f in one["data"]["filters"]] == ["sec"] and one["data"]["filters"][0]["options"] == [{"value": "sec_technology", "label": "Technology"}]


def test_signals_list_values_and_labels_without_the_none_choice(client):
    client.add("https://finviz.com/screener?ft=4", screener_filters())
    result = client.one("screen", "signals")
    assert result["data"]["signals"] == [{"value": "ta_topgainers", "label": "Top Gainers"}, {"value": "ta_newhigh", "label": "New High"}]


def test_columns_list_ids_titles_indices_and_categories(client):
    client.add("https://finviz.com/screener?v=152", screener_table([], columns=["ticker"]))
    result = client.one("screen", "columns", "--filter", "market")
    assert result["data"]["columns"] == [{"id": "marketCap", "title": "Market Cap", "index": 6, "category": "Valuation"}]


def test_views_are_described_by_the_view_argument(client):
    help_text = " ".join(client.raw("screen", "run", "--help", code=0).stdout.split())
    assert "valuation (P/E" in help_text and "custom (the columns named with --columns" in help_text
    assert client.one("screen", "views", code=2)["error"]["code"] == "invalid_argument"


ROWS = [("AAPL", ["Apple Inc", "4827.02B"]), ("MSFT", ["Microsoft Corp", "3500.10B"])]


def test_run_returns_header_keyed_rows_with_confirmed_filters_total_and_the_next_page(client):
    client.add("https://finviz.com/screener?v=111&ft=4&f=sec_technology,cap_largeover&r=1", screener_table(ROWS, total=166, selected_filters=("sec_technology", "cap_largeover")))
    result = client.one("screen", "run", "--filters", "sec_technology,cap_largeover")
    assert result["data"]["rows"][0] == {"No.": "1", "Ticker": "AAPL", "Company": "Apple Inc", "Market Cap": "4827.02B", "ticker": "AAPL", "url": "https://finviz.com/stock?t=AAPL&ty=c&p=d&b=1"}
    assert result["conditions"]["filters"] == {"requested": "sec_technology,cap_largeover", "status": "confirmed", "evidence": ["cap_largeover", "sec_technology"]}
    assert result["coverage"] == {"received": 2, "matched": 2, "shown": 2, "start": 0, "source_total": 166}
    assert result["next"] == "screen run --filters sec_technology,cap_largeover --row 21"
    assert result["conditions"]["row"]["status"] == "confirmed"


def test_run_reports_an_unknown_filter_as_not_applied_even_though_rows_come_back(client):
    client.add("https://finviz.com/screener?v=111&ft=4&f=cap_bogus&r=1", screener_table(ROWS, total=9000))
    result = client.one("screen", "run", "--filters", "cap_bogus")
    assert result["status"] == "ok" and len(result["data"]["rows"]) == 2
    assert result["conditions"]["filters"] == {"requested": "cap_bogus", "status": "not_applied", "evidence": None}


def test_run_resolves_column_ids_through_the_catalog_and_confirms_selected_columns(client):
    client.add("https://finviz.com/screener?v=152", screener_table([], columns=["ticker"]))
    client.add("https://finviz.com/screener?v=152&ft=4&c=1,6&r=1", screener_table([("NVDA", ["4.2T"])], headers=("Ticker", "Market Cap"), columns=["ticker", "marketCap"]))
    result = client.one("screen", "run", "--columns", "ticker,marketCap")
    assert result["data"]["rows"] == [{"Ticker": "NVDA", "Market Cap": "4.2T", "ticker": "NVDA", "url": "https://finviz.com/stock?t=NVDA&ty=c&p=d&b=1"}]
    assert result["conditions"]["columns"] == {"requested": "ticker,marketCap", "status": "confirmed", "evidence": ["ticker", "marketCap"]}
    client.add("https://finviz.com/screener?v=152&ft=4&f=sec_technology&c=1,6&r=1", screener_table([("NVDA", ["4.2T"])], headers=("Ticker", "Market Cap"), columns=["ticker", "marketCap"], filter_controls=False, echo="sec_technology"))
    filtered = client.one("screen", "run", "--columns", "ticker,marketCap", "--filters", "sec_technology")
    assert filtered["conditions"]["filters"] == {"requested": "sec_technology", "status": "unverified", "evidence": {"echoed_by_server": "sec_technology"}}
    assert "unverified" in filtered["warnings"][0]
    assert client.one("screen", "run", "--columns", "ticker,nope", code=2)["error"]["code"] == "invalid_columns"


def test_a_sortable_table_publishes_the_keys_its_own_headers_carry(client):
    client.add("https://finviz.com/screener?v=111&ft=4&r=1", screener_table(ROWS))
    result = client.one("screen", "run")
    assert result["data"]["sort_keys"] == {"No.": "no.", "Ticker": "ticker", "Company": "company", "Market Cap": "marketcap"}
    client.add("https://finviz.com/screener?v=111&ft=4&o=-marketcap&r=1", screener_table(ROWS, sort=("marketcap", "descending")))
    assert client.one("screen", "run", "--sort=-" + result["data"]["sort_keys"]["Market Cap"])["conditions"]["sort"]["status"] == "confirmed"


def test_run_confirms_signal_and_sort_from_page_controls(client):
    client.add("https://finviz.com/screener?v=111&ft=4&s=ta_topgainers&o=-marketcap&r=1", screener_table(ROWS, signal="ta_topgainers", sort=("marketcap", "descending")))
    result = client.one("screen", "run", "--signal", "ta_topgainers", "--sort=-marketcap")
    assert result["conditions"]["signal"] == {"requested": "ta_topgainers", "status": "confirmed", "evidence": "ta_topgainers"}
    assert result["conditions"]["sort"] == {"requested": "-marketcap", "status": "confirmed", "evidence": {"column": "Market Cap", "key": "marketcap", "direction": "descending"}}
    client.add("https://finviz.com/screener?v=111&ft=4&o=pe&r=1", screener_table(ROWS))
    assert client.one("screen", "run", "--sort", "pe")["conditions"]["sort"]["status"] == "not_applied"


def test_sort_falls_back_to_the_order_control_when_no_header_is_marked(client):
    page = screener_table(ROWS).replace("is-selected is-ascending", "") + '<select id="orderSelect"><option selected="selected" value="screener?v=111&ft=4&o=-marketcap">Market Capitalization</option></select>'
    client.add("https://finviz.com/screener?v=111&ft=4&o=-marketcap&r=1", page)
    assert client.one("screen", "run", "--sort=-marketcap")["conditions"]["sort"] == {"requested": "-marketcap", "status": "confirmed", "evidence": {"key": "marketcap", "direction": "descending", "column": "Market Capitalization"}}


def test_run_follows_pages_into_a_jsonl_file_and_refuses_to_overwrite_it(client, tmp_path):
    pages = {1: ROWS, 21: [("GOOG", ["Alphabet", "2T"]), ("AMZN", ["Amazon", "2T"])], 41: [("META", ["Meta", "1T"])]}
    for start, rows in pages.items():
        client.add("https://finviz.com/screener?v=111&ft=4&f=sec_technology&r=%d" % start, screener_table(rows, total=5, current=start, selected_filters=("sec_technology",)))
    out = tmp_path / "rows.jsonl"
    result = client.one("screen", "run", "--filters", "sec_technology", "--pages", "3", "--out", str(out))
    assert result["data"]["export"] == {"path": str(out), "rows_written": 5, "pages": 3}
    assert result["coverage"] == {"received": 5, "matched": 5, "shown": 5, "start": 0, "source_total": 5, "pages": 3}
    assert "next" not in result
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert [r["ticker"] for r in lines] == ["AAPL", "MSFT", "GOOG", "AMZN", "META"] and len({r["observation_id"] for r in lines}) == 3
    assert client.one("screen", "run", "--filters", "sec_technology", "--out", str(out), code=2)["error"]["code"] == "export_exists"
    client.one("screen", "run", "--filters", "sec_technology", "--out", str(out), "--append")
    assert len(out.read_text().splitlines()) == 7
    partial = client.one("screen", "run", "--filters", "sec_technology", "--pages", "2")
    assert partial["next"] == "screen run --filters sec_technology --row 41 --pages 2" and partial["coverage"]["pages"] == 2 and len(partial["data"]["rows"]) == 4


def test_run_starts_at_a_source_row_and_confirms_it(client):
    client.add("https://finviz.com/screener?v=111&ft=4&r=21", screener_table(ROWS, current=21, total=166))
    result = client.one("screen", "run", "--row", "21")
    assert result["conditions"]["row"] == {"requested": 21, "status": "confirmed", "evidence": 21}
    assert result["data"]["rows"][0]["No."] == "21" and result["next"] == "screen run --row 41"


def test_each_page_observation_keeps_its_own_rows_and_conditions(client):
    client.add("https://finviz.com/screener?v=111&ft=4&f=cap_largeover&r=1", screener_table(ROWS, total=4, current=1, page_values=(1, 21), selected_filters=("cap_largeover",)))
    client.add("https://finviz.com/screener?v=111&ft=4&f=cap_largeover&r=21", screener_table([("GOOG", ["Alphabet", "2T"])], total=4, current=21, page_values=(1, 21)))
    result = client.one("screen", "run", "--filters", "cap_largeover", "--pages", "2")
    first, second = result["source"]["pages"]
    page = client.one("read", second)
    assert [r["ticker"] for r in page["data"]["rows"]] == ["GOOG"] and page["conditions"]["filters"]["status"] == "not_applied"
    assert result["conditions"]["filters"] == {"requested": "cap_largeover", "status": "not_applied", "evidence": {first: ["cap_largeover"], second: None}}


def test_a_failing_later_page_keeps_earlier_rows_and_names_where_to_resume(client, tmp_path):
    client.add("https://finviz.com/screener?v=111&ft=4&f=sec_technology&r=1", screener_table(ROWS, total=40, current=1, page_values=(1, 21)))
    client.add("https://finviz.com/screener?v=111&ft=4&f=sec_technology&r=21", "", status=429, headers={"Retry-After": "30"})
    out = tmp_path / "rows.jsonl"
    result = client.one("screen", "run", "--filters", "sec_technology", "--pages", "2", "--out", str(out), code=8)
    assert result["status"] == "partial" and result["data"]["export"]["rows_written"] == 2 and len(out.read_text().splitlines()) == 2
    assert result["error"]["code"] == "access_restricted" and "21" in result["warnings"][0]
    assert result["next"] == "screen run --filters sec_technology --row 21 --pages 2 --out " + str(out) + " --append"
    plain = client.one("screen", "run", "--filters", "sec_technology", "--pages", "2", code=8)
    assert [r["ticker"] for r in plain["data"]["rows"]] == ["AAPL", "MSFT"] and "--row 21" in plain["next"]


def test_export_applies_the_selection_and_a_selection_that_matched_nothing_is_not_an_empty_source(client, tmp_path):
    client.add("https://finviz.com/screener?v=111&ft=4&r=1", screener_table(ROWS, total=2, page_values=(1,)))
    out = tmp_path / "rows.jsonl"
    result = client.one("screen", "run", "--fields", "ticker", "--limit", "1", "--out", str(out))
    assert [json.loads(line) for line in out.read_text().splitlines()] == [{"ticker": "AAPL", "observation_id": result["id"]}]
    assert result["coverage"] == {"received": 2, "matched": 2, "shown": 1, "start": 0, "cut": "limit", "source_total": 2}
    nothing = client.one("screen", "run", "--filter", "nomatch", "--out", str(tmp_path / "none.jsonl"))
    assert nothing["status"] == "ok" and nothing["data"]["export"]["rows_written"] == 0 and nothing["coverage"]["matched"] == 0


def test_missing_column_catalog_is_a_structure_change_not_an_empty_list(client):
    client.add("https://finviz.com/screener?v=152", '<html><body><script id="route-init-data" type="application/json">{}</script></body></html>')
    assert client.one("screen", "columns", code=6)["error"]["code"] == "structure_changed"


def test_aggregate_reports_a_later_page_returning_the_wrong_row(client):
    for start in (1, 21):
        client.add(f"https://finviz.com/screener?v=111&ft=4&r={start}", screener_table(ROWS, current=1, page_values=(1, 21)))
    result = client.one("screen", "run", "--pages", "2")
    first, second = result["source"]["pages"]
    assert result["conditions"]["row"] == {"requested": 1, "status": "not_applied", "evidence": {first: 1, second: 1}}
    assert client.one("read", second)["conditions"]["row"] == {"requested": 21, "status": "not_applied", "evidence": 1}
    assert len(result["data"]["rows"]) == 4  # the received rows are kept; the source is not silently deduplicated


def test_an_aggregate_and_each_page_read_again_without_fetching(client):
    for start, ticker in ((1, "FIRST"), (21, "SECOND")):
        client.add(f"https://finviz.com/screener?v=111&ft=4&r={start}", screener_table([(ticker, [ticker * 5, "2T"])], current=start, page_values=(1, 21)))
    result = client.one("screen", "run", "--pages", "2")
    client.responses.clear()
    ids = result["source"]["pages"]
    assert len(ids) == 2 and result["id"] not in ids
    again = client.one("read", result["id"], "--start", "1", "--limit", "1")
    assert again["data"]["rows"][0]["ticker"] == "SECOND" and again["data"]["rows"][0]["observation_id"] == ids[1]
    for page_id, ticker in zip(ids, ("FIRST", "SECOND")):
        assert client.one("read", page_id)["data"]["rows"][0]["ticker"] == ticker
        assert ticker in client.one("read", page_id, "--raw")["data"]


@pytest.mark.parametrize("body,status,code", [("wait", 429, "access_restricted"), ("<html>Changed layout</html>", 200, "structure_changed")])
def test_a_caught_later_page_failure_is_saved_with_its_original_error(client, body, status, code):
    client.add("https://finviz.com/screener?v=111&ft=4&r=1", screener_table(ROWS, page_values=(1, 21)))
    client.add("https://finviz.com/screener?v=111&ft=4&r=21", body, status=status, headers={"Retry-After": "30"})
    result = client.one("screen", "run", "--pages", "2", code=8)
    failed_id = re.search(r"observation ([a-f0-9]+)", " ".join(result["warnings"]))[1]
    saved = client.one("read", failed_id)
    assert any(code in w for w in saved["warnings"])
    assert client.one("read", failed_id, "--raw")["data"] == body
    assert client.one("read", result["id"], code=8)["status"] == "partial"  # reading a partial aggregate stays partial


def test_a_single_page_screen_that_returned_nothing_is_stored_as_empty(client):
    client.add("https://finviz.com/screener?v=111&ft=4&r=1", screener_table([], total=0, page_values=(1,)))
    assert client.one("screen", "run", code=7)["status"] == "empty"
    assert client.one("read", client.one("screen", "run", code=7)["id"], code=7)["status"] == "empty"


def test_tickers_screen_named_stocks_in_one_request_and_rows_outside_the_list_are_not_applied(client):
    three = [("AAPL", ["Apple Inc", "35.1"]), ("MSFT", ["Microsoft", "31.0"]), ("NVDA", ["NVIDIA", "40.2"])]
    page = screener_table(three, headers=("No.", "Ticker", "Company", "P/E"), total=3, page_values=(1,)).replace("<body>", '<body><input id="tickersInput" value="AAPL,MSFT,NVDA"/>')
    client.add("https://finviz.com/screener?v=121&ft=4&t=AAPL,MSFT,NVDA&r=1", page)
    result = client.one("screen", "run", "--tickers", "AAPL,MSFT,NVDA", "--view", "valuation")
    assert [r["ticker"] for r in result["data"]["rows"]] == ["AAPL", "MSFT", "NVDA"]
    assert result["conditions"]["tickers"] == {"requested": "AAPL,MSFT,NVDA", "status": "confirmed", "evidence": {"ticker_input": "AAPL,MSFT,NVDA", "rows_outside_the_list": [], "requested_but_not_returned": []}}
    client.add("https://finviz.com/screener?v=111&ft=4&t=AAPL,ZZZZ&r=1", screener_table(ROWS[:1], page_values=(1,)))
    assert client.one("screen", "run", "--tickers", "AAPL,ZZZZ")["conditions"]["tickers"]["evidence"]["requested_but_not_returned"] == ["ZZZZ"]
    client.add("https://finviz.com/screener?v=111&ft=4&t=AAPL&r=1", screener_table(ROWS, page_values=(1,)))
    assert client.one("screen", "run", "--tickers", "AAPL")["conditions"]["tickers"]["status"] == "not_applied"


def test_screener_sort_keys_are_the_order_controls_own(client):
    assert "-marketcap" in client.one("schema", "screen", "run")["data"]["arguments"]["--sort"]["choices"]
    assert client.one("screen", "run", "--sort", "bogus", code=2)["error"]["code"] == "invalid_argument"
