"""News headlines, Market Pulse explanations and Finviz-hosted articles."""

import re
from urllib.parse import urlencode, urljoin

import markup
from contract import Collection, Selector, leaf
from transport import Failure, validate_url

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


def per_section(records, keep, context):
    """The first `keep` headlines of each section in page order: which list a headline came from is part of what it means."""
    if not keep:
        return records
    seen = {}
    kept = []
    for record in records:
        seen[record.get("section")] = seen.get(record.get("section"), 0) + 1
        if seen[record.get("section")] <= keep:
            kept.append(record)
    return kept


@leaf(
    "news",
    "headlines",
    help="News headlines by time, by source, or the stock, ETF and crypto news lists.",
    args=[(("--kind",), dict(default="latest", choices=list(NEWS_VIEWS), help="Which news list to read."))],
    collections={"headlines": Collection("{time, title, url, source, section, tickers} in page order, newest first within each section; url is the external article and tickers are Finviz's tagged symbols", local=[Selector(("--per-section",), dict(type=int, default=20, help="Keep the first N headlines of each section so no section drops out; 0 keeps every headline."), per_section)])},
)
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
    obs.result["target"], obs.result["collections"] = args.kind, {"headlines": items}
    return obs.result


@leaf(
    "news",
    "pulse",
    help="Market Pulse: Finviz's generated explanations of why stocks and the market moved; list the latest or read one by ID.",
    args=[(("id",), dict(nargs="?", metavar="ID", help="Pulse ID from the list; omitted lists the latest entries."))],
    collections={"entries": Collection("listed: {id, age, headline, tickers}; one ID: {id, ticker, dateTime, headline, summary (markdown), source, sentiment, catalyst, bulletPointsList} as published, a source-generated explanation rather than independent evidence")},
)
def pulse(ctx, args, target):
    if args.id:
        if not args.id.isdigit():
            raise Failure("invalid_argument", "A pulse ID is numeric.", "Use an id from news pulse.")
        obs = ctx.observe("https://finviz.com/api/stocks-why-moving/by-id/" + args.id)
        entry = obs.json()
        obs.result["target"], obs.result["collections"] = args.id, {"entries": [entry] if isinstance(entry, dict) else []}
        return obs.result
    obs = ctx.observe("https://finviz.com/news?v=6")
    page = markup.soup(obs)
    items = [{"id": int(row["data-wiim-trigger"]), "age": markup.text(row.select_one(".news_date-cell")), "headline": markup.text(row.select_one(".market-pulse-headline")), "tickers": [a["data-boxover-ticker"] for a in row.select("[data-boxover-ticker]")]} for row in page.select("tr[data-wiim-trigger]") if str(row.get("data-wiim-trigger", "")).isdigit()]
    if not items:
        raise obs.fail("structure_changed", "No Market Pulse rows were found.", "Read the saved raw page with read ID --raw.")
    obs.result["target"], obs.result["collections"] = "pulse", {"entries": items}
    return obs.result


@leaf(
    "news",
    "article",
    help="Read a Finviz-hosted article (finviz.com/news/<id>/<slug>); other hosts need their own reader.",
    args=[(("url",), dict(metavar="URL", help="Article URL on finviz.com."))],
    collections={"paragraphs": Collection("{text} per paragraph as displayed")},
    context={"title": "the article headline", "links, images": "links and images inside the body; text outside the paragraphs is a link label and appears there"},
)
def article(ctx, args, target):
    validate_url(args.url)
    if not re.fullmatch(r"/news/\d+/[\w-]+", args.url.split("finviz.com", 1)[-1].split("?")[0]):
        raise Failure("unsupported_url", "news article reads finviz.com/news/<id>/<slug> pages only.", "Take the url of a Finviz-hosted headline; other hosts need their own reader.")
    obs = ctx.observe(args.url)
    body = markup.article(markup.soup(obs), obs.url)
    if body is None:
        raise obs.fail("structure_changed", "No article body was found at this URL.", "Read the saved raw page with read ID --raw.")
    obs.result["target"] = args.url
    obs.result["context"] = {"title": body["title"], "links": body["links"], "images": body["images"]}
    obs.result["collections"] = {"paragraphs": [{"text": p} for p in body["paragraphs"]]}
    return obs.result
