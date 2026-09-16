"""Compact Finviz page builders mirroring the markup observed on 2026-09-15; tests state the values, the builders only supply structure."""

import json


def screener_filters(filters=(("cap", "Market Cap.", "Total market value of a company's outstanding shares.", [("mega", "Mega ($200bln and more)"), ("largeover", "+Large (over $10bln)")]), ("sec", "Sector", "Company sector.", [("technology", "Technology")])), selected=(), signals=(("ta_topgainers", "Top Gainers"), ("ta_newhigh", "New High"))):
    rows = ""
    for key, label, definition, options in filters:
        opts = '<option value="">Any</option>' + "".join('<option value="%s"%s>%s</option>' % (v, ' selected="selected"' if key + "_" + v in selected else "", t) for v, t in options)
        rows += '<tr><td class="filters-cells"><span class="screener-combo-title" data-boxover-html="&lt;b&gt;%s&lt;/b&gt;&lt;br&gt;%s">%s</span></td><td class="filters-cells"><select id="fs_%s" class="screener-combo-text">%s<option value="" data-elite-only="screener">Custom (Elite only)</option></select></td></tr>' % (label, definition, label, key, opts)
    signal = '<select id="signalSelect"><option selected="selected" value="screener?v=111&ft=4">None (all stocks)</option>' + "".join('<option value="screener?v=111&s=%s&ft=4">%s</option>' % (v, t) for v, t in signals) + "</select>"
    return "<html><body>" + signal + "<table>" + rows + "</table></body></html>"


def screener_table(rows, headers=("No.", "Ticker", "Company", "Market Cap"), total=None, page_values=(1, 21, 41), current=1, sort=("ticker", "ascending"), selected_filters=(), signal=None, columns=None, filter_controls=True, echo=None):
    """rows: list of (ticker, cells) where cells are the values after the Ticker column."""
    head = "".join('<th class="table-header%s" onclick="window.location=\'screener?v=111&ft=4&o=%s\'">%s</th>' % (" is-selected is-" + sort[1] if h.lower().replace(" ", "") == sort[0].replace("-", "") else "", ("-" if sort[1] == "ascending" else "") + h.lower().replace(" ", ""), h) for h in headers)
    body = ""
    for number, (ticker, cells) in enumerate(rows, start=current):
        first = "" if headers[0] != "No." else '<td align="right"><a href="stock?t=%s&ty=c&p=d&b=1">%d</a></td>' % (ticker, number)
        body += '<tr class="styled-row">%s<td data-boxover-ticker="%s" data-boxover-company="X"><span class="flex"><a class="company-ticker" href="stock?t=%s&ty=c&p=d&b=1"><img src="x.svg" alt="logo"/><span>%s</span></a><a href="stock?t=%s&ty=c&p=d&b=1" class="tab-link">%s</a></span></td>%s</tr>' % (first, ticker, ticker, ticker[0], ticker, ticker, "".join("<td>%s</td>" % c for c in cells))
    table = '<table class="styled-table-new screener_table"><thead><tr>%s</tr></thead>%s</table>' % (head, body)
    pages = '<select id="pageSelect">' + "".join('<option%s value=%d>Page %d / %d</option>' % (' selected="selected"' if v == current else "", v, i + 1, len(page_values)) for i, v in enumerate(page_values)) + "</select>"
    count = '<div id="screener-total" class="count-text">#%d / %d Total</div>' % (current, total) if total is not None else ""
    chosen = dict(f.split("_", 1) for f in selected_filters)
    filters = "".join('<select id="fs_%s"><option value="">Any</option><option%s value="%s">x</option></select>' % (key, ' selected="selected"' if key in chosen else "", chosen.get(key, "any")) for key in ("sec", "cap", "idx"))
    if not filter_controls:
        filters = ""
    signals = '<select id="signalSelect"><option%s value="screener?v=111&ft=4%s">None (all stocks)</option><option%s value="screener?v=111&s=ta_topgainers&ft=4">Top Gainers</option></select>' % ("" if signal else ' selected="selected"', "&f=" + echo if echo else "", ' selected="selected"' if signal == "ta_topgainers" else "")
    init = ""
    if columns is not None:
        init = '<script id="route-init-data" type="application/json">%s</script>' % json.dumps({"tableSettings": {"tableName": "screener-custom", "selectedColumns": columns, "columnsMap": COLUMNS_MAP, "categories": CATEGORIES}})
    return "<html><body>" + count + pages + signals + filters + init + table + "</body></html>"


