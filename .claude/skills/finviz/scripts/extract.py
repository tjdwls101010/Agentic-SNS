"""Retain source fields and evidence while extracting Finviz read surfaces."""

import json
import re
from urllib.parse import parse_qs, urlsplit, urljoin, urlencode

from bs4 import BeautifulSoup

from runtime import Failure


def text(node):
    return node.get_text(" ", strip=True) if node else ""


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key: " + key)
        result[key] = value
    return result


def parse(result, raw):
    url = result["source"]["url"]
    query = {k: v["requested"] for k, v in result["conditions"].items()}
    content = raw.decode("utf-8-sig", errors="replace")
    if content.lstrip().startswith(("{", "[")):
        result["data"] = json.loads(content, object_pairs_hook=unique_object)
        source = result["data"]
        if urlsplit(url).path == "/api/quote" and isinstance(source, dict):
            lengths = {
                k: len(source[k])
                for k in ("date", "open", "high", "low", "close", "volume")
                if isinstance(source.get(k), list)
            }
            if "date" in lengths:
                result["coverage"].update(received=lengths["date"], shown=lengths["date"])
            if lengths and len(set(lengths.values())) > 1:
                raise Failure(
                    "array_alignment",
                    "Price/date arrays differ in length: " + str(lengths),
                    "Inspect the original arrays; do not zip or truncate them into aligned bars.",
                )
        metadata(result)
        return
    soup = BeautifulSoup(content, "html.parser")
    if soup.select_one("#challenge-form, #cf-challenge-running") or "just a moment" in text(soup.title).lower():
        raise Failure(
            "access_restricted",
            "Provider returned a verification page.",
            "Stop and inspect the source; do not bypass verification.",
        )
    scripts = {}
    for node in soup.select("script[id]"):
        value = node.string or node.get_text()
        if value.lstrip().startswith(("{", "[")):
            scripts[node["id"]] = json.loads(value, object_pairs_hook=unique_object)
    embedded = {}
    for script in soup.select("script:not([src])"):
        code = script.string or script.get_text()
        for name, pattern in {
            "map_performance": r"initialPerf:\s*",
            "group_performance": r"FinvizInitGroupsPerformance\(\s*",
        }.items():
            match = re.search(pattern, code)
            if match and code[match.end() :].startswith(("{", "[")):
                embedded[name] = json.JSONDecoder(object_pairs_hook=unique_object).raw_decode(code[match.end() :])[0]
    navigation = []
    for link in soup.select("a[href]"):
        target = urljoin(url, link["href"])
        if urlsplit(target).netloc in ("finviz.com", "www.finviz.com") and text(link):
            navigation.append(dict(label=text(link), url=target))
    controls = []
    for select in soup.select("select"):
        controls.append(
            dict(
                id=select.get("id"),
                name=select.get("name"),
                label=select.get("data-label"),
                options=[
                    dict(value=o.get("value", ""), label=text(o), selected=o.has_attr("selected"))
                    for o in select.select("option")
                ],
            )
        )
    metrics = []
    for row in soup.select(".snapshot-table2 tr"):
        cells = row.find_all("td", recursive=False)
        for i in range(0, len(cells) - 1, 2):
            label, value = cells[i], cells[i + 1]
            raw_value = text(value)
            definition = label.get("data-boxover-html")
            metrics.append(
                dict(
                    label=text(label),
                    value=raw_value,
                    definition=text(BeautifulSoup(definition, "html.parser")) if definition else None,
                    unit="%" if raw_value.endswith("%") else None,
                )
            )
    tables = []
    for table in soup.select(
        ".screener_table, .groups_table, #insider-table, .styled-table-new, #news-table, .news-table, .fullview-ratings-outer"
    ):
        if table.select("table"):
            continue
        rows = []
        headers = [text(n) for n in table.select("th")]
        for tr in table.select("tr"):
            cells = tr.find_all("td", recursive=False)
            if not cells:
                continue
            links = [dict(text=text(a), url=urljoin(url, a["href"])) for a in tr.select("a[href]")]
            ticker_node = tr.select_one("[data-boxover-ticker]")
            ticker = ticker_node.get("data-boxover-ticker") if ticker_node else None
            if not ticker:
                for link in links:
                    parts = urlsplit(link["url"])
                    if parts.path in ("/stock", "/quote.ashx"):
                        ticker = parse_qs(parts.query).get("t", [None])[0]
                        if ticker:
                            break
            rows.append(
                dict(ticker=ticker, pulse_id=tr.get("data-wiim-trigger"), cells=[text(c) for c in cells], links=links)
            )
        tables.append(dict(headers=headers, rows=rows))
    article = None
    if re.fullmatch(r"/news/\d+/[\w-]+", urlsplit(url).path):
        body = soup.select_one("article, .text-justify")
        if body:
            article = dict(
                title=text(soup.h1),
                paragraphs=[text(p) for p in body.select("p")],
                text=text(body),
                links=[dict(text=text(a), url=urljoin(url, a["href"])) for a in body.select("a[href]")],
                images=[urljoin(url, img["src"]) for img in body.select("img[src]")],
            )
    result["data"] = dict(
        article=article,
        embedded=embedded,
        navigation=navigation,
        initial=scripts,
        controls=controls,
        tables=tables,
        metrics=metrics,
    )
    if (
        not scripts
        and not tables
        and not controls
        and not metrics
        and not article
        and not embedded
        and not (urlsplit(url).path in ("/map", "/map.ashx", "/bubbles", "/bubbles.ashx") and navigation)
    ):
        result["data"] = None
        raise Failure(
            "structure_changed",
            "No supported data structure was found.",
            "Read the saved raw response; check whether this surface requires access or has changed.",
        )
    result["coverage"]["received"] = sum(len(t["rows"]) for t in tables) if tables else None
    result["coverage"]["shown"] = result["coverage"]["received"]
    if query.get("f"):
        requested = query["f"].split(",")
        selected = {
            c["id"][3:] + "_" + o["value"]
            for c in controls
            if (c["id"] or "").startswith("fs_")
            for o in c["options"]
            if o["selected"] and o["value"]
        }
        known = {c["id"][3:] for c in controls if (c["id"] or "").startswith("fs_")}
        if all(token.split("_", 1)[0] in known for token in requested):
            result["conditions"]["f"].update(
                status="confirmed" if set(requested) == selected else "not_applied", evidence=sorted(selected)
            )
    for node in walk(scripts):
        if (
            "c" in query
            and isinstance(node, dict)
            and isinstance(node.get("selectedColumns"), list)
            and isinstance(node.get("columnsMap"), dict)
        ):
            columns = [str(node["columnsMap"].get(key, {}).get("index")) for key in node["selectedColumns"]]
            if "None" not in columns:
                result["conditions"]["c"].update(
                    status="confirmed" if columns == query["c"].split(",") else "not_applied", evidence=columns
                )
    current = int(parse_qs(urlsplit(url).query).get("r", ["1"])[-1])
    candidates = []
    for a in soup.select("a[href]"):
        target = urljoin(url, a["href"])
        parts = urlsplit(target)
        params = {k: v[-1] for k, v in parse_qs(parts.query, keep_blank_values=True).items()}
        # Pagination may reorder query keys; all non-position conditions must match.
        page_query = {k: v[-1] for k, v in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}
        if parts.netloc == urlsplit(url).netloc and parts.path == urlsplit(url).path and params.get("r", "").isdigit():
            if {k: v for k, v in params.items() if k != "r"} == {
                k: v for k, v in page_query.items() if k != "r"
            } and int(params["r"]) > current:
                candidates.append((int(params["r"]), target))
    if candidates:
        result["continuation"] = min(candidates)[1]
    for c in controls:
        if c["id"] == "pageSelect":
            chosen = [o["value"] for o in c["options"] if o["selected"]]
            if chosen and "r" in result["conditions"]:
                result["conditions"]["r"].update(
                    status="confirmed" if chosen[0] == query["r"] else "not_applied", evidence=chosen[0]
                )

    evidence_keys = {"e": "currentExpiry", "page": "initialPage", "sort": "initialSort", "dateFrom": "initialDateFrom"}
    for key, field in evidence_keys.items():
        if key in result["conditions"]:
            evidence = [n[field] for n in walk(scripts) if isinstance(n, dict) and field in n]
            if evidence:
                result["conditions"][key].update(
                    status="confirmed" if str(evidence[0]) == query[key] else "not_applied", evidence=evidence[0]
                )

    metadata(result)


