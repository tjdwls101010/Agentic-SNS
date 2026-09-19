import json

import pytest

from pages import MAP_CHUNK, MAP_LOADER, MAP_RUNTIME, article_page, calendar_page, groups_page, insiders_page, map_page, news_page, pulse_page


def test_groups_options_list_group_and_sort_identifiers(client):
    client.add("https://finviz.com/groups", groups_page())
    data = client.one("groups", "options")["data"]
    assert data["groups"] == [{"group": "sector", "label": "Sector"}, {"group": "industry", "label": "Industry"}, {"group": "industry/basicmaterials", "label": "Industry (Basic Materials)"}, {"group": "country", "label": "Country"}, {"group": "capitalization", "label": "Capitalization"}]
    assert data["sorts"] == [{"key": "name", "label": "Name"}, {"key": "marketcap", "label": "Market Capitalization"}]


def test_groups_table_rows_carry_the_screener_filter_and_confirm_group_and_sort(client):
    client.add("https://finviz.com/groups?g=sector&v=110", groups_page())
    result = client.one("groups", "table")
    assert result["data"][0] == {"No.": "1", "Name": "Basic Materials", "Stocks": "291", "Market Cap": "2882.47B", "Dividend": "1.93%", "filter": "sec_basicmaterials"}
    assert result["conditions"]["group"] == {"requested": "sector", "status": "confirmed", "evidence": "sector"}
    assert "sort" not in result["conditions"]
    client.add("https://finviz.com/groups?g=industry&sg=basicmaterials&v=120&o=-marketcap", groups_page(selected_group=("groups?g=industry&v=110&o=name&st=d1", "groups?g=industry&sg=basicmaterials&v=110&o=name&st=d1")))
    result = client.one("groups", "table", "--group", "industry/basicmaterials", "--view", "valuation", "--sort=-marketcap")
    assert result["conditions"]["group"]["status"] == "confirmed" and result["conditions"]["sort"]["status"] == "not_applied"


def test_groups_performance_returns_source_records_for_every_period(client):
    perf = [{"ticker": "basicmaterials", "label": "Basic Materials", "group": "", "screenerUrl": "screener?f=sec_basicmaterials&v=211", "perfT": -0.83, "perfW": -5.58, "perfM": -1.66, "perfQ": -3.24, "perfH": 1.65, "perfY": 24.2, "perfYtd": 13.37}]
    client.add("https://finviz.com/api/groups_perf?g=sector", perf)
    assert client.one("groups", "performance")["data"] == perf
    client.add("https://finviz.com/api/groups_perf?g=industry&sg=energy", perf)
    assert client.one("groups", "performance", "--group", "industry/energy")["data"] == perf


def test_market_quotes_performance_and_bubbles_keep_source_shapes(client):
    quotes = {"6A": {"label": "AUD", "ticker": "6A", "last": 0.71145, "change": -0.29}, "ES": {"label": "S&P 500", "ticker": "ES", "last": 6600.0, "change": 0.1}}
    client.add("https://finviz.com/api/futures_all?timeframe=d", quotes)
    result = client.one("market", "quotes", "futures", "--filter", "S&P")
    assert result["data"] == {"ES": quotes["ES"]} and result["coverage"]["received"] == 2
    client.add("https://finviz.com/api/forex_perf", {"USD": 0.0, "AUD": -0.19})
    assert client.one("market", "performance", "forex")["data"] == {"USD": 0.0, "AUD": -0.19}
    bubbles = [{"ticker": "CF", "company": "CF Industries", "x": 1.0, "y": 1.09, "size": 2.0e10, "color": "Basic Materials", "isETF": False}]
    client.add("https://finviz.com/api/bubbles?x=sector&y=lastChange&size=marketCap&color=sector&idx=dji", bubbles)
    assert client.one("market", "bubbles")["data"] == bubbles


def test_quotes_leave_out_the_rendering_sparklines_until_they_are_asked_for(client):
    """Each instrument carries a 300-point sparkline that is 90% of the response; the quote itself is what the screen shows."""
    quotes = {"ES": {"label": "S&P 500", "last": 6600.0, "sparkline": [1, 2, 3], "sparklineDateChanges": ["a"], "change": 0.1}}
    client.add("https://finviz.com/api/futures_all?timeframe=d", quotes)
    assert client.one("market", "quotes", "futures")["data"] == {"ES": {"label": "S&P 500", "last": 6600.0, "change": 0.1}}
    assert client.one("market", "quotes", "futures", "--sparkline")["data"] == quotes


def test_market_map_defaults_to_performance_and_takes_the_classification_tree_on_request(client):
    """Resolving the tree costs five more requests and is 85% of the response; the map's numbers are the answer to a performance question."""
    client.add("https://finviz.com/api/map_perf?t=sec&st=d1", {"nodes": {"AAPL": 1.0}, "subtype": "d1", "version": 15})
    default = client.one("market", "map")
    assert default["data"]["performance"] == {"AAPL": 1.0} and default["data"]["classification"] is None
    assert "dependencies" not in default["source"]