COLUMNS_MAP = {"row": {"id": "row", "title": "No.", "index": 0, "categoryIndex": 0}, "ticker": {"id": "ticker", "title": "Ticker", "index": 1, "categoryIndex": 0}, "company": {"id": "company", "title": "Company", "index": 2, "categoryIndex": 0}, "marketCap": {"id": "marketCap", "title": "Market Cap", "index": 6, "categoryIndex": 1}, "PE": {"id": "PE", "title": "P/E", "index": 7, "categoryIndex": 1}}
CATEGORIES = [{"id": "identification-classification", "title": "Identification & Classification"}, {"id": "valuation", "title": "Valuation"}]


METRICS = [("Market Cap", "41.39B", "Market capitalization"), ("EPS next Y", "6.74", "EPS estimate for next year"), ("EPS this Y", "10.95%", "EPS growth this year"), ("EPS next Y", "8.75%", "EPS growth next year"), ("EPS Q/Q", "8.50%", "Quarterly earnings growth (YoY)")]


def stock_overview(ticker="A", name="Agilent Technologies Inc", last_close="147.00", date="Sep 15 • 6:05 AM ET", change="+0.20 (0.14%)", metrics=METRICS, ratings=(("Sep-09-26", "Resumed", "UBS", "Neutral", "$165"),), news=(("Sep-14-26 04:30PM", "Keysight stock underperforms", "https://www.marketwatch.com/x", "MarketWatch"),), insiders=(("Dolsten Mikael", "Director", "Sep 04 '26", "Sale", "151.38", "634", "95,972", "4,924", "Sep 09 04:01 PM", "http://www.sec.gov/Archives/edgar/data/1/form4.xml"),), profile="Agilent Technologies, Inc. engages in life sciences.", peers=("WAT", "MTD"), ownership=None, insider_monthly=None, fundflows=None, ratings_table=True):
    header = '<div class="quote-header-wrapper"><h1 class="quote-header_ticker-wrapper_ticker" data-ticker="%s">%s</h1><h2 class="quote-header_ticker-wrapper_company"><a href="http://example.com">%s</a></h2><div class="quote-price"><strong class="quote-price_price">%s</strong><span class="quote-price_date">%s</span><span class="quote-price_change">%s</span></div></div>' % (ticker, ticker, name, last_close, date, change)
    cells = "".join('<tr><td data-boxover-html="%s">%s</td><td><b>%s</b></td></tr>' % (d, label, v) for label, v, d in metrics)
    snapshot = '<table class="snapshot-table2">%s</table>' % cells
    rating_rows = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in row) for row in ratings)
    ratings_html = '<table class="js-table-ratings"><thead><tr><th>Date</th><th>Action</th><th>Analyst</th><th>Rating Change</th><th>Price Target Change</th></tr></thead>%s</table>' % rating_rows if ratings_table else ""
    news_rows = "".join('<tr><td>%s</td><td><div class="news-link-left"><a class="tab-link-news" href="%s">%s</a></div><div class="news-link-right"><span>(%s)</span></div></td></tr>' % (t, u, h, s) for t, h, u, s in news)
    news_html = '<table id="news-table" class="fullview-news-outer news-table">%s</table>' % news_rows
    insider_rows = "".join('<tr class="fv-insider-row"><td><a class="tab-link" href="insidertrading?oc=1437590&tc=7">%s</a></td><td>%s</td><td>%s</td><td><span>%s</span></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><a class="tab-link" href="%s">%s</a></td></tr>' % (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[9], r[8]) for r in insiders)
    insider_html = '<table class="body-table styled-table-new"><thead><tr><th>Insider Trading</th><th>Relationship</th><th>Date</th><th>Transaction</th><th>Cost</th><th>#Shares</th><th>Value ($)</th><th>#Shares Total</th><th>SEC Form 4</th></tr></thead>%s</table>' % insider_rows
    profile_html = '<td class="fullview-profile quote_profile">%s</td><div class="fullview-links"><a href="screener?t=A,WAT,MTD">Peers</a>%s</div>' % (profile, "".join('<a href="stock?t=%s&ty=c&ta=1&p=d">%s</a>' % (p, p) for p in peers))
    scripts = ""
    for script_id, payload in (("institutional-ownership-init-data-0", ownership), ("insider-init-data-0", insider_monthly), ("route-init-data-fundflows-0", fundflows)):
        if payload is not None:
            scripts += '<script id="%s" type="application/json">%s</script>' % (script_id, json.dumps(payload))
    return "<html><body>" + header + snapshot + profile_html + ratings_html + news_html + insider_html + scripts + "</body></html>"