def metadata(result):
    data = result["data"]
    query = {k: v[-1] for k, v in parse_qs(urlsplit(result["source"]["url"]).query, keep_blank_values=True).items()}
    nodes = list(walk(data))
    for key, names in {
        "e": ["currentExpiry"],
        "page": ["initialPage", "page"],
        "dateFrom": ["initialDateFrom"],
        "sort": ["initialSort"],
    }.items():
        if key in result["conditions"]:
            evidence = [
                node[name]
                for node in nodes
                if isinstance(node, dict)
                for name in names
                if name in node and not isinstance(node[name], (dict, list))
            ]
            if evidence:
                result["conditions"][key].update(
                    status="confirmed" if str(evidence[0]) == result["conditions"][key]["requested"] else "not_applied",
                    evidence=evidence[0],
                )
    if isinstance(data, list):
        result["coverage"].update(received=len(data), shown=len(data))
    for node in nodes:
        if isinstance(node, dict) and isinstance(node.get("items"), list) and isinstance(node.get("page"), int):
            result["coverage"].update(
                received=len(node["items"]), shown=len(node["items"]), source_total=node.get("totalItemsCount")
            )
            if node["page"] < node.get("totalPages", node["page"]):
                query["page"] = str(node["page"] + 1)
                result["continuation"] = result["source"]["url"].split("?")[0] + "?" + urlencode(query)
            result["coverage"]["pagination_end"] = node["page"] >= node.get("totalPages", node["page"] + 1)
            break
