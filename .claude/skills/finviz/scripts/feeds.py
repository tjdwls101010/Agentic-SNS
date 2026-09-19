"""Calendars, news headlines, Market Pulse, Finviz-hosted articles, market-wide insider trades and the generic URL reader."""

import re
from urllib.parse import urlencode, urljoin, urlsplit

import markup
from finviz import condition, leaf
from transport import Failure, PAGES, validate_url

CALENDAR_PATHS = {"earnings": "/calendar/earnings", "dividends": "/calendar/dividends", "economic": "/calendar/economic", "season": "/calendar/earnings/season-preview"}


DATE_FIELDS = {"earnings": "earningsDate", "dividends": "exdate", "economic": "date", "season": "date"}


CALENDAR_ARGS = [(("--date",), dict(default=None, help="Start date YYYY-MM-DD; the page states back the start date it used as date_from, and the date condition is judged from that echo. Not accepted by season.")), (("--page",), dict(type=int, default=1, help="One-based page from a previous continuation; pages after the first come from the calendar API, which states back no date or sort, so those conditions stay unverified. Values other than 1 are rejected by economic and season.")), (("--sort",), dict(default=None, help="Source sort key, e.g. earningsDate or -earningsDate; the page states the applied sort back as evidence."))]
CALENDAR_HELP = {"earnings": "Earnings calendar: report dates with EPS and sales estimates, actuals and surprises.", "dividends": "Dividend calendar: ex-dates with ordinary and special amounts and yields.", "economic": "Economic calendar: events with actual, previous and forecast values.", "season": "Earnings season preview: upcoming report counts per day with estimates."}
CALENDAR_OUTPUT = {"date_from": "the start date the source states it used; null when the response states none, as the paging API does", "items": "source records: earnings carry epsEstimate/epsActual/salesEstimate and isEarningDateEstimate; dividends carry exdate, ordinary, special, yield; economic carry event, actual, previous, forecast; season carries date and estimates", "totals_per_day": "season only: report counts per day"}


def calendar_leaf(kind):
    return leaf("calendar", kind, help=CALENDAR_HELP[kind], args=CALENDAR_ARGS, output=CALENDAR_OUTPUT, records="items", narrow=["--limit", "--fields", "--filter"], context=["date_from"], default_limit=40)


def calendar(ctx, args, target):
    args.kind = args.leaf
    if args.kind == "economic" and args.page != 1:
        raise Failure("invalid_argument", "The economic calendar has no pagination.", "Omit --page; narrow with --date, --filter or --limit.")
    if args.kind == "season" and (args.date or args.page != 1 or args.sort):
        raise Failure("invalid_argument", "The season preview has no date, page or sort selectors.", "Run calendar season without them; select locally with --filter or --limit.")
    # 성진: 페이지가 dateFrom·sort를 적용하고 그 값을 route-init-data에 되비추므로 1페이지는 페이지에서 읽는다. API는 되비추는 값이 없어 페이지를 넘길 때만 쓴다.
    use_api = args.page != 1
    date_from = args.date
    if use_api and not date_from:
        page_obs, page_data = calendar_page_data(ctx, args.kind)
        date_from = page_data.get("initialDateFrom")
        if not date_from:
            raise page_obs.fail("structure_changed", "The calendar page does not state its default date.", "Pass --date explicitly.")
    if use_api:
        query = {"dateFrom": date_from, "page": args.page, "sort": args.sort or ("earningsDate" if args.kind == "earnings" else None)}
        obs = ctx.observe("https://finviz.com/api/calendar/" + args.kind + "?" + urlencode({k: v for k, v in query.items() if v is not None}))
        root = obs.json()
        entries = root if isinstance(root, dict) else None
        items = root.get("items", []) if isinstance(root, dict) else root
        data = {}
        stated_date, stated_sort = (None if args.date else date_from), None  # the API states no start date of its own
    else:
        obs, data = calendar_page_data(ctx, args.kind, {"dateFrom": args.date, "sort": args.sort})
        entries = data.get("entries") if isinstance(data.get("entries"), dict) else None
        items = entries.get("items", []) if entries else (data.get("entries") or [])
        stated_date, stated_sort = data.get("initialDateFrom"), data.get("initialSort")
        date_from = stated_date
    if not isinstance(items, list):
        raise obs.fail("structure_changed", "The calendar response has no item list.", "Read the saved raw response with read ID --raw.")
    obs.result["target"] = args.kind
    obs.result["data"] = {"date_from": stated_date, "items": items}
    if args.kind == "season":
        obs.result["data"]["totals_per_day"] = data.get("totalsPerDay")
    conditions = {}
    if args.date:
        conditions["date"] = echoed_condition(args.date, stated_date, "source_date_from")
    if args.page != 1 or (use_api and args.kind != "economic"):
        observed = entries.get("page") if entries else None
        conditions["page"] = condition(args.page, ("confirmed" if observed == args.page else "not_applied") if observed is not None else "unverified", observed)
    if args.sort:
        conditions["sort"] = echoed_condition(args.sort, stated_sort, "source_sort")
    obs.result["conditions"] = conditions
    coverage = {"received": len(items), "exhaustive": False}
    if entries:
        total_pages = entries.get("totalPages")
        coverage["source_total"] = entries.get("totalItemsCount")
        coverage["pagination_end"] = entries.get("page") == total_pages if total_pages else None
        if total_pages and (entries.get("page") or 0) < total_pages:
            obs.result["continuation"] = {"page": entries["page"] + 1}
    elif data and data.get("totalCount") is not None:
        coverage["source_total"] = data["totalCount"]
    obs.result["coverage"] = coverage
    return obs.result


