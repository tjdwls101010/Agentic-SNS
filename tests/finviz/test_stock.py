import json

from pages import stock_overview

OVERVIEW = "https://finviz.com/stock?t=A&ty=c"


def test_revenue_selection_keeps_units_named_series_and_every_source_record_field(client):
    from pages import stock_section

    values = [{"fiscal_year": "2025", "report_end_date": "2025-10-31", "source_filing_url": "https://www.sec.gov/x", "value": 12.5, "newField": {"restated": True}}]
    series = {"Products / A": values, "Products B": values, "Services": []}
    client.add("https://finviz.com/stock?t=A&ty=rv", stock_section({"products_and_services": {"unit": "USD", "revenues": series}}))
    result = client.one("stock", "revenue", "A", "--filter", "products", "--limit", "1")
    assert result["data"] == {"unit": "USD", "series": {"Products / A": values}}
    assert result["coverage"] == {"received": 3, "shown": 1, "exhaustive": False}
    assert client.one("read", result["id"], "--pointer", "/data")["data"] == {"unit": "USD", "series": series}
    assert client.one("stock", "revenue", "A", "--keys", "Services")["data"] == {"unit": "USD", "series": {"Services": []}}
    assert client.one("stock", "revenue", "A", "--keys", "unknown", code=2)["error"]["code"] == "invalid_keys"
    assert client.one("stock", "revenue", "A", "--filter", "missing", code=7)["data"] == {"unit": "USD", "series": {}}
    saved_slice = client.one("read", result["id"], "--pointer", "/data/series", "--start", "1", "--limit", "1")
    assert saved_slice["data"] == {"Products B": values}
    assert saved_slice["selection"]["context"] == {"unit": "USD"}


def test_snapshot_keeps_duplicate_metric_labels_with_their_own_definitions_and_header_facts(client):
    client.add(OVERVIEW, stock_overview())
    result = client.one("stock", "snapshot", "A")
    data = result["data"]
    assert data["ticker"] == "A" and data["name"] == "Agilent Technologies Inc"
    assert data["last_close"] == "147.00" and data["as_of"] == "Sep 15 • 6:05 AM ET" and data["change"] == "+0.20 (0.14%)"
    eps = [m for m in data["metrics"] if m["label"] == "EPS next Y"]
    assert eps == [{"label": "EPS next Y", "value": "6.74", "definition": "EPS estimate for next year", "unit": None}, {"label": "EPS next Y", "value": "8.75%", "definition": "EPS growth next year", "unit": "%"}]
    assert data["metrics"][4]["definition"] == "Quarterly earnings growth (YoY)"
    narrowed = client.one("stock", "snapshot", "A", "--filter", "eps next y")
    assert len(narrowed["data"]["metrics"]) == 2 and narrowed["coverage"] == {"received": 5, "shown": 2, "exhaustive": False}


def test_one_ticker_gets_every_metric_and_several_tickers_get_a_comparable_list(client):
    """84 metrics with their definitions answer a question about one company; repeated three times they are the same definitions three times."""
    for ticker in ("A", "MSFT", "NVDA"):
        client.add("https://finviz.com/stock?t=%s&ty=c" % ticker, stock_overview(ticker=ticker))
    alone = client.one("stock", "snapshot", "A")
    assert alone["coverage"]["shown"] == 5 and alone["data"]["metrics"][0]["definition"] == "Market capitalization"
    doc = client.run("stock", "snapshot", "A", "MSFT", "NVDA")
    assert doc["status"] == "ok" and [r["target"] for r in doc["results"]] == ["A", "MSFT", "NVDA"]
    for result in doc["results"]:
        assert result["data"]["ticker"] and result["data"]["last_close"]
        assert result["data"]["metrics"][0] == {"label": "Market Cap", "value": "41.39B"}
    asked = client.run("stock", "snapshot", "A", "MSFT", "--fields", "label,value,definition")["results"][0]
    assert asked["data"]["metrics"][0]["definition"] == "Market capitalization"


