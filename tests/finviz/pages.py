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
