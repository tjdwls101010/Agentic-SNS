from pages import stock_overview, stock_section

OVERVIEW = "https://finviz.com/stock?t=A&ty=c"


def test_the_overview_defaults_to_the_snapshot_and_counts_the_other_sections(client):
    ownership = {"managersOwnership": [{"investorId": "2012383", "name": "BlackRock, Inc.", "slug": "blackrock-inc-2012383", "percOwnership": 9.06}], "fundsOwnership": [{"investorId": "1", "name": "Vanguard 500", "slug": "v", "percOwnership": 3.1}]}
    monthly = [{"date": 1756684800, "saleAggregated": 95972, "saleTransactionCount": 1, "buyAggregated": 0, "buyTransactionCount": 0}]
    client.add(OVERVIEW, stock_overview(ownership=ownership, insider_monthly=monthly))
    result = client.one("stock", "overview", "A")
    data = result["data"]
    assert {k: data[k] for k in ("ticker", "name", "last_close", "as_of", "change")} == {"ticker": "A", "name": "Agilent Technologies Inc", "last_close": "147.00", "as_of": "Sep 15 • 6:05 AM ET", "change": "+0.20 (0.14%)"}
    assert data["description"] == "Agilent Technologies, Inc. engages in life sciences." and data["peers"] == ["WAT", "MTD"] and data["website"] == "http://example.com"
    eps = [m for m in data["snapshot"] if m["label"] == "EPS next Y"]
    assert eps == [{"label": "EPS next Y", "value": "6.74", "definition": "EPS estimate for next year", "unit": None}, {"label": "EPS next Y", "value": "8.75%", "definition": "EPS growth next year", "unit": "%"}]
    assert data["other_sections"] == {"news": 1, "ratings": 1, "insiders": 1, "insider_monthly": 1, "ownership_managers": 1, "ownership_funds": 1}
    assert result["coverage"] == {"snapshot": {"received": 5, "matched": 5, "shown": 5, "start": 0}}


def test_every_overview_section_comes_from_the_one_page(client):
    ownership = {"managersOwnership": [{"investorId": "2012383", "name": "BlackRock, Inc.", "percOwnership": 9.06}], "fundsOwnership": [{"investorId": "1", "name": "Vanguard 500", "percOwnership": 3.1}]}
    monthly = [{"date": 1756684800, "saleAggregated": 95972}]
    client.add(OVERVIEW, stock_overview(ownership=ownership, insider_monthly=monthly))
    data = client.one("stock", "overview", "A", "--sections", "news,ratings,insiders,insider_monthly,ownership_managers,ownership_funds")["data"]
    assert data["news"] == [{"date": "Sep-14-26", "time": "04:30PM", "title": "Keysight stock underperforms", "url": "https://www.marketwatch.com/x", "source": "MarketWatch"}]
    assert data["ratings"] == [{"Date": "Sep-09-26", "Action": "Resumed", "Analyst": "UBS", "Rating Change": "Neutral", "Price Target Change": "$165"}]
    trade = data["insiders"][0]
    assert trade["Insider Trading"] == "Dolsten Mikael" and trade["Transaction"] == "Sale"
    assert trade["filing_url"] == "http://www.sec.gov/Archives/edgar/data/1/form4.xml" and trade["owner_url"] == "https://finviz.com/insidertrading?oc=1437590&tc=7"
    assert data["insider_monthly"] == monthly and data["ownership_managers"] == ownership["managersOwnership"] and data["ownership_funds"] == ownership["fundsOwnership"]


def test_a_snapshot_is_narrowed_like_any_collection(client):
    client.add(OVERVIEW, stock_overview())
    narrowed = client.one("stock", "overview", "A", "--filter", "eps next y", "--fields", "label,value")
    assert narrowed["data"]["snapshot"] == [{"label": "EPS next Y", "value": "6.74"}, {"label": "EPS next Y", "value": "8.75%"}]
    assert narrowed["coverage"]["snapshot"] == {"received": 5, "matched": 2, "shown": 2, "start": 0}


def test_several_tickers_are_separate_results_and_a_failing_one_is_isolated(client):
    client.add(OVERVIEW, stock_overview())
    client.add("https://finviz.com/stock?t=ZZZZ&ty=c", "missing", status=404)
    doc = client.run("stock", "overview", "A", "ZZZZ", code=8)
    assert doc["status"] == "partial" and [r["target"] for r in doc["results"]] == ["A", "ZZZZ"]
    assert doc["results"][0]["status"] == "ok" and doc["results"][1]["error"]["code"] == "http_error"