def test_bubbles_default_to_a_named_index_the_budget_fits(client):
    """An unknown idx is not refused by the source, it silently returns all 5,906 stocks, so the universe is a closed choice."""
    rows = [{"ticker": "AAPL", "x": 1.0, "y": 2.0, "size": 3.0, "color": "Technology", "isETF": False}]
    client.add("https://finviz.com/api/bubbles?x=sector&y=lastChange&size=marketCap&color=sector&idx=dji", rows)
    result = client.one("market", "bubbles")
    assert result["data"] == rows and result["request"]["index"] == "dji"
    refused = client.one("market", "bubbles", "--index", "nasdaq", code=2)
    assert refused["error"]["code"] == "invalid_argument" and "sp500" in refused["error"]["message"]


def test_market_map_resolves_classification_from_the_page_assets_and_degrades_to_partial(client):
    perf = {"nodes": {"RY": 1.2, "TD": -0.4}, "additional": {}, "subtype": "d1", "version": 15, "hash": "X"}
    client.add("https://finviz.com/api/map_perf?t=geo&st=d1", perf)
    client.add("https://finviz.com/map?t=geo", map_page())
    client.add("https://finviz.com/assets/dist-legacy/map.v1.aaaa1111.js", "/* legacy loader is in a preceding bundle */")
    client.add("https://finviz.com/assets/dist-legacy/1378.v1.61170fe2.js", MAP_LOADER)
    client.add("https://finviz.com/assets/dist-legacy/runtime.v1.22f44280.js", MAP_RUNTIME)
    client.add("https://finviz.com/assets/dist-legacy/62.v1.bbb222.js", MAP_CHUNK)
    result = client.one("market", "map", "--type", "geo", "--classification")
    assert result["data"]["performance"] == perf["nodes"] and result["data"]["period"] == "d1"
    assert result["data"]["classification"]["children"][0]["children"][0]["children"][0] == {"name": "RY", "description": "Royal Bank Of Canada", "value": 294647}
    assert result["data"]["classification_source"].endswith("62.v1.bbb222.js")
    only = client.one("market", "map", "--type", "geo")
    assert only["data"]["classification"] is None and "source" not in only["data"] or only["data"].get("classification_source") is None
    client.add("https://finviz.com/assets/dist-legacy/62.v1.bbb222.js", "module.exports={name:'Other'}")
    degraded = client.one("market", "map", "--type", "geo", "--classification", code=8)
    assert degraded["status"] == "partial" and degraded["data"]["performance"] == perf["nodes"] and degraded["data"]["classification"] is None
    assert degraded["error"]["code"] == "asset_structure"
    failed_asset = client.one("read", degraded["source"]["dependencies"][-1])["data"]
    assert failed_asset["status"] == "error" and failed_asset["error"]["code"] == "asset_structure"
    replayed = client.one("read", degraded["id"], code=8)  # a recovery path must not launder the gap it is recovering from
    assert replayed["status"] == "partial"


@pytest.mark.parametrize("map_type,chunk,label", [("geo", 6207, "World"), ("sec_all", 7791, "All stocks"), ("sec", 8119, "S&P 500")])
def test_map_loads_the_requested_universe_from_the_current_entry_script(client, map_type, chunk, label):
    # Recorded 2026-09-16: map.v1.67823970.js module 30092; unrelated branches omitted.
    loader = 'function o(e){switch(e){case i.IZ.World:return a(n.e(6207).then(n.t.bind(n,68379,23)));case i.IZ.SectorFull:return a(n.e(7791).then(n.t.bind(n,20375,23)));default:return a(n.e(8119).then(n.t.bind(n,10163,23)))}}'
    loader = 'switch(layout){case i.IZ.World:render();break;default:return n.e(9999)};' + loader
    client.add(f"https://finviz.com/api/map_perf?t={map_type}&st=d1", {"nodes": {"TEST": 1.2}, "subtype": "d1"})
    client.add(f"https://finviz.com/map?t={map_type}", map_page())
    client.add("https://finviz.com/assets/dist-legacy/map.v1.aaaa1111.js", loader)
    client.add("https://finviz.com/assets/dist-legacy/1378.v1.61170fe2.js", "/* no map loader */")
    client.add("https://finviz.com/assets/dist-legacy/4740.v1.b05b832c.js", "/* no map loader */")
    client.add("https://finviz.com/assets/dist-legacy/runtime.v1.22f44280.js", 'r.u=e=>e+".v1."+{6207:"world-test",7791:"full-test",8119:"sector-test"}[e]+".js"')
    suffix = {6207: "world-test", 7791: "full-test", 8119: "sector-test"}[chunk]
    url = f"https://finviz.com/assets/dist-legacy/{chunk}.v1.{suffix}.js"
    tree = {"name": "Root", "children": [{"name": label, "children": [{"name": "TEST", "value": 123, "newField": "kept"}]}]}
    client.add(url, "module.exports=" + json.dumps(tree))
    result = client.one("market", "map", "--type", map_type, "--classification")
    assert result["data"]["classification"] == tree and result["data"]["classification_source"] == url
    assert result["data"]["performance"] == {"TEST": 1.2}
    client.add("https://finviz.com/assets/dist-legacy/map.v1.aaaa1111.js", loader + loader.replace(str(chunk), "9999"))
    ambiguous = client.one("market", "map", "--type", map_type, "--classification", code=8)
    assert ambiguous["error"]["code"] == "asset_structure" and ambiguous["data"]["classification"] is None
    assert ambiguous["data"]["performance"] == {"TEST": 1.2}
    client.add("https://finviz.com/assets/dist-legacy/map.v1.aaaa1111.js", loader)
    client.add(url, "a.exports=" + json.dumps(tree) + ";b.exports=" + json.dumps(tree))
    roots = client.one("market", "map", "--type", map_type, "--classification", code=8)
    assert roots["error"]["code"] == "asset_structure" and "found 2" in roots["error"]["message"]
    assert roots["data"]["classification"] is None and roots["data"]["performance"] == {"TEST": 1.2}