for _kind in CALENDAR_PATHS:
    calendar_leaf(_kind)(calendar)


def echoed_condition(requested, stated, evidence_key):
    """Judge a selector by the value the source states back, never by whether the returned rows happen to satisfy it."""
    if stated is None:
        return condition(requested, "unverified", None)
    return condition(requested, "confirmed" if str(stated) == str(requested) else "not_applied", {evidence_key: stated})


def calendar_page_data(ctx, kind, query=None):
    parameters = urlencode({k: v for k, v in (query or {}).items() if v is not None})
    obs = ctx.observe("https://finviz.com" + CALENDAR_PATHS[kind] + ("?" + parameters if parameters else ""))
    root = markup.script_json(markup.soup(obs), obs, "route-init-data")
    data = root.get("data") if isinstance(root, dict) else None
    if not isinstance(data, dict):
        raise obs.fail("structure_changed", "The calendar page has no data block.", "Read the saved raw page with read ID --raw.")
    return obs, data


NEWS_VIEWS = {"latest": None, "by-source": "2", "stocks": "3", "etfs": "4", "crypto": "5"}


def source_of(row):
    for node in [row] + row.select("a[onclick]"):
        match = re.search(r"trackAndOpenNews\(\s*event\s*,\s*'([^']+)'", node.get("onclick") or "")
        if match:
            return match.group(1)
    icon = row.select_one("use[href*='#']")
    if icon is not None:
        return icon["href"].split("#")[-1].removesuffix("-light").removesuffix("-dark") or None
    return None


@leaf("news", "headlines", help="News headlines by time, by source, or the stock, ETF and crypto news lists.", args=[(("--kind",), dict(default="latest", choices=list(NEWS_VIEWS), help="Which news list to read."))], output={"[]": "{time, title, url, source, section, tickers} in page order; url is the external article, tickers are Finviz's tagged symbols. Without --limit the newest headlines of every section are kept, so no section disappears from the list."}, narrow=["--filter", "--limit", "--fields"])
def headlines(ctx, args, target):
    view = NEWS_VIEWS[args.kind]
    obs = ctx.observe("https://finviz.com/news" + ("?" + urlencode({"v": view}) if view else ""))
    page = markup.soup(obs)
    headings = [markup.text(h) for h in page.select(".news-calendar_heading")]
    items = []
    tables = [t for t in page.select("table") if any(tr.find_parent("table") is t for tr in t.select("tr.news_table-row"))]
    for index, table_node in enumerate(tables):
        heading = table_node.select_one(".news_heading-cell")
        section = markup.text(heading) if heading is not None else (headings[index] if index < len(headings) else None)
        for row in table_node.select("tr.news_table-row"):
            link = row.select_one("a.nn-tab-link, a.tab-link-news")
            if link is None:
                continue
            time_cell = row.select_one(".news_date-cell")
            items.append({"time": markup.text(time_cell), "title": markup.text(link), "url": urljoin(obs.url, link["href"]), "source": source_of(row) or (markup.text(heading) if heading is not None else None), "section": section, "tickers": [a["data-boxover-ticker"] for a in row.select("[data-boxover-ticker]")]})
    if not items:
        raise obs.fail("structure_changed", "No news rows were found.", "Read the saved raw page with read ID --raw.")
    obs.result["coverage"] = {"received": len(items)}
    obs.result["target"], obs.result["data"] = args.kind, across_sections(items, args.limit or 40)
    return obs.result