def test_overview_news_defaults_to_the_most_recent_screenful(client):
    items = [("Sep-%02d-26 04:30PM" % (day % 28 + 1), "Headline %d" % day, "https://example.com/%d" % day, "Source") for day in range(60)]
    client.add(OVERVIEW, stock_overview(news=items))
    result = client.one("stock", "overview", "A", "--sections", "news")
    assert result["coverage"]["news"] == {"received": 60, "matched": 60, "shown": 20, "start": 0, "cut": "default"}
    assert [i["title"] for i in result["data"]["news"]][:2] == ["Headline 0", "Headline 1"]
    assert result["next"] == "read " + result["id"] + " --section news --start 20"


def test_fund_flows_are_newest_first_and_absent_for_a_stock(client):
    flows = [{"date": "2023-09-05", "aum": 413148304250, "flow": -936946365.6}, {"date": "2023-09-06", "aum": 413000000000, "flow": 1.5}]
    client.add("https://finviz.com/stock?t=SPY&ty=c", stock_overview(ticker="SPY", name="SPDR S&P 500 ETF Trust", fundflows=flows, ratings_table=False))
    result = client.one("stock", "overview", "SPY", "--sections", "flows", "--limit", "1")
    assert result["data"]["flows"] == flows[-1:] and result["coverage"]["flows"]["received"] == 2
    client.add(OVERVIEW, stock_overview())
    stock = client.one("stock", "overview", "A", "--sections", "flows", code=7)
    assert stock["coverage"] == {"flows": {"absent": True}} and any("ETF" in w for w in stock["warnings"])
    both = client.one("stock", "overview", "A", "--sections", "snapshot,flows")
    assert both["status"] == "ok" and both["coverage"]["flows"] == {"absent": True}


EARNINGS = {"earningsDate": "2026-08-26T16:30:00", "earningsData": [{"ticker": "A", "fiscalPeriod": "2026Q3", "epsActual": 1.62, "epsEstimate": 1.4883}, {"ticker": "A", "fiscalPeriod": "2026Q2", "epsActual": 1.4, "epsEstimate": 1.3}], "earningsAnnualData": [{"fiscalPeriod": "2024FY", "epsActual": 5.2}, {"fiscalPeriod": "2025FY", "epsActual": 5.5}], "earningsRevisionsData": [{"fiscalPeriod": "2023FY", "estimateType": "E", "mean": 5.6}, {"fiscalPeriod": "2024FY", "estimateType": "E", "mean": 6.1}], "priceReactionData": [{"fiscalPeriod": "2026Q3", "rsi": 67.1}]}


def test_earnings_datasets_are_sections_of_one_page(client):
    client.add("https://finviz.com/stock?t=A&ty=ea", stock_section(EARNINGS))
    result = client.one("stock", "earnings", "A")
    assert result["data"]["next_earnings_date"] == "2026-08-26T16:30:00" and result["data"]["quarterly"] == EARNINGS["earningsData"]
    assert result["data"]["other_sections"] == {"annual": 2, "revisions": 2, "reaction": 1}
    client.responses.clear()
    annual = client.one("read", result["id"], "--section", "annual")["data"]["annual"]
    assert [r["fiscalPeriod"] for r in annual] == ["2025FY", "2024FY"]  # the source lists years oldest first
    history = client.one("read", result["id"], "--section", "revisions", "--fiscal-period", "2024FY")["data"]["revisions"]
    assert history == [EARNINGS["earningsRevisionsData"][1]]


