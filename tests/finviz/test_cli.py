import json


def test_lookup_preserves_identity_and_can_reread_original_response(client):
    source = {"results": [{"ticker": "A", "company": "Agilent Technologies", "exchange": "NYSE", "newField": 17}]}
    client.add("https://finviz.com/api/suggestions?input=Agilent", source)
    result = client.run("lookup", "Agilent")
    assert result["data"] == source
    assert result["source"]["url"].endswith("input=Agilent")
    assert result["source"]["received_complete"] is True
    saved = client.run("read", result["id"], "--pointer", "/data/results/0")
    assert saved["data"]["ticker"] == "A"
    raw = client.run("read", result["id"], "--raw")
    assert json.loads(raw["data"]) == source


def test_screener_keeps_ticker_identity_conditions_and_continuation(client):
    url = "https://finviz.com/screener?ft=4&v=152&f=sec_technology&c=1%2C6%2C7&r=21"
    page = """<select id="fs_sec"><option value="">Any</option><option selected value="technology">Technology</option></select>
    <script id="route-init-data" type="application/json">{"tableSettings":{"selectedColumns":["ticker","marketCap","PE"],"columnsMap":{"ticker":{"index":1},"marketCap":{"index":6},"PE":{"index":7}}}}</script>
    <table class="screener_table"><tr><th>Ticker</th><th>Market Cap</th><th>P/E</th></tr><tr><td><a href="/quote.ashx?t=NVDA"><span>N</span>NVDA</a></td><td>4.2T</td><td>32.1</td></tr></table>
    <a href="/screener?ft=4&v=152&f=sec_technology&c=1%2C6%2C7&r=41">Next</a>"""
    client.add(url, page)
    result = client.run("screen", "--filter", "sec_technology", "--view", "152", "--columns", "1,6,7", "--start", "21")
    assert result["data"]["tables"][0]["rows"][0]["ticker"] == "NVDA"
    assert len(result["data"]["tables"][0]["rows"][0]["cells"]) == 3
    assert result["conditions"]["f"]["status"] == "confirmed"
    assert result["conditions"]["r"]["status"] == "unverified"
    assert result["coverage"]["received"] == 1
    assert "r=41" in result["continuation"]
    assert result["coverage"]["exhaustive"] is False


def test_stock_preserves_duplicate_metrics_definitions_and_initial_data(client):
    page = """<h1>Agilent</h1><table class="snapshot-table2"><tr><td data-boxover-html="EPS estimate for next year">EPS next Y</td><td>6.74</td><td data-boxover-html="EPS growth next year">EPS next Y</td><td>8.75%</td></tr><tr><td data-boxover-html="Quarterly earnings growth (YoY)">EPS Q/Q</td><td>-</td></tr></table>
    <script id="route-init-data" type="application/json">{"currentExpiry":"2026-10-16","options":[{"volume":0,"iv":null,"newField":7}]}</script>"""
    client.add("https://finviz.com/stock?t=A&ty=oc&e=2026-10-16", page)
    result = client.run("stock", "A", "--section", "options", "--expiry", "2026-10-16")
    metrics = result["data"]["metrics"]
    assert [m["value"] for m in metrics] == ["6.74", "8.75%", "-"]
    assert metrics[1]["unit"] == "%"
    assert metrics[2]["definition"] == "Quarterly earnings growth (YoY)"
    assert result["conditions"]["e"]["status"] == "confirmed"
    assert result["data"]["initial"]["route-init-data"]["options"][0] == {"volume": 0, "iv": None, "newField": 7}


def test_statement_and_price_series_preserve_data_and_flag_misaligned_arrays(client):
    statement = {
        "currency": "USD",
        "data": {"Period": ["TTM", "2025FY", "2024FY", "2023FY"], "EPS": [1.25, 1.2, 0, None]},
    }
    client.add("https://finviz.com/api/statement?t=A&so=F&s=IA", statement)
    result = client.run("stock", "A", "--section", "income")
    assert result["data"] == statement
    bars = {
        "date": [20260910, 20260911],
        "open": [100, 101],
        "high": [103, 104],
        "low": [99, 100],
        "close": [102],
        "volume": [0, 20],
        "lastTime": 1789084800,
    }
    client.add("https://finviz.com/api/quote?instrument=stock&ticker=A&timeframe=d&barsCount=30", bars)
    result = client.run("prices", "A")
    assert result["status"] == "partial"
    assert result["data"] == bars
    assert result["errors"][0]["code"] == "array_alignment"
    assert client.run("read", result["id"], "--pointer", "/data/date")["data"] == [20260910, 20260911]


