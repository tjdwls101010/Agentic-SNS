"""Shared Finviz HTML extraction: tables as header-keyed records, snapshot metrics, embedded JSON, selects and articles."""

import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from transport import unique_object

STOCK_PATHS = ("/stock", "/quote.ashx")


def text(node):
    return node.get_text(" ", strip=True) if node else ""


def soup(obs):
    """Parse a page and refuse verification screens; page structure problems are reported by the callers."""
    page = BeautifulSoup(obs.text, "html.parser")
    if page.select_one("#challenge-form, #cf-challenge-running") or "just a moment" in text(page.title).lower():
        raise obs.fail("access_restricted", "Finviz returned a verification page instead of data.", "Wait before retrying and do not bypass the verification; the raw page is saved.")
    return page


def script_json(page, obs, script_id):
    node = page.select_one("script#" + script_id)
    if node is None:
        raise obs.fail("structure_changed", "The page has no script#" + script_id + " block.", "Read the saved raw page with read ID --raw; Finviz may have changed this page or it may require an account.")
    try:
        return json.loads(node.string or node.get_text(), object_pairs_hook=unique_object)
    except ValueError as exc:
        raise obs.fail("parse_error", "script#" + script_id + " is not valid JSON: " + str(exc)[:200], "Read the saved raw page with read ID --raw.")


def cell_text(cell):
    for icon in cell.select(".company-ticker, img, svg"):
        icon.decompose()
    return text(cell)


def ticker_of(row, base):
    node = row.select_one("[data-boxover-ticker]")
    if node is not None and node.get("data-boxover-ticker"):
        return node["data-boxover-ticker"]
    for link in row.select("a[href]"):
        parts = urlsplit(urljoin(base, link["href"]))
        if parts.path in STOCK_PATHS:
            return parse_qs(parts.query).get("t", [None])[0]
    return None


def unique_headers(headers):
    seen, names = {}, []
    for header in headers:
        seen[header] = seen.get(header, 0) + 1
        names.append(header if seen[header] == 1 else header + " #" + str(seen[header]))
    return names


def table_records(table, base, with_links=False):
    """Rows keyed by header text; a ticker column is normalised through the row's own ticker attribute or stock link."""
    headers = unique_headers([text(th) for th in table.select("thead th")] or [text(th) for th in table.select("th")])
    records = []
    for tr in table.select("tr"):
        cells = tr.find_all("td", recursive=False)
        if not cells:
            continue
        ticker = ticker_of(tr, base)
        links = [{"text": text(a), "url": urljoin(base, a["href"])} for a in tr.select("a[href]")]
        values = [cell_text(td) for td in cells]
        record = dict(zip(headers, values)) if headers and len(headers) == len(values) else {"cells": values}
        if ticker:
            record["ticker"] = ticker
            if "Ticker" in record:
                record["Ticker"] = ticker
            record["url"] = next((link["url"] for link in links if urlsplit(link["url"]).path in STOCK_PATHS), None)
        if with_links:
            record["links"] = [link for link in links if urlsplit(link["url"]).path not in STOCK_PATHS]
        records.append(record)
    return headers, records


def metrics(page):
    """Snapshot metrics as ordered records; repeated labels stay separate because Finviz reuses names with different definitions."""
    found = []
    for row in page.select(".snapshot-table2 tr"):
        cells = row.find_all("td", recursive=False)
        for i in range(0, len(cells) - 1, 2):
            label, value = cells[i], cells[i + 1]
            raw = text(value)
            definition = label.get("data-boxover-html")
            found.append({"label": text(label), "value": raw, "definition": text(BeautifulSoup(definition, "html.parser")) if definition else None, "unit": "%" if raw.endswith("%") else None})
    return found


def selects(page):
    controls = {}
    for select in page.select("select[id]"):
        controls[select["id"]] = [{"value": o.get("value", ""), "label": text(o), "selected": o.has_attr("selected"), "elite_only": o.has_attr("data-elite-only")} for o in select.select("option")]
    return controls


def query_param(url, key):
    return parse_qs(urlsplit(url).query, keep_blank_values=True).get(key, [None])[-1]


def article(page, base):
    body = page.select_one("article, .text-justify")
    if body is None:
        return None
    # Paragraphs only: the text outside them is link labels, which links already carries.
    return {"title": text(page.h1), "paragraphs": [text(p) for p in body.select("p")], "links": [{"text": text(a), "url": urljoin(base, a["href"])} for a in body.select("a[href]")], "images": [urljoin(base, img["src"]) for img in body.select("img[src]")]}


def total_count(page):
    node = page.select_one("#screener-total")
    match = re.search(r"/\s*([\d,]+)\s*Total", text(node)) if node else None
    return int(match.group(1).replace(",", "")) if match else None


def table_with_header(page, header):
    """The innermost table whose own header cells include `header`; Finviz nests data tables inside layout tables."""
    for table in reversed(page.select("table")):
        if any(markup_text == header for markup_text in (text(th) for th in table.select("th") if th.find_parent("table") is table)):
            return table
    return None


def sort_keys(table):
    """Column label -> the source sort key its header link carries; static headers have none and are left out."""
    found = {}
    for header in table.select("th[onclick]"):
        key = query_param("https://finviz.com/" + header["onclick"].split("'")[1], "o") if "'" in header.get("onclick", "") else None
        if key:
            found[text(header)] = key.lstrip("-")
    return found


def sort_condition(requested, page, controls):
    """Confirm a sort key from the selected header (its toggle link names the key; a leading - means it is currently ascending) or the order control."""
    key = requested.lstrip("-")
    wanted = "descending" if requested.startswith("-") else "ascending"
    header = page.select_one("th.table-header.is-selected")
    chosen = [o for o in controls.get("orderSelect", []) if o["selected"] and query_param(o["value"], "o")]
    if header is not None and "o=" in header.get("onclick", ""):
        toggled = query_param("https://finviz.com/" + header["onclick"].split("'")[1], "o") or ""
        classes = header.get("class", [])
        direction = "descending" if "is-descending" in classes else "ascending" if "is-ascending" in classes else ("ascending" if toggled.startswith("-") else "descending")
        observed = {"column": text(header), "key": toggled.lstrip("-"), "direction": direction}
    elif chosen:
        value = query_param(chosen[0]["value"], "o")
        observed = {"column": chosen[0]["label"], "key": value.lstrip("-"), "direction": "descending" if value.startswith("-") else "ascending"}
    else:
        observed = None
    status = ("confirmed" if observed["key"] == key and observed["direction"] == wanted else "not_applied") if observed else "unverified"
    return {"requested": requested, "status": status, "evidence": observed}