def test_map_does_not_substitute_the_default_for_a_missing_requested_type(client):
    client.add("https://finviz.com/api/map_perf?t=cap&st=d1", {"nodes": {"A": 2}, "subtype": "d1"})
    client.add("https://finviz.com/map?t=cap", map_page())
    client.add("https://finviz.com/assets/dist-legacy/map.v1.aaaa1111.js", MAP_LOADER)
    for name in ("1378.v1.61170fe2.js", "4740.v1.b05b832c.js"):
        client.add("https://finviz.com/assets/dist-legacy/" + name, "/* no map loader */")
    result = client.one("market", "map", "--type", "cap", "--classification", code=8)
    assert result["error"]["code"] == "asset_structure" and "no case for MarketCap" in result["error"]["message"]
    assert result["data"]["classification"] is None and result["data"]["performance"] == {"A": 2}


def test_calendar_date_is_judged_by_the_sources_own_start_date_not_by_the_returned_items(client):
    """A source that ignores dateFrom still returns items on or after it; only the page's own initialDateFrom separates applied from ignored."""
    entries = {"items": [{"ticker": "MU", "earningsDate": "2026-09-25T08:30:00"}], "page": 1, "totalPages": 1, "totalItemsCount": 1}
    ignored = {"data": {"initialDateFrom": "2026-09-18", "initialSort": "earningsDate", "initialPage": 1, "entries": entries}}
    client.add("https://finviz.com/calendar/earnings?dateFrom=2026-09-01", calendar_page(ignored))
    result = client.one("calendar", "earnings", "--date", "2026-09-01")
    assert result["conditions"]["date"] == {"requested": "2026-09-01", "status": "not_applied", "evidence": {"source_date_from": "2026-09-18"}}
    assert result["data"]["date_from"] == "2026-09-18"
    applied = {"data": {"initialDateFrom": "2026-09-01", "initialSort": "-earningsDate", "initialPage": 1, "entries": entries}}
    client.add("https://finviz.com/calendar/earnings?dateFrom=2026-09-01&sort=-earningsDate", calendar_page(applied))
    result = client.one("calendar", "earnings", "--date", "2026-09-01", "--sort=-earningsDate")
    assert result["conditions"]["date"] == {"requested": "2026-09-01", "status": "confirmed", "evidence": {"source_date_from": "2026-09-01"}}
    assert result["conditions"]["sort"] == {"requested": "-earningsDate", "status": "unverified", "evidence": {"source_sort": "-earningsDate"}}
    client.add("https://finviz.com/api/calendar/earnings?dateFrom=2026-09-01&page=2&sort=earningsDate", dict(entries, page=2, totalPages=3))
    paged = client.one("calendar", "earnings", "--date", "2026-09-01", "--page", "2")
    assert paged["conditions"]["date"] == {"requested": "2026-09-01", "status": "unverified", "evidence": None}
    assert paged["conditions"]["page"]["status"] == "confirmed"
    assert "date_from" not in paged["data"] or paged["data"]["date_from"] is None