def test_calendar_continuation_uses_observed_page_and_retains_dates(client):
    url = "https://finviz.com/api/calendar/earnings?dateFrom=2026-09-15&page=1&sort=earningsDate"
    source = {
        "items": [
            {
                "ticker": "A",
                "earningsDate": "2026-09-15T08:30:00",
                "isEarningDateEstimate": True,
                "epsActual": None,
                "epsEstimate": 1.2,
            }
        ],
        "page": 1,
        "pageSize": 50,
        "totalItemsCount": 51,
        "totalPages": 2,
    }
    client.add(url, source)
    result = client.run("calendar", "earnings", "--date", "2026-09-15")
    assert result["data"] == source
    assert result["conditions"]["page"]["status"] == "confirmed"
    assert result["conditions"]["dateFrom"]["status"] == "unverified"
    assert result["coverage"]["source_total"] == 51
    assert result["continuation"].endswith("page=2&sort=earningsDate")


def test_market_queries_keep_native_fields_and_can_open_the_source_url(client):
    cases = [
        (["groups"], "https://finviz.com/api/groups_perf?g=sector&v=210&o=name&st=d1"),
        (["market", "forex"], "https://finviz.com/api/forex_all?timeframe=d"),
        (["market", "crypto", "--performance"], "https://finviz.com/api/crypto_perf"),
        (["news", "--pulse", "284262"], "https://finviz.com/api/stocks-why-moving/by-id/284262"),
        (
            ["map", "--performance-only", "--type", "geo", "--period", "w1"],
            "https://finviz.com/api/map_perf?t=geo&st=w1",
        ),
    ]
    for args, url in cases:
        source = {"providerField": {"value": 0, "period": "source period"}, "unknownField": None}
        client.add(url, source)
        result = client.run(*args)
        assert result["data"] == source
        assert client.run("open", url)["data"] == source


def test_news_articles_and_insider_rows_keep_links_and_source_roles(client):
    client.add(
        "https://finviz.com/news?v=6",
        """<table class="styled-table-new"><tr class="market-pulse-row-clickable" data-wiim-trigger="284262"><td>Sep 15</td><td><a href="/stock?t=A">A</a></td><td>Why A moved</td></tr></table>""",
    )
    result = client.run("news", "--view", "6")
    assert result["data"]["tables"][0]["rows"][0]["pulse_id"] == "284262"
    client.add(
        "https://finviz.com/news/123/source-story",
        """<h1>Source story</h1><div class="text-justify"><p>Original paragraph.</p><p>Second paragraph with <a href="https://www.sec.gov/Archives/example.htm">filing</a>.</p></div>""",
    )
    article = client.run("news", "--url", "https://finviz.com/news/123/source-story")
    assert article["data"]["article"]["paragraphs"] == ["Original paragraph.", "Second paragraph with filing ."]
    assert article["data"]["article"]["links"][0]["url"].startswith("https://www.sec.gov/")
    client.add(
        "https://finviz.com/insidertrading?tc=7",
        """<table id="insider-table"><tr><th>Ticker</th><th>Transaction</th></tr><tr><td><a href="stock?t=A">A</a></td><td><a href="https://www.sec.gov/Archives/form4.xml">Buy 0 shares</a></td></tr></table>""",
    )
    insiders = client.run("insiders")
    assert insiders["data"]["tables"][0]["rows"][0]["ticker"] == "A"
    assert insiders["data"]["tables"][0]["rows"][0]["cells"][1] == "Buy 0 shares"