def across_sections(items, keep):
    """Keep `keep` headlines without losing a section: which list a headline came from is part of what it means, and the sections are concatenated, not interleaved."""
    if len(items) <= keep:
        return items
    sections = {}
    for position, item in enumerate(items):
        sections.setdefault(item.get("section"), []).append(position)
    chosen, depth = set(), 0
    while len(chosen) < keep and any(len(positions) > depth for positions in sections.values()):
        for positions in sections.values():
            if depth < len(positions) and len(chosen) < keep:
                chosen.add(positions[depth])
        depth += 1
    return [item for position, item in enumerate(items) if position in chosen]


@leaf("news", "pulse", help="Market Pulse: Finviz's generated explanations of why stocks and the market moved; list them or read one by ID.", args=[(("id",), dict(nargs="?", help="Pulse ID from the list; omitted lists the latest entries."))], output={"[] (list)": "{id, age, headline, tickers}", "{} (one ID)": "{id, ticker, dateTime, headline, summary (markdown), source, sentiment, catalyst, bulletPointsList} as published; a source-generated explanation, not independent evidence"}, narrow=["--filter", "--limit"])
def pulse(ctx, args, target):
    if args.id:
        if not args.id.isdigit():
            raise Failure("invalid_id", "A pulse ID is numeric.", "Use an id from news pulse.")
        obs = ctx.observe("https://finviz.com/api/stocks-why-moving/by-id/" + args.id)
        obs.result["target"], obs.result["data"] = args.id, obs.json()
        return obs.result
    obs = ctx.observe("https://finviz.com/news?v=6")
    page = markup.soup(obs)
    items = [{"id": int(row["data-wiim-trigger"]), "age": markup.text(row.select_one(".news_date-cell")), "headline": markup.text(row.select_one(".market-pulse-headline")), "tickers": [a["data-boxover-ticker"] for a in row.select("[data-boxover-ticker]")]} for row in page.select("tr[data-wiim-trigger]") if str(row.get("data-wiim-trigger", "")).isdigit()]
    if not items:
        raise obs.fail("structure_changed", "No Market Pulse rows were found.", "Read the saved raw page with read ID --raw.")
    obs.result["target"], obs.result["data"] = "pulse", items
    return obs.result


@leaf("news", "article", help="Read a Finviz-hosted article (finviz.com/news/<id>/<slug>); other hosts need their own reader.", args=[(("url",), dict(help="Article URL on finviz.com."))], output={"title, paragraphs, text": "article body as displayed", "links, images": "links and images inside the body"})
def article(ctx, args, target):
    validate_url(args.url)
    obs = ctx.observe(args.url)
    body = markup.article(markup.soup(obs), obs.url)
    if body is None:
        raise obs.fail("structure_changed", "No article body was found at this URL.", "Read the saved raw page with read ID --raw; only finviz.com/news/<id>/<slug> pages carry an article.")
    obs.result["target"], obs.result["data"] = args.url, body
    return obs.result


TRANSACTIONS = {"all": "7", "buy": "1", "sale": "2"}