def test_calendar_pages_use_source_entries_and_confirm_date_page_and_sort(client):
    entries = {"items": [{"ticker": "BIOX", "earningsDate": "2026-09-15T08:30:00", "isEarningDateEstimate": False, "epsEstimate": 0.07, "epsActual": None}], "page": 1, "pageSize": 100, "totalItemsCount": 5, "totalPages": 1}
    client.add("https://finviz.com/calendar/earnings", calendar_page({"data": {"initialDateFrom": "2026-09-15", "initialSort": "earningsDate", "initialPage": 1, "entries": entries}, "version": 3}))
    result = client.one("calendar", "earnings")
    assert result["data"] == {"date_from": "2026-09-15", "items": entries["items"]}
    assert result["coverage"] == {"received": 1, "shown": 1, "source_total": 5, "exhaustive": False, "pagination_end": True}
    assert "continuation" not in result
    later = [{"ticker": "ISPR", "earningsDate": "2026-09-21T08:30:00", "epsEstimate": 0.01}]
    client.add("https://finviz.com/api/calendar/earnings?dateFrom=2026-09-20&page=2&sort=earningsDate", dict(entries, items=later, page=2, totalPages=3))
    result = client.one("calendar", "earnings", "--date", "2026-09-20", "--page", "2")
    assert result["data"] == {"date_from": None, "items": later}
    assert result["conditions"] == {"date": {"requested": "2026-09-20", "status": "unverified", "evidence": None}, "page": {"requested": 2, "status": "confirmed", "evidence": 2}}
    assert result["continuation"] == {"page": 3}
    economic = [{"calendarId": 1, "event": "Monthly Budget Statement", "date": "2026-09-11T14:00:00", "actual": "-$167B", "forecast": "-$404B"}]
    client.add("https://finviz.com/calendar/economic", calendar_page({"data": {"initialDateFrom": "2026-09-14", "entries": economic}}))
    result = client.one("calendar", "economic")
    assert result["data"]["items"] == economic and result["coverage"]["received"] == 1
    client.add("https://finviz.com/calendar/economic?dateFrom=2026-09-01", calendar_page({"data": {"initialDateFrom": "2026-09-01", "entries": economic}}))
    result = client.one("calendar", "economic", "--date", "2026-09-01")
    assert result["data"]["items"] == economic and result["conditions"]["date"]["status"] == "confirmed"
    client.add("https://finviz.com/calendar/dividends", calendar_page({"data": {"initialDateFrom": "2026-09-15", "initialPage": 1, "entries": dict(entries, totalPages=7, totalItemsCount=304)}}))
    client.add("https://finviz.com/api/calendar/dividends?dateFrom=2026-09-15&page=2", dict(entries, items=[{"ticker": "CX", "exdate": "2026-09-15"}], page=2, totalPages=7, totalItemsCount=304))
    result = client.one("calendar", "dividends", "--page", "2")
    assert result["data"]["items"] == [{"ticker": "CX", "exdate": "2026-09-15"}] and result["data"]["date_from"] == "2026-09-15"
    assert result["coverage"]["source_total"] == 304 and result["continuation"] == {"page": 3} and result["conditions"]["page"]["status"] == "confirmed"
    client.add("https://finviz.com/calendar/earnings/season-preview", calendar_page({"data": {"initialDateFrom": "2026-09-14", "entries": [{"date": "2026-09-30", "ticker": "MU"}], "totalsPerDay": {"2026-09-30": 3}, "totalCount": 64}}))
    result = client.one("calendar", "season")
    assert result["data"]["items"] == [{"date": "2026-09-30", "ticker": "MU"}] and result["data"]["totals_per_day"] == {"2026-09-30": 3} and result["coverage"]["source_total"] == 64


def test_each_calendar_takes_only_the_arguments_it_accepts(client):
    """One shared argument list made season advertise --date, --page and --sort and then refuse all three."""
    season = client.raw("calendar", "season", "--help", code=0).stdout
    assert "--date" not in season and "--page" not in season and "--sort" not in season
    economic = client.raw("calendar", "economic", "--help", code=0).stdout
    assert "--date" in economic and "--sort" in economic and "--page" not in economic
    earnings = client.raw("calendar", "earnings", "--help", code=0).stdout
    assert "--date" in earnings and "--page" in earnings and "--sort" in earnings
    refused = client.one("calendar", "season", "--date", "2026-09-01", code=2)
    assert refused["error"]["code"] == "invalid_argument"
    assert client.one("calendar", "economic", "--page", "2", code=2)["error"]["code"] == "invalid_argument"
    assert "rejected by" not in " ".join(str(a) for a in client.one("schema", "calendar", "earnings")["data"]["arguments"].values())


def test_inspect_lists_the_structure_the_model_cannot_know_in_advance(client):
    client.add("https://finviz.com/api/suggestions?input=A", [{"ticker": "A", "nested": {"deep": [1]}}])
    saved = client.one("search", "A")["id"]
    pointers = [entry["pointer"] for entry in client.one("inspect", saved)["data"]]
    assert "/data" in pointers and "/data/0/nested" in pointers
    assert not [p for p in pointers if p in ("/", "/id", "/observed_at", "/status", "/source/url", "/source/http_status")]