def test_catalog_exposes_current_choices_and_schema_describes_saved_results(client):
    client.add(
        "https://finviz.com/screener?ft=4&v=151",
        """<select id="fs_theme" data-label="Theme"><option value="newtheme">New theme</option></select><script id="route-init-data">{"tableSettings":{"availableColumns":["ticker","newColumn"],"columnsMap":{"newColumn":{"index":999,"label":"New column"}}}}</script>""",
    )
    result = client.run("catalog", "screen")
    assert result["data"]["controls"][0]["options"][0]["value"] == "newtheme"
    assert result["data"]["initial"]["route-init-data"]["tableSettings"]["columnsMap"]["newColumn"]["index"] == 999
    schema = client.run("schema")
    assert "unverified" in json.dumps(schema)
    info = client.run("inspect", result["id"])
    assert "/data/controls" in [n["pointer"] for n in info["data"]]
    assert client.run("doctor")["status"] == "ok"


def test_collection_retries_failed_page_and_refuses_modified_export(client, tmp_path):
    first_url = "https://finviz.com/api/calendar/earnings?page=1"
    second_url = "https://finviz.com/api/calendar/earnings?page=2"
    row = {"ticker": "A", "earningsDate": "2026-09-15"}
    client.add(first_url, {"items": [row], "page": 1, "totalPages": 2, "totalItemsCount": 2})
    first = client.run("open", first_url)
    client.add(second_url, "temporarily unavailable", status=503)
    collection = client.run("collect", first["id"])
    assert collection["status"] == "partial"
    assert collection["data"]["next_url"] == second_url
    client.add(
        second_url,
        {
            "items": [row, {"ticker": "B", "earningsDate": "2026-09-15"}],
            "page": 2,
            "totalPages": 2,
            "totalItemsCount": 2,
        },
    )
    target = tmp_path / "results.jsonl"
    done = client.run("collect", collection["id"], "--out", str(target))
    assert done["data"]["unique_items"] == 2
    assert done["data"]["duplicates"] == 1
    assert done["data"]["next_url"] is None
    assert len(target.read_text().splitlines()) == 2
    target.write_text("user modification\n")
    error = client.run("collect", collection["id"], "--out", str(target), code=1)
    assert error["errors"][0]["code"] == "export_conflict"
    assert target.read_text() == "user modification\n"


def test_map_uses_type_specific_loader_and_runtime_hash_without_executing_js(client):
    client.add("https://finviz.com/api/map_perf?t=geo&st=d1", {"nodes": {"A": 1.2}, "subtype": "d1"})
    client.add(
        "https://finviz.com/map?t=geo",
        """<script src="/assets/dist/runtime.v1.current.js"></script><script src="/assets/dist/999.v1.loader.js"></script><script src="/assets/dist/map.v1.entry.js"></script>""",
    )
    client.add(
        "https://finviz.com/assets/dist/999.v1.loader.js",
        "function choose(t){switch(t){case x.IZ.World:return o(n.e(6207).then(n.t.bind(n,68379,23)));default:return o(n.e(8119).then(n.t.bind(n,10163,23)))}}",
    )
    client.add(
        "https://finviz.com/assets/dist/runtime.v1.current.js",
        'n.u=e=>e+".v1."+{6207:"worldhash",8119:"wronghash"}[e]+".js"',
    )
    client.add(
        "https://finviz.com/assets/dist/6207.v1.worldhash.js",
        'self.webpackChunk.push([[6207],{68379(e){e.exports={name:"Root",children:[{name:"Japan",children:[{name:"A",value:42}]}]}}}]);throw new Error("must never execute");',
    )
    result = client.run("map", "--type", "geo")
    assert result["data"]["performance"]["nodes"]["A"] == 1.2
    assert result["data"]["classification"] is not None, result["errors"]
    assert result["data"]["classification"]["children"][0]["name"] == "Japan"
    assert result["data"]["classification"]["children"][0]["children"][0]["value"] == 42
    assert result["data"]["classification_source"]["url"].endswith("6207.v1.worldhash.js")