def test_a_failed_multi_target_result_names_every_target_it_saved(client):
    for ticker in ("A", "MSFT", "NVDA"):
        client.add("https://finviz.com/stock?t=%s&ty=c" % ticker, stock_overview(ticker=ticker, metrics=[("M%d" % n, "1", "d" * 60) for n in range(40)]))
    doc = client.run("--max-chars", "1200", "stock", "snapshot", "A", "MSFT", "NVDA", code=9)
    fix = doc["results"][0]["error"]["fix"]
    assert all(result["id"] in fix for result in doc["results"]), fix
    assert all(str(result["target"]) in fix for result in doc["results"]), fix
    assert len(json.dumps(doc, separators=(",", ":"))) <= 1200  # the replacement document is bounded too


def test_snapshot_accepts_several_tickers_and_isolates_a_failing_one(client):
    client.add(OVERVIEW, stock_overview())
    client.add("https://finviz.com/stock?t=ZZZZ&ty=c", "missing", status=404)
    doc = client.run("stock", "snapshot", "A", "ZZZZ", code=8)
    assert doc["status"] == "partial"
    assert [r["target"] for r in doc["results"]] == ["A", "ZZZZ"]
    assert doc["results"][0]["status"] == "ok" and doc["results"][1]["error"]["code"] == "http_error"


def test_overview_news_defaults_to_the_most_recent_screenful(client):
    items = [("Sep-%02d-26 04:30PM" % (day + 1), "Headline %d" % day, "https://example.com/%d" % day, "Source") for day in range(60)]
    client.add(OVERVIEW, stock_overview(news=items))
    result = client.one("stock", "news", "A")
    assert result["coverage"] == {"received": 60, "shown": 40, "exhaustive": False}
    assert [i["title"] for i in result["data"]][:2] == ["Headline 0", "Headline 1"]


def test_profile_ratings_news_insiders_and_ownership_come_from_the_overview_page(client):
    ownership = {"managersOwnership": [{"investorId": "2012383", "name": "BlackRock, Inc.", "slug": "blackrock-inc-2012383", "percOwnership": 9.06}], "fundsOwnership": [{"investorId": "1", "name": "Vanguard 500", "slug": "v", "percOwnership": 3.1}]}
    monthly = [{"date": 1756684800, "saleAggregated": 95972, "saleTransactionCount": 1, "buyAggregated": 0, "buyTransactionCount": 0}]
    client.add(OVERVIEW, stock_overview(ownership=ownership, insider_monthly=monthly))
    profile = client.one("stock", "profile", "A")["data"]
    assert profile == {"ticker": "A", "name": "Agilent Technologies Inc", "description": "Agilent Technologies, Inc. engages in life sciences.", "peers": ["WAT", "MTD"], "links": {"website": "http://example.com"}}
    ratings = client.one("stock", "ratings", "A")["data"]
    assert ratings == [{"Date": "Sep-09-26", "Action": "Resumed", "Analyst": "UBS", "Rating Change": "Neutral", "Price Target Change": "$165"}]
    news = client.one("stock", "news", "A")["data"]
    assert news == [{"time": "Sep-14-26 04:30PM", "title": "Keysight stock underperforms", "url": "https://www.marketwatch.com/x", "source": "MarketWatch"}]
    insiders = client.one("stock", "insiders", "A")["data"]
    assert insiders["trades"][0]["Insider Trading"] == "Dolsten Mikael" and insiders["trades"][0]["Transaction"] == "Sale"
    assert insiders["trades"][0]["filing_url"] == "http://www.sec.gov/Archives/edgar/data/1/form4.xml"
    assert insiders["trades"][0]["owner_url"] == "https://finviz.com/insidertrading?oc=1437590&tc=7"
    assert insiders["monthly"] == monthly
    held = client.one("stock", "ownership", "A")["data"]
    assert held == {"managers": ownership["managersOwnership"], "funds": ownership["fundsOwnership"]}