def stock_section(payload, ticker="A", metrics=METRICS):
    header = '<div class="quote-header-wrapper"><h1 class="quote-header_ticker-wrapper_ticker" data-ticker="%s">%s</h1></div>' % (ticker, ticker)
    snapshot = '<table class="snapshot-table2">%s</table>' % "".join('<tr><td data-boxover-html="%s">%s</td><td><b>%s</b></td></tr>' % (d, label, v) for label, v, d in metrics)
    return '<html><body>%s%s<script id="route-init-data" type="application/json">%s</script></body></html>' % (header, snapshot, json.dumps(payload))


def groups_page(rows=(("Basic Materials", "sec_basicmaterials", ["291", "2882.47B", "1.93%"]), ("Technology", "sec_technology", ["800", "30000.00B", "0.70%"])), headers=("No.", "Name", "Stocks", "Market Cap", "Dividend"), selected_group="groups?g=sector&v=110&o=name&st=d1", sort=("name", "ascending")):
    head = "".join('<th class="table-header%s" onclick="window.location=\'groups?g=sector&v=110&o=%s&st=d1\'">%s</th>' % (" is-selected is-" + sort[1] if h.lower() == sort[0] else "", ("-" if sort[1] == "ascending" else "") + h.lower().replace(" ", ""), h) for h in headers)
    body = "".join('<tr class="styled-row"><td>%d</td><td><a class="tab-link" href="screener?f=%s&v=111">%s</a></td>%s</tr>' % (i + 1, f, name, "".join("<td>%s</td>" % c for c in cells)) for i, (name, f, cells) in enumerate(rows))
    table = '<table class="styled-table-new groups_table"><thead><tr>%s</tr></thead>%s</table>' % (head, body)
    chosen = selected_group if isinstance(selected_group, tuple) else (selected_group,)
    groups = '<select id="groupSelect">' + "".join('<option%s value="%s">%s</option>' % (' selected="selected"' if v in chosen else "", v, t) for v, t in (("groups?g=sector&v=110&o=name&st=d1", "Sector"), ("groups?g=industry&v=110&o=name&st=d1", "Industry"), ("groups?g=industry&sg=basicmaterials&v=110&o=name&st=d1", "Industry (Basic Materials)"), ("groups?g=country&v=110&o=name&st=d1", "Country"), ("groups?g=capitalization&v=110&o=name&st=d1", "Capitalization"))) + "</select>"
    orders = '<select id="orderSelect"><option selected="selected" value="groups?g=sector&v=110&o=name&st=d1">Name</option><option value="groups?g=sector&v=110&o=marketcap&st=d1">Market Capitalization</option></select>'
    views = '<a href="groups?g=sector&v=110&o=name&st=d1">Overview</a><a href="groups?g=sector&v=120&o=name&st=d1">Valuation</a>'
    return "<html><body>" + groups + orders + views + table + "</body></html>"


def insiders_page(rows=(("ENLT", "Paz Amit", "2108367", "CHIEF INNOVATION OFFICER", "Sep 12 '26", "Sale", "42.10", "10,000", "421,000", "50,000", "Sep 14 09:55 PM", "http://www.sec.gov/Archives/edgar/data/1/x.xml"),), transaction="insidertrading?tc=7"):
    head = "".join("<th class=\"table-header\">%s</th>" % h for h in ("Ticker", "Owner", "Relationship", "Date", "Transaction", "Cost", "#Shares", "Value ($)", "#Shares Total", "SEC Form 4"))
    body = "".join('<tr class="fv-insider-row"><td data-boxover-ticker="%s"><span class="flex"><span class="company-ticker"><img src="x.svg"/><span>%s</span></span><a class="tab-link" href="stock?t=%s&b=2">%s</a></span></td><td><a class="tab-link" href="insidertrading?oc=%s&tc=7&b=2">%s</a></td><td>%s</td><td>%s</td><td><span>%s</span></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td><a class="tab-link" href="%s">%s</a></td></tr>' % (r[0], r[0][0], r[0], r[0], r[2], r[1], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[11], r[10]) for r in rows)
    control = '<select id="transactionFilter">' + "".join('<option%s value="%s">%s</option>' % (' selected="selected"' if v == transaction else "", v, t) for v, t in (("insidertrading?tc=7", "All Transactions"), ("insidertrading?tc=1", "Buy Transactions"), ("insidertrading?tc=2", "Sale Transactions"))) + "</select>"
    return '<html><body>%s<table id="insider-table" class="styled-table-new"><thead><tr>%s</tr></thead>%s</table></body></html>' % (control, head, body)