def test_forecast_and_dividends_keep_source_records_newest_first(client):
    forecast = {"targetPrice": 175.58, "targetPriceLow": 155, "targetPriceHigh": 190, "targetPriceAnalysts": 19, "lastClose": 146.8, "lastTime": "2026-09-14T15:59:55", "recommendationsData": [{"recomDate": "2024-11-19", "buy": 7}, {"recomDate": "2024-11-26", "buy": 8}]}
    client.add("https://finviz.com/stock?t=A&ty=fc", stock_section(forecast))
    data = client.one("stock", "forecast", "A")["data"]
    assert {k: data[k] for k in ("target_price", "analysts", "last_close")} == {"target_price": 175.58, "analysts": 19, "last_close": 146.8}
    assert [r["recomDate"] for r in data["recommendations"]] == ["2024-11-26", "2024-11-19"]
    dividends = {"lastClose": 146.8, "dividendExDate": "2026-06-30T00:00:00", "dividendEstimate": 1.019, "dividendTTM": 1.013, "dividendsData": [{"Ticker": "A", "Exdate": "2026-06-30", "Ordinary": 0.255, "Special": 0}], "dividendsAnnualData": [{"FiscalPeriod": "2015FY", "Amount": 0.4, "Estimate": False}, {"FiscalPeriod": "2016FY", "Amount": 0.46, "Estimate": False}]}
    client.add("https://finviz.com/stock?t=A&ty=dv", stock_section(dividends))
    data = client.one("stock", "dividends", "A")["data"]
    assert data["ex_date"] == "2026-06-30T00:00:00" and data["payments"] == dividends["dividendsData"]
    assert [r["FiscalPeriod"] for r in data["annual"]] == ["2016FY", "2015FY"]


def test_revenue_keeps_units_named_series_and_every_source_field(client):
    values = [{"fiscal_year": "2025", "report_end_date": "2025-10-31", "source_filing_url": "https://www.sec.gov/x", "value": 12.5, "newField": {"restated": True}}]
    revenue = {"products_and_services": {"unit": "USD", "revenues": {"Products / A": values, "Products B": values, "Services": []}}, "regions": {"unit": "USD", "revenues": {"Americas": values}}, "segment": {"unit": "USD", "revenues": {}}}
    client.add("https://finviz.com/stock?t=A&ty=rv", stock_section(revenue))
    result = client.one("stock", "revenue", "A")
    assert result["data"]["products"] == [dict({"series": "Products / A"}, **values[0]), dict({"series": "Products B"}, **values[0])]
    assert result["data"]["unit"] == {"products": "USD", "regions": "USD", "segments": "USD"}
    assert result["data"]["series"]["products"] == {"Products / A": 1, "Products B": 1, "Services": 0}  # an empty series stays named
    narrowed = client.one("stock", "revenue", "A", "--filter", "products b", "--fields", "value")
    assert narrowed["data"]["products"] == [{"series": "Products B", "value": 12.5}]
    assert client.one("stock", "revenue", "A", "--sections", "segments", code=7)["status"] == "empty"


def test_short_interest_defaults_to_the_newest_readings(client):
    short = [{"ticker": "A", "timestamp": 1579064400 + n, "shortInterest": 5.0 + n} for n in range(30)]
    client.add("https://finviz.com/stock?t=A&ty=si", stock_section(short))
    result = client.one("stock", "short-interest", "A")
    readings = result["data"]["readings"]
    assert readings[0] == short[-1] and len(readings) == 24 and result["coverage"]["cut"] == "default"
    assert result["next"] == "read " + result["id"] + " --start 24"


def test_options_confirm_expiry_and_narrow_side_and_strikes_locally(client):
    chain = {"expiries": ["2026-09-18", "2026-10-16"], "currentExpiry": "2026-10-16", "options": [{"strike": 55, "type": "put", "iv": 2.7}, {"strike": 60, "type": "call", "iv": 1.1}], "lastClose": 146.8, "lastTime": 1789415995}
    client.add("https://finviz.com/stock?t=A&ty=oc&e=2026-10-16", stock_section(chain))
    result = client.one("stock", "options", "A", "--expiry", "2026-10-16", "--type", "call")
    assert result["conditions"]["expiry"] == {"requested": "2026-10-16", "status": "confirmed", "evidence": "2026-10-16"}
    assert result["data"]["expiries"] == ["2026-09-18", "2026-10-16"] and result["data"]["contracts"] == [chain["options"][1]]
    assert result["coverage"] == {"received": 2, "matched": 1, "shown": 1, "start": 0}
    client.add("https://finviz.com/stock?t=A&ty=oc&e=2027-01-01", stock_section(dict(chain, currentExpiry="2026-09-18")))
    assert client.one("stock", "options", "A", "--expiry", "2027-01-01")["conditions"]["expiry"]["status"] == "not_applied"