def test_flows_and_short_interest_windows_end_at_the_newest_record_not_the_oldest(client):
    """Both series are published oldest first, so a prefix cut answers a question about 2023 with a 2026 label."""
    flows = [{"date": "2023-09-05", "aum": 413148304250, "flow": -936946365.6}, {"date": "2023-09-06", "aum": 413000000000, "flow": 1.5}]
    client.add("https://finviz.com/stock?t=SPY&ty=c", stock_overview(ticker="SPY", name="SPDR S&P 500 ETF Trust", fundflows=flows, ratings_table=False))
    result = client.one("stock", "flows", "SPY", "--limit", "1")
    assert result["data"] == flows[-1:] and result["coverage"] == {"received": 2, "shown": 1, "exhaustive": False}
    from pages import stock_section
    short = [{"ticker": "A", "timestamp": 1579064400, "shortInterest": 5.19}, {"ticker": "A", "timestamp": 1789064400, "shortInterest": 7.7}]
    client.add("https://finviz.com/stock?t=A&ty=si", stock_section(short))
    assert client.one("stock", "short-interest", "A", "--limit", "1")["data"] == short[-1:]


def test_flows_return_etf_fund_flows_and_are_empty_for_a_stock(client):
    flows = [{"date": "2023-09-05", "aum": 413148304250, "flow": -936946365.6}, {"date": "2023-09-06", "aum": 413000000000, "flow": 1.5}]
    client.add("https://finviz.com/stock?t=SPY&ty=c", stock_overview(ticker="SPY", name="SPDR S&P 500 ETF Trust", fundflows=flows, ratings_table=False))
    result = client.one("stock", "flows", "SPY", "--limit", "1")
    assert result["data"] == flows[-1:] and result["coverage"]["received"] == 2
    client.add(OVERVIEW, stock_overview())
    result = client.one("stock", "flows", "A", code=7)
    assert result["status"] == "empty" and "ETF" in result["warnings"][0]


from pages import stock_section  # noqa: E402


EARNINGS = {"earningsDate": "2026-08-26T16:30:00", "earningsData": [{"ticker": "A", "fiscalPeriod": "2026Q3", "epsActual": 1.62, "epsEstimate": 1.4883}, {"ticker": "A", "fiscalPeriod": "2026Q2", "epsActual": 1.4, "epsEstimate": 1.3}], "earningsAnnualData": [{"fiscalPeriod": "2025FY", "epsActual": 5.5}], "earningsRevisionsData": [{"fiscalPeriod": "2023FY", "estimateType": "E", "mean": 5.6}, {"fiscalPeriod": "2024FY", "estimateType": "E", "mean": 6.1}], "priceReactionData": [{"fiscalPeriod": "2026Q3", "rsi": 67.1}]}


def test_earnings_datasets_are_selected_and_revisions_can_be_narrowed_by_fiscal_period(client):
    client.add("https://finviz.com/stock?t=A&ty=ea", stock_section(EARNINGS))
    result = client.one("stock", "earnings", "A")
    assert result["data"] == {"next_earnings_date": "2026-08-26T16:30:00", "dataset": "quarterly", "records": EARNINGS["earningsData"]}
    assert result["request"]["dataset"] == "quarterly"
    annual = client.one("stock", "earnings", "A", "--dataset", "annual")["data"]
    assert annual["records"] == EARNINGS["earningsAnnualData"]
    revisions = client.one("stock", "earnings", "A", "--dataset", "revisions", "--fiscal-period", "2024FY")["data"]
    assert revisions["records"] == [EARNINGS["earningsRevisionsData"][1]]
    reaction = client.one("stock", "earnings", "A", "--dataset", "reaction")["data"]
    assert reaction["records"][0]["rsi"] == 67.1