@leaf("insiders", "trades", help="Latest insider trades across the market, with owner pages and SEC Form 4 links.", args=[(("--transaction",), dict(default="all", choices=list(TRANSACTIONS), help="Transaction type.")), (("--owner",), dict(default=None, help="Owner id from a row's owner_url to list one insider's trades.")), (("--sort",), dict(default=None, help="Source sort key from the column header links, e.g. -transactiondate.")), (("--value",), dict(default=None, help="Source transaction-value threshold parameter."))], output={"[]": "rows keyed by the table headers plus ticker, url (stock page), owner_url and filing_url, newest first"}, narrow=["--filter", "--fields", "--limit"], default_limit=20)
def trades(ctx, args, target):
    query = {"tc": TRANSACTIONS[args.transaction], "oc": args.owner, "o": args.sort, "tv": args.value}
    obs = ctx.observe("https://finviz.com/insidertrading?" + urlencode({k: v for k, v in query.items() if v is not None}))
    page = markup.soup(obs)
    node = page.select_one("table#insider-table")
    if node is None:
        raise obs.fail("structure_changed", "No insider table was found.", "Read the saved raw page with read ID --raw.")
    headers, rows = markup.table_records(node, obs.url)
    trs = [tr for tr in node.select("tr") if tr.find_all("td", recursive=False)]
    for row, tr in zip(rows, trs):
        links = [urljoin(obs.url, a["href"]) for a in tr.select("a[href]")]
        row["owner_url"] = next((u for u in links if "insidertrading" in u), None)
        row["filing_url"] = next((u for u in links if "sec.gov" in u), None)
    controls = markup.selects(page)
    chosen = [o["label"] for o in controls.get("transactionFilter", []) if o["selected"]]
    conditions = {"transaction": condition(args.transaction, ("confirmed" if chosen and chosen[0].lower().startswith({"all": "all", "buy": "buy", "sale": "sale"}[args.transaction]) else "not_applied") if chosen else "unverified", chosen[0] if chosen else None)}
    for name in ("owner", "sort", "value"):
        if getattr(args, name):
            conditions[name] = condition(getattr(args, name))
    obs.result["target"], obs.result["conditions"], obs.result["data"] = args.transaction, conditions, rows
    return obs.result


@leaf("open", None, help="Read any supported finviz.com URL: JSON APIs come back as-is, pages through the generic extractor.", args=[(("url",), dict(help="HTTPS finviz.com URL to a screener, stock, groups, map, news, calendar, insider or market page or API.")), (("--all-links",), dict(action="store_true", help="Keep every link on the page instead of the first 50; a dense page carries a few hundred, mostly peer and view links that its own command returns as data."))], output={"JSON API": "the response as published", "page": "{metrics, tables: [{headers, rows}], initial: {script id: json}, controls: {select id: options}, article, links}; links_received counts the links before the 50-link default"}, narrow=["--fields"])
def open_url(ctx, args, target):
    validate_url(args.url)
    obs = ctx.observe(args.url)
    obs.result["target"] = args.url
    if obs.text.lstrip().startswith(("{", "[")):
        obs.result["data"] = obs.json()
        return obs.result
    page = markup.soup(obs)
    content = page.select("article, main, .text-justify")
    for chrome in page.select("nav, header, footer, .navbar"):
        if chrome.parent is not None and not any(node in content for node in chrome.parents) and not chrome.select_one("article, main, .text-justify"):
            chrome.decompose()
    # 성진: 본문 컨테이너 밖의 무쿼리 화면 링크를 메뉴로 본다; 본문 링크 오분류가 확인되면 사이트 메뉴 컨테이너로 범위를 좁힌다.
    for anchor in page.select("a[href]"):
        if any(node in content for node in anchor.parents):
            continue
        parts = urlsplit(urljoin(obs.url, anchor["href"]))
        if parts.hostname in ("finviz.com", "www.finviz.com") and ((parts.path in PAGES and not parts.query) or re.fullmatch(r"/(login|register|elite|help|contact|privacy|terms)(?:\.ashx)?/?", parts.path)):
            anchor.decompose()
    tables = []
    for node in page.select("table"):
        nested = node.select("table")
        if nested or "snapshot-table2" in node.get("class", []):
            continue
        headers, rows = markup.table_records(node, obs.url)
        if rows and markup.text(node):
            tables.append({"headers": headers, "rows": rows})
    initial = {}
    for script in page.select("script[id]"):
        text = script.string or script.get_text()
        if text.lstrip().startswith(("{", "[")):
            try:
                initial[script["id"]] = markup.script_json(page, obs, script["id"])
            except Exception:
                initial[script["id"]] = None
    links = [{"text": markup.text(a), "url": urljoin(obs.url, a["href"])} for a in page.select("a[href]") if markup.text(a)]
    data = {"metrics": markup.metrics(page), "tables": tables, "initial": initial, "controls": markup.selects(page), "article": markup.article(page, obs.url), "links": links if args.all_links else links[:50]}
    if not args.all_links and len(links) > 50:
        data["links_received"] = len(links)
    if not any((data["metrics"], tables, initial, data["controls"], data["article"])):
        raise obs.fail("structure_changed", "No supported data structure was found on this page.", "Read the saved raw page with read ID --raw; the page may be visual-only or require an account.")
    obs.result["data"] = data
    return obs.result


def is_article_url(url):
    return re.fullmatch(r"/news/\d+/[\w-]+", urlsplit(url).path) is not None