def test_news_headlines_by_time_by_source_and_stock_badges(client):
    client.add("https://finviz.com/news", news_page())
    result = client.one("news", "headlines")
    assert result["data"] == [{"time": "06:56AM", "title": "Stocks Fall as Oil Rally", "url": "https://www.bloomberg.com/a", "source": "Bloomberg", "section": "News", "tickers": []}, {"time": "06:30AM", "title": "Paramount Dividend Analysis", "url": "https://finance.yahoo.com/b", "source": "GuruFocus.com", "section": "Blogs", "tickers": ["PSKY"]}]
    client.add("https://finviz.com/news?v=2", news_page(by_source=True))
    by_source = client.one("news", "headlines", "--kind", "by-source")["data"]
    assert [i["source"] for i in by_source] == ["Bloomberg", "GuruFocus.com"] and by_source[0]["section"] == "Bloomberg"
    client.add("https://finviz.com/news?v=3", news_page(sections=()))
    stocks = client.one("news", "headlines", "--kind", "stocks", "--filter", "PSKY")["data"]
    assert stocks[0]["tickers"] == ["PSKY"] and stocks[0]["section"] is None


def test_headline_and_calendar_defaults_are_one_screenful_and_keep_every_section(client):
    """The page groups headlines into News and Blogs; a prefix cut of the flattened list would silently drop a whole section."""
    items = [("0%d:00AM" % (i % 10), "Headline %d" % i, "https://example.com/%d" % i, "Source", ()) for i in range(60)]
    client.add("https://finviz.com/news", news_page(items=tuple(items)))
    result = client.one("news", "headlines")
    assert result["coverage"] == {"received": 60, "shown": 40, "exhaustive": False}
    assert {i["section"] for i in result["data"]} == {"News", "Blogs"}
    assert len([i for i in result["data"] if i["section"] == "Blogs"]) == 20
    assert [i["title"] for i in result["data"]][:2] == ["Headline 0", "Headline 1"]
    events = [{"calendarId": n, "event": "Event %d" % n, "date": "2026-09-11T14:00:00"} for n in range(60)]
    client.add("https://finviz.com/calendar/economic", calendar_page({"data": {"initialDateFrom": "2026-09-14", "entries": events}}))
    economic = client.one("calendar", "economic")
    assert economic["coverage"]["received"] == 60 and economic["coverage"]["shown"] == 40
    rows = tuple(("T%d" % n, "Owner %d" % n, str(n), "Director", "Sep 12 '26", "Sale", "42.10", "10,000", "421,000", "50,000", "Sep 14 09:55 PM", "http://www.sec.gov/x.xml") for n in range(40))
    client.add("https://finviz.com/insidertrading?tc=7", insiders_page(rows=rows))
    trades = client.one("insiders", "trades")
    assert trades["coverage"]["received"] == 40 and trades["coverage"]["shown"] == 20


def test_a_default_window_narrows_the_answer_without_narrowing_the_search_or_the_observation(client):
    """A window applied before --filter would answer "not in the news" from a result that holds the headline."""
    items = [("0%d:00AM" % (i % 10), "Headline %d" % i, "https://example.com/%d" % i, "Source", ()) for i in range(60)]
    client.add("https://finviz.com/news", news_page(items=tuple(items)))
    default = client.one("news", "headlines")
    assert default["coverage"] == {"received": 60, "shown": 40, "exhaustive": False}
    found = client.one("news", "headlines", "--filter", "Headline 55")
    assert [i["title"] for i in found["data"]] == ["Headline 55"] and found["coverage"]["received"] == 60
    beyond = client.one("read", default["id"], "--pointer", "/data", "--start", "40", "--limit", "5")
    assert beyond["selection"]["received"] == 60 and len(beyond["data"]) == 5  # the store keeps what the window left out
    assert client.one("read", default["id"], "--pointer", "/data", "--filter", "Headline 55", "--limit", "1")["data"][0]["title"] == "Headline 55"


def test_news_pulse_lists_rows_and_reads_one_explanation(client):
    client.add("https://finviz.com/news?v=6", pulse_page())
    result = client.one("news", "pulse")
    assert result["data"] == [{"id": 285611, "age": "7 min", "headline": "VEON signs memorandum", "tickers": ["VEON"]}, {"id": 285537, "age": "2 hours", "headline": "US equity futures point lower", "tickers": ["$MARKET"]}]
    detail = {"id": 285537, "ticker": "$MARKET", "dateTime": "2026-09-15T05:36:38.943", "headline": "US equity futures point lower", "summary": "- S&P 500 futures **fall 0.59%**", "source": "market_summary", "sentiment": "bad", "catalyst": False, "instrument": 0, "bulletPointsList": None}
    client.add("https://finviz.com/api/stocks-why-moving/by-id/285537", detail)
    assert client.one("news", "pulse", "285537")["data"] == detail