def test_forecast_dividends_revenue_and_short_interest_keep_source_records(client):
    forecast = {"targetPrice": 175.58, "targetPriceLow": 155, "targetPriceHigh": 190, "targetPriceAnalysts": 19, "lastClose": 146.8, "lastTime": "2026-09-14T15:59:55", "recommendationsData": [{"recomDate": "2024-11-19", "targetPrice": 149.7, "buy": 7, "hold": 11, "sell": 1}], "earningsData": []}
    client.add("https://finviz.com/stock?t=A&ty=fc", stock_section(forecast))
    data = client.one("stock", "forecast", "A")["data"]
    assert data == {"target_price": 175.58, "target_price_low": 155, "target_price_high": 190, "analysts": 19, "last_close": 146.8, "last_time": "2026-09-14T15:59:55", "recommendations": forecast["recommendationsData"]}
    dividends = {"lastClose": 146.8, "dividendExDate": "2026-06-30T00:00:00", "dividendEstimate": 1.019, "dividendTTM": 1.013, "dividendsData": [{"Ticker": "A", "Exdate": "2026-06-30", "Ordinary": 0.255, "Special": 0}], "dividendsAnnualData": [{"Ticker": "A", "FiscalPeriod": "2015FY", "Amount": 0.4, "Yield": 1.06, "Payout": 33.33, "Estimate": False}]}
    client.add("https://finviz.com/stock?t=A&ty=dv", stock_section(dividends))
    data = client.one("stock", "dividends", "A")["data"]
    assert data == {"ex_date": "2026-06-30T00:00:00", "estimate": 1.019, "ttm": 1.013, "last_close": 146.8, "payments": dividends["dividendsData"], "annual": dividends["dividendsAnnualData"]}
    revenue = {"products_and_services": {"revenues": {"Instrumentation": [{"fiscal_year": "2014", "report_end_date": "2014-10-31", "source_filing_url": "https://www.sec.gov/x", "value": 831000000.0}]}, "unit": "USD"}, "regions": {"revenues": {"Americas": []}, "unit": "USD"}, "segment": {"revenues": {}, "unit": "USD"}}
    client.add("https://finviz.com/stock?t=A&ty=rv", stock_section(revenue))
    data = client.one("stock", "revenue", "A")["data"]
    assert data == {"unit": "USD", "series": revenue["products_and_services"]["revenues"]}
    assert client.one("stock", "revenue", "A", "--by", "regions")["data"] == {"unit": "USD", "series": {"Americas": []}}
    assert client.one("stock", "revenue", "A", "--by", "segment", code=7)["status"] == "empty"
    short = [{"ticker": "A", "timestamp": 1579064400, "shortInterest": 5.19, "sharesFloat": 306.66, "averageVolume": 1609239.97}]
    client.add("https://finviz.com/stock?t=A&ty=si", stock_section(short))
    assert client.one("stock", "short-interest", "A")["data"] == short


def test_options_confirm_expiry_and_filter_contract_type_locally(client):
    chain = {"view": "chain_date", "expiries": ["2026-09-18", "2026-10-16"], "currentExpiry": "2026-10-16", "ticker": "A", "options": [{"ticker": "A", "exDate": 261016, "strike": 55, "type": "put", "iv": 2.7}, {"ticker": "A", "exDate": 261016, "strike": 60, "type": "call", "iv": 1.1}], "lastClose": 146.8, "lastTime": 1789415995}
    client.add("https://finviz.com/stock?t=A&ty=oc&e=2026-10-16", stock_section(chain))
    result = client.one("stock", "options", "A", "--expiry", "2026-10-16", "--type", "call")
    assert result["conditions"]["expiry"] == {"requested": "2026-10-16", "status": "confirmed", "evidence": "2026-10-16"}
    assert result["data"]["expiries"] == ["2026-09-18", "2026-10-16"] and result["data"]["current_expiry"] == "2026-10-16"
    assert result["data"]["contracts"] == [chain["options"][1]]
    assert result["coverage"] == {"received": 2, "shown": 1, "exhaustive": False}
    client.add("https://finviz.com/stock?t=A&ty=oc&e=2027-01-01", stock_section(dict(chain, currentExpiry="2026-09-18")))
    assert client.one("stock", "options", "A", "--expiry", "2027-01-01")["conditions"]["expiry"]["status"] == "not_applied"