def news_page(items=(("06:56AM", "Stocks Fall as Oil Rally", "https://www.bloomberg.com/a", "Bloomberg", ()), ("06:30AM", "Paramount Dividend Analysis", "https://finance.yahoo.com/b", "GuruFocus.com", ("PSKY",))), sections=("News", "Blogs"), by_source=False):
    def row(t, title, url, source, tickers):
        badges = "".join('<a class="fv-label stock-news-label" data-boxover-ticker="%s" href="/stock?t=%s"><span>%s</span></a>' % (k, k, k) for k in tickers)
        return '<tr class="styled-row news_table-row"><td class="news_first-time-cell"><svg><use href="/assets/icons_news.svg#%s-light"></use></svg></td><td class="news_date-cell">%s</td><td class="news_link-cell"><a class="nn-tab-link" href="%s" onclick="trackAndOpenNews(event, \'%s\', \'%s\')">%s</a>%s</td></tr>' % (source.lower().split(".")[0], t, url, source, url, title, badges)
    if by_source:
        tables = "".join('<table class="styled-table-new break-inside-avoid-column"><tr class="news_table-row"><td class="news_heading-cell"><div><a href="https://%s.example/">%s</a></div></td></tr>%s</table>' % (source.lower(), source, row(t, title, url, source, tickers)) for t, title, url, source, tickers in items)
        return "<html><body>" + tables + "</body></html>"
    headings = "".join('<span class="news-calendar_heading">%s</span>' % h for h in sections)
    half = (len(items) + 1) // 2
    tables = "".join('<table class="styled-table-new">%s</table>' % "".join(row(*i) for i in chunk) for chunk in (items[:half], items[half:]) if chunk)
    return "<html><body>" + headings + tables + "</body></html>"


def pulse_page(items=((285611, "7 min", "VEON signs memorandum", ("VEON",)), (285537, "2 hours", "US equity futures point lower", ("$MARKET",)))):
    rows = "".join('<tr class="news_table-row" data-wiim-trigger="%d"><td class="news_icon-cell"></td><td class="news_date-cell">%s</td><td class="news_link-cell"><div><span class="market-pulse-headline">%s</span><div class="market-pulse-badges">%s<span class="market-pulse-more-link">More +</span></div></div></td></tr>' % (i, age, head, "".join('<a class="fv-label stock-news-label" data-boxover-ticker="%s" href="/stock?t=%s"><span>%s</span></a>' % (k, k, k) for k in tickers)) for i, age, head, tickers in items)
    return '<html><body><table class="styled-table-new">%s</table></body></html>' % rows


def article_page(title="Fed Decision Preview", paragraphs=("First paragraph.", "Second paragraph."), links=(("SEC filing", "https://www.sec.gov/x"),)):
    return '<html><body><h1>%s</h1><article>%s%s<img src="/img/chart.png"/></article></body></html>' % (title, "".join("<p>%s</p>" % p for p in paragraphs), "".join('<a href="%s">%s</a>' % (u, t) for t, u in links))


def calendar_page(payload):
    return '<html><body><script id="route-init-data" type="application/json">%s</script></body></html>' % json.dumps(payload)


def map_page(scripts=("/assets/dist-legacy/4740.v1.b05b832c.js", "/assets/dist-legacy/runtime.v1.22f44280.js", "/assets/dist-legacy/1378.v1.61170fe2.js", "/assets/dist-legacy/map.v1.aaaa1111.js")):
    return "<html><body>" + "".join('<script defer src="%s"></script>' % s for s in scripts) + "</body></html>"


MAP_LOADER = 'var IZ={World:1,SectorFull:2};switch(t){case IZ.World:return n.e(62).then(x);case IZ.SectorFull:return n.e(63).then(y);default:return n.e(61).then(z)}'
MAP_RUNTIME = 'r.u=function(e){return e+".v1."+{61:"aaa111",62:"bbb222",63:"ccc333"}[e]+".js"}'
MAP_CHUNK = 'module.exports={name:"Root",children:[{name:"World",children:[{name:"Canada",children:[{name:"RY",description:"Royal Bank Of Canada",value:294647}]}]}]};'