def test_transport_and_parse_failures_keep_original_response_and_reject_redirect_escape(client):
    url = "https://finviz.com/api/statement?t=A&s=IA"
    client.add(url, "{broken json")
    broken = client.run("open", url, code=1)
    assert broken["source"]["received_complete"] is True
    assert client.run("read", broken["id"], "--raw")["data"] == "{broken json"
    client.add(url, "partial bytes", exit=28)
    broken = client.run("open", url, code=1)
    assert broken["source"]["received_complete"] is False
    assert client.run("read", broken["id"], "--raw")["data"] == "partial bytes"
    client.add(url, "blocked", status=429, headers={"Retry-After": "120"})
    blocked = client.run("open", url, code=1)
    assert blocked["source"]["headers"]["retry-after"] == "120"
    assert blocked["errors"][0]["code"] == "access_restricted"
    client.add(url, "redirect", status=302, headers={"Location": "https://example.com/steal"})
    redirect = client.run("open", url, code=1)
    assert redirect["errors"][0]["code"] == "unsupported_url"
    for forbidden in [
        "http://finviz.com/stock?t=A",
        "https://finviz.com:443/stock?t=A",
        "https://finviz.com/register",
        "https://finviz.com/portfolio.ashx",
        "https://www.sec.gov/Archives/a.html",
    ]:
        assert client.run("open", forbidden, code=1)["errors"]


def test_large_output_is_bounded_and_saved_fields_remain_readable(client):
    source = {"items": [{"ticker": str(i), "description": "x" * 1000} for i in range(150)]}
    client.add("https://finviz.com/api/suggestions?input=many", source)
    result = client.run("lookup", "many")
    assert len(json.dumps(result)) < 20000
    assert result["presentation"]["truncated"] is True
    item = client.run("read", result["id"], "--pointer", "/data/items/149")
    assert item["data"]["ticker"] == "149"
    assert len(item["data"]["description"]) == 1000


def test_default_calendar_uses_source_default_date_instead_of_guessing(client):
    client.add(
        "https://finviz.com/calendar/earnings?page=1&sort=earningsDate",
        """<script id="route-init-data">{"data":{"initialDateFrom":"2026-09-14","initialSort":"earningsDate","initialPage":1,"entries":{"items":[],"page":1,"totalPages":1,"totalItemsCount":0}}}</script>""",
    )
    result = client.run("calendar", "earnings")
    assert result["data"]["initial"]["route-init-data"]["data"]["initialDateFrom"] == "2026-09-14"
    assert result["coverage"]["received"] == 0
    assert result["coverage"]["pagination_end"] is True


def test_map_catalog_returns_current_navigation_without_requiring_visual_data(client):
    client.add(
        "https://finviz.com/map",
        """<div><a href="/map?t=sec_all">Full stock market</a><a href="/map?t=geo">World</a><a href="/bubbles?idx=sp500">Bubbles</a></div>""",
    )
    result = client.run("catalog", "map")
    assert any(x["url"] == "https://finviz.com/map?t=geo" for x in result["data"]["navigation"])


def test_custom_columns_confirmed_from_source_and_missing_filter_is_not_applied(client):
    client.add(
        "https://finviz.com/screener?ft=4&v=152&f=sec_technology&c=1%2C6&r=1",
        """<select id="fs_sec"><option selected value="">Any</option><option value="technology">Technology</option></select><script id="route-init-data">{"tableSettings":{"selectedColumns":["ticker","marketCap"],"columnsMap":{"ticker":{"index":1},"marketCap":{"index":6}}}}</script><table class="screener_table"><tr><th>Ticker</th><th>Market cap</th></tr></table>""",
    )
    result = client.run("screen", "--view", "152", "--filter", "sec_technology", "--columns", "1,6")
    assert result["conditions"]["c"]["status"] == "confirmed"
    assert result["conditions"]["f"]["status"] == "not_applied"
    assert result["coverage"]["received"] == 0


def test_invalid_pointer_and_negative_read_window_are_errors(client):
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A"}])
    first = client.run("lookup", "A")
    assert client.run("read", first["id"], "--pointer", "data", code=1)["errors"]
    assert client.run("read", first["id"], "--pointer", "/data/-1", code=1)["errors"]
    assert client.run("read", first["id"], "--start", "-1", code=1)["errors"]


