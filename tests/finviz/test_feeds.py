import json

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
    assert result["data"] == [quotes["ES"]] and result["coverage"]["received"] == 2
    client.add("https://finviz.com/api/forex_perf", {"USD": 0.0, "AUD": -0.19})
    assert client.one("market", "performance", "forex")["data"] == {"USD": 0.0, "AUD": -0.19}
    bubbles = [{"ticker": "CF", "company": "CF Industries", "x": 1.0, "y": 1.09, "size": 2.0e10, "color": "Basic Materials", "isETF": False}]
    client.add("https://finviz.com/api/bubbles?x=sector&y=lastChange&size=marketCap&color=sector&idx=sp500", bubbles)
    assert client.one("market", "bubbles")["data"] == bubbles


def test_market_map_resolves_classification_from_the_page_assets_and_degrades_to_partial(client):
    perf = {"nodes": {"RY": 1.2, "TD": -0.4}, "additional": {}, "subtype": "d1", "version": 15, "hash": "X"}
    client.add("https://finviz.com/api/map_perf?t=geo&st=d1", perf)
    client.add("https://finviz.com/map?t=geo", map_page())
    client.add("https://finviz.com/assets/dist-legacy/1378.v1.61170fe2.js", MAP_LOADER)
    client.add("https://finviz.com/assets/dist-legacy/runtime.v1.22f44280.js", MAP_RUNTIME)
    client.add("https://finviz.com/assets/dist-legacy/62.v1.bbb222.js", MAP_CHUNK)
    result = client.one("market", "map", "--type", "geo")
    assert result["data"]["performance"] == perf["nodes"] and result["data"]["period"] == "d1"
    assert result["data"]["classification"]["children"][0]["children"][0]["children"][0] == {"name": "RY", "description": "Royal Bank Of Canada", "value": 294647}
    assert result["data"]["classification_source"].endswith("62.v1.bbb222.js")
    only = client.one("market", "map", "--type", "geo", "--performance-only")
    assert only["data"]["classification"] is None and "source" not in only["data"] or only["data"].get("classification_source") is None
    client.add("https://finviz.com/assets/dist-legacy/62.v1.bbb222.js", "module.exports={name:'Other'}")
    degraded = client.one("market", "map", "--type", "geo", code=8)
    assert degraded["status"] == "partial" and degraded["data"]["performance"] == perf["nodes"] and degraded["data"]["classification"] is None
    assert degraded["error"]["code"] == "asset_structure"


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
    assert result["data"] == {"date_from": "2026-09-20", "items": later}
    assert result["conditions"] == {"date": {"requested": "2026-09-20", "status": "confirmed", "evidence": {"earliest_item": "2026-09-21T08:30:00"}}, "page": {"requested": 2, "status": "confirmed", "evidence": 2}}
    assert result["continuation"] == {"page": 3}
    economic = [{"calendarId": 1, "event": "Monthly Budget Statement", "date": "2026-09-11T14:00:00", "actual": "-$167B", "forecast": "-$404B"}]
    client.add("https://finviz.com/calendar/economic", calendar_page({"data": {"initialDateFrom": "2026-09-14", "entries": economic}}))
    result = client.one("calendar", "economic")
    assert result["data"]["items"] == economic and result["coverage"]["received"] == 1
    client.add("https://finviz.com/api/calendar/economic?dateFrom=2026-09-01", economic)
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
    assert data == {"title": "Fed Decision Preview", "paragraphs": ["First paragraph.", "Second paragraph."], "text": "First paragraph. Second paragraph. SEC filing", "links": [{"text": "SEC filing", "url": "https://www.sec.gov/x"}], "images": ["https://finviz.com/img/chart.png"]}
    assert client.one("news", "article", "https://www.marketwatch.com/story/x", code=2)["error"]["code"] == "unsupported_url"


def test_insider_trades_keep_ticker_owner_and_filing_links_and_confirm_the_transaction_filter(client):
    client.add("https://finviz.com/insidertrading?tc=2", insiders_page(transaction="insidertrading?tc=2"))
    result = client.one("insiders", "trades", "--transaction", "sale")
    row = result["data"][0]
    assert row["Ticker"] == "ENLT" and row["ticker"] == "ENLT" and row["Owner"] == "Paz Amit" and row["Transaction"] == "Sale"
    assert row["owner_url"] == "https://finviz.com/insidertrading?oc=2108367&tc=7&b=2" and row["filing_url"] == "http://www.sec.gov/Archives/edgar/data/1/x.xml"
    assert result["conditions"]["transaction"] == {"requested": "sale", "status": "confirmed", "evidence": "Sale Transactions"}
    client.add("https://finviz.com/insidertrading?tc=7&oc=2108367", insiders_page())
    assert client.one("insiders", "trades", "--owner", "2108367")["conditions"]["owner"]["status"] == "unverified"


def test_open_reads_any_supported_finviz_url_generically_and_refuses_others(client):
    client.add("https://finviz.com/quote.ashx?t=AAPL&p=d", '<html><body><h1 data-ticker="AAPL">AAPL</h1><table class="snapshot-table2"><tr><td data-boxover-html="Market capitalization">Market Cap</td><td>4T</td></tr></table><table class="styled-table-new"><thead><tr><th>Date</th><th>Action</th></tr></thead><tr><td>Sep-09-26</td><td>Resumed</td></tr></table><select id="x"><option value="1" selected>one</option></select><script id="init" type="application/json">{"a": 1}</script><a href="/stock?t=MSFT">MSFT</a></body></html>')
    data = client.one("open", "https://finviz.com/quote.ashx?t=AAPL&p=d")["data"]
    assert data["metrics"] == [{"label": "Market Cap", "value": "4T", "definition": "Market capitalization", "unit": None}]
    assert data["tables"] == [{"headers": ["Date", "Action"], "rows": [{"Date": "Sep-09-26", "Action": "Resumed"}]}]
    assert data["initial"] == {"init": {"a": 1}} and data["controls"] == {"x": [{"value": "1", "label": "one", "selected": True, "elite_only": False}]}
    assert data["links"] == [{"text": "MSFT", "url": "https://finviz.com/stock?t=MSFT"}]
    assert client.one("open", "https://www.sec.gov/cgi-bin/browse-edgar", code=2)["error"]["code"] == "unsupported_url"
    assert client.one("open", "https://finviz.com/register", code=2)["error"]["code"] == "unsupported_route"
    client.add("https://finviz.com/api/forex_perf", {"USD": 0.0})
    assert client.one("open", "https://finviz.com/api/forex_perf")["data"] == {"USD": 0.0}
    assert json.dumps(data)  # generic output is plain JSON