def test_option_chains_default_to_the_strikes_around_the_last_close(client):
    contracts = [{"strike": strike, "type": kind, "iv": 1.0} for strike in (20, 60, 150, 155, 900) for kind in ("call", "put")]
    client.add("https://finviz.com/stock?t=A&ty=oc", stock_section({"expiries": ["2026-10-16"], "currentExpiry": "2026-10-16", "options": contracts, "lastClose": 152.0}))
    assert [c["strike"] for c in client.one("stock", "options", "A", "--strikes", "2")["data"]["contracts"]] == [150, 150, 155, 155]
    assert [c["strike"] for c in client.one("stock", "options", "A", "--strikes", "2", "--type", "call")["data"]["contracts"]] == [150, 155]
    assert client.one("stock", "options", "A", "--strikes", "0")["coverage"]["matched"] == 10


def test_filings_page_through_the_source_and_filter_forms_locally(client):
    filings = {"formCategories": [{"id": "annual-quarterly-current", "forms": ["10-K", "10-Q", "8-K"]}], "availableForms": ["4", "8-K", "10-K"], "initialSort": "-filingDate", "entries": {"items": [{"form": "4", "filingDate": "2026-09-10T00:00:00"}, {"form": "10-K", "filingDate": "2025-12-19T00:00:00"}], "page": 2, "pageSize": 2, "totalItemsCount": 1144, "totalPages": 572}}
    client.add("https://finviz.com/stock?t=A&ty=lf&page=2", stock_section(filings))
    result = client.one("stock", "filings", "A", "--page", "2", "--form", "10-K")
    assert result["data"]["filings"] == [filings["entries"]["items"][1]] and result["data"]["available_forms"] == ["4", "8-K", "10-K"]
    assert result["conditions"]["page"] == {"requested": 2, "status": "confirmed", "evidence": 2}
    assert result["coverage"] == {"received": 2, "matched": 1, "shown": 1, "start": 0, "source_total": 1144}
    assert result["next"] == "stock filings A --page 3 --form 10-K"


def test_a_statement_is_line_item_records_with_period_context(client):
    statement = {"currency": "USD", "data": {"Period": ["TTM", "2025FY"], "Period End Date": ["", "10/31/2025"], "Total Revenue": ["7,372.00", "6,948.00"], "EPS (Diluted)": ["4.91", "4.57"]}}
    client.add("https://finviz.com/api/statement?t=A&so=F&s=IA", statement)
    data = client.one("stock", "statement", "A")["data"]
    assert data == {"currency": "USD", "periods": ["TTM", "2025FY"], "period_end_dates": ["", "10/31/2025"], "items": [{"item": "Total Revenue", "TTM": "7,372.00", "2025FY": "6,948.00"}, {"item": "EPS (Diluted)", "TTM": "4.91", "2025FY": "4.57"}]}
    client.add("https://finviz.com/api/statement?t=A&so=F&s=BQ", {"currency": "USD", "data": {"Period": ["2026Q3"], "Total Assets": ["13,967.00"]}})
    assert client.one("stock", "statement", "A", "--kind", "balance", "--period", "quarterly")["data"]["items"] == [{"item": "Total Assets", "2026Q3": "13,967.00"}]
    assert client.one("stock", "statement", "A", "--fields", "2024FY", code=2)["error"]["code"] == "invalid_fields"


def test_price_bars_are_newest_first_and_misaligned_arrays_are_refused(client):
    bars = {"date": [1788872400, 1788958800], "open": [148.02, 145.23], "high": [149.2, 146.5], "low": [145.9, 143.7], "close": [146.85, 144.75], "volume": [1603236, 1853973], "lastClose": 146.8}
    client.add("https://finviz.com/api/quote?instrument=stock&ticker=A&timeframe=d&barsCount=2", bars)
    result = client.one("stock", "prices", "A", "--bars", "2")
    assert result["data"]["bars"] == [{"date_epoch": 1788958800, "open": 145.23, "high": 146.5, "low": 143.7, "close": 144.75, "volume": 1853973}, {"date_epoch": 1788872400, "open": 148.02, "high": 149.2, "low": 145.9, "close": 146.85, "volume": 1603236}]
    assert result["data"]["last"] == {"lastClose": 146.8}
    client.add("https://finviz.com/api/quote?instrument=stock&ticker=A&timeframe=d&barsCount=3", dict(bars, close=[146.85]))
    broken = client.one("stock", "prices", "A", "--bars", "3", code=6)
    assert broken["error"]["code"] == "array_alignment" and "close" in broken["error"]["message"]
    assert '"close": [146.85]' in client.one("read", broken["id"], "--raw")["data"]