def test_redirect_does_not_erase_requested_filter(client):
    client.add("https://finviz.com/screener?f=sec_technology", "", status=302, headers={"Location": "/screener"})
    client.add(
        "https://finviz.com/screener",
        """<select id="fs_sec"><option selected value="">Any</option></select><table class="screener_table"><tr><th>Ticker</th></tr></table>""",
    )
    result = client.run("open", "https://finviz.com/screener?f=sec_technology")
    assert result["conditions"]["f"]["requested"] == "sec_technology"
    assert result["conditions"]["f"]["status"] == "not_applied"
    assert result["source"]["redirects"][0]["id"]


def test_export_keeps_table_headers_and_partial_diagnostics(client, tmp_path):
    client.add(
        "https://finviz.com/screener",
        """<table class="screener_table"><tr><th>Ticker</th><th>Market Cap</th><th>P/E</th></tr><tr><td><a href="stock?t=A">A</a></td><td>42</td><td>17</td></tr></table>""",
    )
    first = client.run("open", "https://finviz.com/screener")
    target = tmp_path / "table.jsonl"
    client.run("collect", first["id"], "--out", str(target))
    exported = json.loads(target.read_text())
    assert exported["data"]["tables"][0]["headers"] == ["Ticker", "Market Cap", "P/E"]
    client.add("https://finviz.com/api/quote?ticker=A", {"date": [1, 2], "close": [5], "currency": "USD"})
    partial = client.run("open", "https://finviz.com/api/quote?ticker=A")
    target = tmp_path / "partial.jsonl"
    collection = client.run("collect", partial["id"], "--out", str(target))
    assert collection["errors"][0]["code"] == "array_alignment"
    exported = json.loads(target.read_text())
    assert exported["status"] == "partial"
    assert exported["errors"][0]["code"] == "array_alignment"
    assert exported["data"]["currency"] == "USD"


def test_catalog_combines_custom_columns_with_separate_filter_controls(client):
    client.add(
        "https://finviz.com/screener?ft=4&v=151",
        """<script id="route-init-data">{"tableSettings":{"columnsMap":{"ticker":{"index":1}}}}</script>""",
    )
    client.add(
        "https://finviz.com/screener?ft=4",
        """<select id="fs_sec"><option value="technology">Technology</option></select>""",
    )
    result = client.run("catalog", "screen")
    assert result["data"]["controls"][0]["id"] == "fs_sec"
    assert result["data"]["initial"]["route-init-data"]["tableSettings"]["columnsMap"]["ticker"]["index"] == 1
    assert len(result["dependencies"]) == 2


def test_read_slice_retains_source_conditions_and_partial_warning(client):
    client.add("https://finviz.com/api/quote?ticker=A", {"date": [1, 2], "close": [5]})
    first = client.run("open", "https://finviz.com/api/quote?ticker=A")
    selected = client.run("read", first["id"], "--pointer", "/data/close")
    assert selected["data"] == [5]
    assert selected["observation_status"] == "partial"
    assert selected["source"]["url"] == "https://finviz.com/api/quote?ticker=A"
    assert selected["conditions"]["ticker"]["requested"] == "A"
    assert selected["errors"][0]["code"] == "array_alignment"


def test_duplicate_json_keys_are_not_silently_collapsed(client):
    client.add("https://finviz.com/api/statement?t=A", '{"data":{"EPS":1,"EPS":2}}')
    result = client.run("open", "https://finviz.com/api/statement?t=A", code=1)
    assert result["errors"][0]["code"] == "parse_error"
    assert client.run("read", result["id"], "--raw")["data"] == '{"data":{"EPS":1,"EPS":2}}'


def test_unexpected_extraction_failure_still_preserves_received_bytes(client):
    source = "[" * 1500 + "0" + "]" * 1500
    client.add("https://finviz.com/api/suggestions?input=deep", source)
    result = client.run("lookup", "deep", code=None)
    assert result["status"] in ("error", "partial")
    assert result["errors"][0]["code"] == "parse_error"
    assert client.run("read", result["id"], "--raw", "--full")["data"] == source