def test_option_chains_default_to_the_strikes_around_the_last_close(client):
    """A whole expiry exceeds the budget, and cutting by strike order would answer with only the deepest out-of-the-money contracts."""
    from pages import stock_section
    contracts = [{"strike": strike, "type": kind, "iv": 1.0} for strike in (20, 60, 150, 155, 900) for kind in ("call", "put")]
    chain = {"expiries": ["2026-10-16"], "currentExpiry": "2026-10-16", "options": contracts, "lastClose": 152.0, "lastTime": 1789415995}
    client.add("https://finviz.com/stock?t=A&ty=oc", stock_section(chain))
    near = client.one("stock", "options", "A", "--strikes", "2")
    assert [c["strike"] for c in near["data"]["contracts"]] == [150, 150, 155, 155]
    assert near["coverage"] == {"received": 10, "shown": 4, "exhaustive": False}
    assert [c["strike"] for c in client.one("stock", "options", "A", "--strikes", "2", "--type", "call")["data"]["contracts"]] == [150, 155]
    assert client.one("stock", "options", "A", "--strikes", "0")["coverage"]["shown"] == 10
    assert [c["strike"] for c in client.one("stock", "options", "A")["data"]["contracts"]] == [20, 20, 60, 60, 150, 150, 155, 155, 900, 900]


def test_filings_page_through_source_entries_and_filter_forms_locally(client):
    filings = {"formCategories": [{"id": "annual-quarterly-current", "label": "All annual, quarterly, and current reports", "forms": ["10-K", "10-Q", "8-K"]}], "availableForms": ["4", "8-K", "10-K"], "initialPage": 2, "initialSort": "-filingDate", "initialFilter": None, "entries": {"items": [{"form": "4", "filingDate": "2026-09-10T00:00:00", "filing": "https://www.sec.gov/a-index.html"}, {"form": "10-K", "filingDate": "2025-12-19T00:00:00", "filing": "https://www.sec.gov/k-index.html"}], "page": 2, "pageSize": 2, "totalItemsCount": 1144, "totalPages": 572}}
    client.add("https://finviz.com/stock?t=A&ty=lf&page=2", stock_section(filings))
    result = client.one("stock", "filings", "A", "--page", "2", "--form", "10-K")
    assert result["data"]["items"] == [filings["entries"]["items"][1]]
    assert result["data"]["available_forms"] == ["4", "8-K", "10-K"]
    assert result["conditions"]["page"] == {"requested": 2, "status": "confirmed", "evidence": 2}
    assert result["coverage"] == {"received": 2, "shown": 1, "source_total": 1144, "exhaustive": False, "pagination_end": False}
    assert result["continuation"] == {"page": 3}