def test_news_article_reads_finviz_hosted_articles_only(client):
    client.add("https://finviz.com/news/123/fed-decision-preview", article_page())
    data = client.one("news", "article", "https://finviz.com/news/123/fed-decision-preview")["data"]
    assert data == {"title": "Fed Decision Preview", "paragraphs": ["First paragraph.", "Second paragraph."], "links": [{"text": "SEC filing", "url": "https://www.sec.gov/x"}], "images": ["https://finviz.com/img/chart.png"]}
    assert client.one("news", "article", "https://www.marketwatch.com/story/x", code=2)["error"]["code"] == "unsupported_url"


def test_insider_trades_keep_ticker_owner_and_filing_links_and_confirm_the_transaction_filter(client):
    client.add("https://finviz.com/insidertrading?tc=2", insiders_page(transaction="insidertrading?tc=2"))
    result = client.one("insiders", "trades", "--transaction", "sale")
    row = result["data"][0]
    assert row["Ticker"] == "ENLT" and row["ticker"] == "ENLT" and row["Owner"] == "Paz Amit" and row["Transaction"] == "Sale"
    assert row["owner_url"] == "https://finviz.com/insidertrading?oc=2108367&tc=7&b=2" and row["filing_url"] == "http://www.sec.gov/Archives/edgar/data/1/x.xml"
    assert result["conditions"]["transaction"] == {"requested": "sale", "status": "confirmed", "evidence": "Sale Transactions"}
    assert result["sort_keys"] == {"Ticker": "ticker"}
    client.add("https://finviz.com/insidertrading?tc=7&oc=2108367", insiders_page())
    assert client.one("insiders", "trades", "--owner", "2108367")["conditions"]["owner"]["status"] == "unverified"


def test_bubble_axes_are_a_closed_set_the_source_validates(client):
    """An axis the API does not accept is answered with HTTP 400, so a guess costs a request; the parser refuses it first."""
    refused = client.one("market", "bubbles", "--x", "industry", code=2)
    assert refused["error"]["code"] == "invalid_argument"
    assert "marketCap" in refused["error"]["message"] and "--help" in refused["error"]["fix"]
    rows = [{"ticker": "AAPL", "x": 1.0, "y": 2.0, "size": 3.0, "color": "Technology"}]
    client.add("https://finviz.com/api/bubbles?x=PE&y=perfYtd&size=marketCap&color=sector&idx=dji", rows)
    assert client.one("market", "bubbles", "--x", "PE", "--y", "perfYtd")["data"] == rows


def test_open_reads_any_supported_finviz_url_generically_and_refuses_others(client):
    client.add("https://finviz.com/quote.ashx?t=AAPL&p=d", '<html><body><h1 data-ticker="AAPL">AAPL</h1><table class="snapshot-table2"><tr><td data-boxover-html="Market capitalization">Market Cap</td><td>4T</td></tr></table><table class="styled-table-new"><thead><tr><th>Date</th><th>Action</th></tr></thead><tr><td>Sep-09-26</td><td>Resumed</td></tr></table><select id="x"><option value="1" selected>one</option></select><script id="init" type="application/json">{"a": 1}</script><a href="/stock?t=MSFT">MSFT</a></body></html>')
    data = client.one("open", "https://finviz.com/quote.ashx?t=AAPL&p=d")["data"]
    assert data["metrics"] == [{"label": "Market Cap", "value": "4T", "definition": "Market capitalization", "unit": None}]
    assert data["tables"] == [{"headers": ["Date", "Action"], "rows": [{"Date": "Sep-09-26", "Action": "Resumed"}]}]
    assert data["initial"] == {"init": 1} and data["controls"] == {"x": 1}  # collections come back as counts and are asked for by name
    asked = client.one("open", "https://finviz.com/quote.ashx?t=AAPL&p=d", "--initial", "--options")["data"]
    assert asked["initial"] == {"init": {"a": 1}}
    assert asked["controls"] == {"x": [{"value": "1", "label": "one", "selected": True, "elite_only": False}]}
    assert data["links"] == [{"text": "MSFT", "url": "https://finviz.com/stock?t=MSFT"}]
    assert client.one("open", "https://www.sec.gov/cgi-bin/browse-edgar", code=2)["error"]["code"] == "unsupported_url"
    assert client.one("open", "https://finviz.com/register", code=2)["error"]["code"] == "unsupported_route"
    client.add("https://finviz.com/api/forex_perf", {"USD": 0.0})
    assert client.one("open", "https://finviz.com/api/forex_perf")["data"] == {"USD": 0.0}
    assert json.dumps(data)  # generic output is plain JSON


def test_calendar_kinds_are_real_commands_with_their_own_schema_and_the_first_page_sorts_without_a_second_request(client):
    assert client.one("schema", "calendar", "earnings")["data"]["command"] == "calendar earnings"
    sorted_page = {"data": {"initialDateFrom": "2026-09-15", "initialSort": "-earningsDate", "initialPage": 1, "entries": {"items": [{"ticker": "Z", "earningsDate": "2026-09-30T08:30:00"}], "page": 1, "totalPages": 1}}}
    client.add("https://finviz.com/calendar/earnings?sort=-earningsDate", calendar_page(sorted_page))
    result = client.one("calendar", "earnings", "--sort=-earningsDate")
    assert result["data"]["items"][0]["ticker"] == "Z"
    assert result["conditions"]["sort"] == {"requested": "-earningsDate", "status": "unverified", "evidence": {"source_sort": "-earningsDate"}}
    ignored = {"data": {"initialDateFrom": "2026-09-15", "initialSort": "earningsDate", "initialPage": 1, "entries": {"items": [{"ticker": "A"}], "page": 1, "totalPages": 1}}}
    client.add("https://finviz.com/calendar/earnings?sort=marketCap", calendar_page(ignored))
    assert client.one("calendar", "earnings", "--sort", "marketCap")["conditions"]["sort"] == {"requested": "marketCap", "status": "not_applied", "evidence": {"source_sort": "earningsDate"}}
    # Measured 2026-09-19: the page repeats any sort key it is given, including one the API answers with HTTP 400,
    # while an unusable date is replaced by the page's own default. So an agreeing sort echo confirms nothing.
    repeated = {"data": {"initialDateFrom": "2026-09-15", "initialSort": "bogus", "initialPage": 1, "entries": {"items": [{"ticker": "A"}], "page": 1, "totalPages": 1}}}
    client.add("https://finviz.com/calendar/earnings?sort=bogus", calendar_page(repeated))
    echoed = client.one("calendar", "earnings", "--sort", "bogus")["conditions"]["sort"]
    assert echoed == {"requested": "bogus", "status": "unverified", "evidence": {"source_sort": "bogus"}}
    assert client.one("calendar", "season", "--page", "2", code=2)["error"]["code"] == "invalid_argument"
    client.add("https://finviz.com/calendar/earnings", calendar_page({"data": {"initialDateFrom": "2026-09-15", "entries": {"items": [], "page": 1, "totalPages": 1, "totalItemsCount": 0}}}))
    empty = client.one("calendar", "earnings", code=7)
    assert empty["status"] == "empty" and empty["data"]["date_from"] == "2026-09-15" and empty["coverage"]["received"] == 0
    replayed = client.one("read", empty["id"], code=7)  # a recovery path must not report success for a response that carried nothing
    assert replayed["status"] == "empty" and replayed["data"]["status"] == "empty"


def test_market_and_group_api_parameters_report_conditions(client):
    client.add("https://finviz.com/api/map_perf?t=sec&st=w1", {"nodes": {"AAPL": 1.0}, "subtype": "d1", "version": 15})
    result = client.one("market", "map", "--period", "w1")
    assert result["conditions"]["period"] == {"requested": "w1", "status": "not_applied", "evidence": "d1"}
    client.add("https://finviz.com/api/futures_all?timeframe=w", {"ES": {"ticker": "ES", "last": 1}})
    assert client.one("market", "quotes", "futures", "--timeframe", "w")["conditions"]["timeframe"]["status"] == "unverified"
    client.add("https://finviz.com/api/groups_perf?g=industry&sg=energy", [{"ticker": "oilgasdrilling", "label": "Oil & Gas Drilling", "screenerUrl": "screener?f=ind_oilgasdrilling&v=211"}])
    result = client.one("groups", "performance", "--group", "industry/energy")
    assert result["conditions"]["group"]["status"] == "unverified" and result["conditions"]["group"]["evidence"] == {"first_screener_url": "screener?f=ind_oilgasdrilling&v=211"}


def test_open_keeps_headerless_tables_and_drops_site_navigation_links(client):
    client.add("https://finviz.com/news", news_page().replace("<html><body>", '<html><body><nav><a href="/login">Login</a><a href="/register?poster=trial">Try Elite</a></nav>'))
    data = client.one("open", "https://finviz.com/news")["data"]
    assert data["tables"][0]["headers"] == [] and data["tables"][0]["rows"][0]["cells"][1] == "06:56AM"
    assert all(link["text"] not in ("Login", "Try Elite") for link in data["links"])


@pytest.mark.parametrize("date", [[], ["--date", "2026-09-01"]])
def test_economic_calendar_rejects_unsupported_pagination_before_fetching(client, date):
    events = [{"event": "Budget", "date": "2026-09-01", "actual": "-$167B"}]
    client.add("https://finviz.com/calendar/economic", calendar_page({"data": {"initialDateFrom": "2026-09-01", "entries": events}}))
    result = client.one("calendar", "economic", "--page", "2", *date, code=2)
    assert result["error"]["code"] == "invalid_argument"
    assert "--page" in result["error"]["message"] and "calendar economic --help" in result["error"]["fix"]