def test_statement_aligns_periods_and_prices_refuse_misaligned_arrays(client):
    statement = {"currency": "USD", "data": {"Period": ["TTM", "2025FY"], "Period End Date": ["", "10/31/2025"], "Total Revenue": ["7,372.00", "6,948.00"], "EPS (Diluted)": ["4.91", "4.57"]}}
    client.add("https://finviz.com/api/statement?t=A&so=F&s=IA", statement)
    data = client.one("stock", "statement", "A")["data"]
    assert data == {"currency": "USD", "periods": ["TTM", "2025FY"], "period_end_dates": ["", "10/31/2025"], "items": {"Total Revenue": ["7,372.00", "6,948.00"], "EPS (Diluted)": ["4.91", "4.57"]}}
    sliced = client.one("read", client.one("stock", "statement", "A")["id"], "--pointer", "/data/items")
    assert sliced["selection"]["context"] == {"currency": "USD", "periods": ["TTM", "2025FY"], "period_end_dates": ["", "10/31/2025"]}
    client.add("https://finviz.com/api/statement?t=A&so=F&s=BQ", {"currency": "USD", "data": {"Period": ["2026Q3"], "Total Assets": ["13,967.00"]}})
    assert client.one("stock", "statement", "A", "--kind", "balance", "--period", "quarterly")["data"]["items"] == {"Total Assets": ["13,967.00"]}
    bars = {"date": [1788872400, 1788958800], "open": [148.02, 145.23], "high": [149.2, 146.5], "low": [145.9, 143.7], "close": [146.85, 144.75], "volume": [1603236, 1853973], "lastClose": 146.8}
    client.add("https://finviz.com/api/quote?instrument=stock&ticker=A&timeframe=d&barsCount=2", bars)
    result = client.one("stock", "prices", "A", "--bars", "2")
    assert result["data"]["bars"] == [{"date_epoch": 1788872400, "open": 148.02, "high": 149.2, "low": 145.9, "close": 146.85, "volume": 1603236}, {"date_epoch": 1788958800, "open": 145.23, "high": 146.5, "low": 143.7, "close": 144.75, "volume": 1853973}]
    assert result["data"]["last"] == {"lastClose": 146.8}
    broken = dict(bars, close=[146.85])
    client.add("https://finviz.com/api/quote?instrument=stock&ticker=A&timeframe=d&barsCount=3", broken)
    result = client.one("stock", "prices", "A", "--bars", "3", code=6)
    assert result["error"]["code"] == "array_alignment" and "close" in result["error"]["message"]
    assert client.one("read", result["id"], "--pointer", "/data/close")["data"] == [146.85]


def test_empty_record_sets_inside_a_dict_report_empty_and_too_large_points_at_the_records(client):
    client.add("https://finviz.com/stock?t=A&ty=ea", stock_section(EARNINGS))
    empty = client.one("stock", "earnings", "A", "--fiscal-period", "2099Q9", code=7)
    assert empty["status"] == "empty" and empty["data"]["records"] == [] and empty["data"]["next_earnings_date"]
    big = dict(EARNINGS, earningsData=[{"fiscalPeriod": "2026Q%d" % i, "note": "x" * 400} for i in range(20)])
    client.add("https://finviz.com/stock?t=A&ty=ea", stock_section(big))
    error = client.run("--max-chars", "1000", "stock", "earnings", "A", code=9)["results"][0]["error"]
    assert "--pointer /data/records" in error["fix"]


def test_nested_earnings_recovery_requires_the_record_pointer_not_the_data_object(client):
    records = [{"fiscalPeriod": "2025FY", "note": "x" * 650} for _ in range(60)]
    client.add("https://finviz.com/stock?t=A&ty=ea", stock_section(dict(EARNINGS, earningsData=records)))
    result = client.one("stock", "earnings", "A", code=9)
    assert client.one("read", result["id"], "--pointer", "/data", "--start", "0", "--limit", "20", code=9)["error"]["code"] == "too_large"
    assert client.one("read", result["id"], "--pointer", "/data/records", "--start", "0", "--limit", "20")["data"] == records[:20]


def test_profile_links_and_price_bar_field_names_follow_the_contract(client):
    client.add(OVERVIEW, stock_overview())
    result = client.one("stock", "profile", "A")
    assert "conditions" not in result and "coverage" not in result
    profile = result["data"]
    assert profile["links"] == {"website": "http://example.com"} and profile["peers"] == ["WAT", "MTD"]
    bars = {"date": [1788872400], "open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5], "volume": [10]}
    client.add("https://finviz.com/api/quote?instrument=stock&ticker=A&timeframe=d&barsCount=1", bars)
    assert client.one("stock", "prices", "A", "--bars", "1")["data"]["bars"] == [{"date_epoch": 1788872400, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10}]