def test_map_and_bubbles_report_selectors_without_inventing_confirmation(client):
    client.add("https://finviz.com/api/map_perf?t=geo&st=d1", {"nodes": {"RY": 1.2}, "subtype": "d1"})
    result = client.one("market", "map", "--type", "geo")
    assert result["conditions"]["type"] == {"requested": "geo", "status": "unverified", "evidence": None}
    rows = [{"ticker": "RY", "x": 1.2, "y": 6, "size": 40, "color": 3, "futureField": "source"}]
    client.add("https://finviz.com/api/bubbles?x=PE&y=perf52w&size=sales&color=sector&idx=ndx", rows)
    result = client.one("market", "bubbles", "--x", "PE", "--y", "perf52w", "--size", "sales", "--color", "sector", "--index", "ndx")
    assert result["conditions"] == {key: {"requested": value, "status": "unverified", "evidence": None} for key, value in {"x": "PE", "y": "perf52w", "size": "sales", "color": "sector", "index": "ndx"}.items()}
    saved = client.one("read", result["id"], "--pointer", "/data", "--limit", "1")
    assert saved["conditions"] == result["conditions"] and saved["data"] == rows


def test_a_mapping_is_narrowed_by_key_while_fields_reach_inside_each_value(client):
    """--fields promised "record fields to keep" but silently chose instruments, so naming quote fields returned everything."""
    quotes = {"6A": {"label": "AUD", "last": 0.71, "sparkline": [1, 2]}, "ES": {"label": "S&P 500", "last": 6600.0, "sparkline": [3]}}
    client.add("https://finviz.com/api/futures_all?timeframe=d", quotes)
    assert client.one("market", "quotes", "futures", "--keys", "ES")["data"] == {"ES": {"label": "S&P 500", "last": 6600.0}}
    inside = client.one("market", "quotes", "futures", "--fields", "label", "--sparkline")
    assert inside["data"] == {"6A": {"label": "AUD"}, "ES": {"label": "S&P 500"}}
    assert client.one("market", "quotes", "futures", "--keys", "NOPE", code=2)["error"]["code"] == "invalid_keys"
    assert client.one("market", "quotes", "futures", "--fields", "nope", code=2)["error"]["code"] == "invalid_fields"


def test_quotes_selection_preserves_source_keys_without_requiring_ticker_fields(client):
    quotes = {"6A": {"label": "AUD", "last": 0.71, "newField": {"scale": 1}}, "ES": {"label": "S&P 500", "last": 6600.0}, "ALIAS": {"ticker": "ES", "label": "Alias", "last": None}}
    client.add("https://finviz.com/api/futures_all?timeframe=d", quotes)
    assert client.one("market", "quotes", "futures")["data"] == quotes
    result = client.one("market", "quotes", "futures", "--filter", "6a", "--limit", "1")
    assert result["data"] == {"6A": quotes["6A"]}
    assert result["coverage"] == {"received": 3, "shown": 1, "exhaustive": False}
    assert client.one("read", result["id"], "--pointer", "/data")["data"] == quotes
    assert client.one("market", "quotes", "futures", "--keys", "ES,ALIAS", "--limit", "1")["data"] == {"ES": quotes["ES"]}
    assert client.one("market", "quotes", "futures", "--keys", "unknown", code=2)["error"]["code"] == "invalid_keys"
    assert client.one("market", "quotes", "futures", "--limit", "0", code=7)["data"] == {}


def test_open_excludes_plain_and_table_navigation_without_removing_data_links(client):
    chrome = '<a href="/screener">Screener</a><table><tr><td><a href="/screener.ashx">Screener</a></td><td><a href="/login">Login</a></td><td><a href="/elite">Elite</a></td></tr></table><nav><table><tr><td>Site navigation</td></tr></table></nav>'
    content = '<table><tr><td>Technology</td><td><a href="/screener?f=sec_technology">Members</a></td></tr></table><a href="https://example.com/helpful">Source</a>'
    client.add("https://finviz.com/news", "<html><body>" + chrome + content + "</body></html>")
    data = client.one("open", "https://finviz.com/news")["data"]
    assert len(data["tables"]) == 1 and data["tables"][0]["rows"][0]["cells"] == ["Technology", "Members"]
    assert data["links"] == [{"text": "Members", "url": "https://finviz.com/screener?f=sec_technology"}, {"text": "Source", "url": "https://example.com/helpful"}]


def test_open_preserves_article_headers_and_content_links_like_the_article_reader(client):
    url = "https://finviz.com/news/123/fed-decision-preview"
    client.add(url, '<html><body><header><nav><a href="/login">Login</a></nav></header><article><header><h1>Fed Decision Preview</h1><p>By Reporter</p></header><p>First paragraph.</p><a href="/screener">Mentioned screener</a></article></body></html>')
    expected = client.one("news", "article", url)["data"]
    opened = client.one("open", url)["data"]
    assert opened["article"] == expected
    assert opened["article"]["title"] == "Fed Decision Preview"
    assert opened["article"]["paragraphs"] == ["By Reporter", "First paragraph."]
    assert opened["links"] == [{"text": "Mentioned screener", "url": "https://finviz.com/screener"}]
