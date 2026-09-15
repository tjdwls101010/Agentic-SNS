"""Finviz screener: discovery of filters, signals, columns and views, and screening runs with condition evidence and paging."""

import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

import markup
import output
from finviz import condition, leaf
from transport import Failure

BASE = "https://finviz.com/screener"
VIEWS = {
    "overview": ("111", "Ticker, company, sector, industry, country, market cap, P/E, price, change, volume"),
    "valuation": ("121", "Valuation ratios: P/E, forward P/E, PEG, P/S, P/B, P/C, P/FCF, EPS and sales growth"),
    "ownership": ("131", "Shares outstanding and float, insider and institutional ownership and transactions, short float"),
    "performance": ("141", "Performance over week to year, volatility, relative volume, average volume"),
    "financial": ("161", "Dividend yield, ROA, ROE, ROI, current and quick ratios, debt, margins, payout"),
    "technical": ("171", "Beta, ATR, SMA distances, 52-week distances, RSI, price and change"),
    "etf": ("181", "ETF overview: category, sponsor, AUM, expense ratio, flows"),
    "etf-performance": ("191", "ETF performance over standard periods"),
    "custom": ("152", "Columns chosen with --columns; discover them with screen columns"),
}


def screener_page(ctx, query):
    url = BASE + "?" + urlencode({k: v for k, v in query.items() if v is not None}, safe=",")
    obs = ctx.observe(url)
    return obs, markup.soup(obs)


@leaf("screen", "filters", help="List the current screener filters: id, label, definition and the value strings --filters accepts.", output={"[]": "{id, label, definition, options: [{value, label}], elite_only: [labels]}; pass option values to screen run --filters"}, narrow=["--filter", "--limit"])
def filters(ctx, args, target):
    obs, page = screener_page(ctx, {"ft": "4"})
    found = []
    for select in page.select("select[id^=fs_]"):
        title = select.find_parent("td")
        title = title.find_previous_sibling("td").select_one(".screener-combo-title") if title is not None and title.find_previous_sibling("td") else None
        definition = title.get("data-boxover-html") if title is not None else None
        key = select["id"][3:]
        record = {"id": key, "label": markup.text(title) if title is not None else key, "definition": markup.text(markup.BeautifulSoup(definition, "html.parser")) if definition else None, "options": [{"value": key + "_" + o["value"], "label": markup.text(o)} for o in select.select("option") if o.get("value")]}
        elite = [markup.text(o) for o in select.select("option[data-elite-only]")]
        if elite:
            record["elite_only"] = elite
        found.append(record)
    if not found:
        raise obs.fail("structure_changed", "No filter controls were found on the screener page.", "Read the saved raw page with read ID --raw.")
    obs.result["target"], obs.result["data"] = "filters", found
    return obs.result


@leaf("screen", "signals", help="List the screener signals (top gainers, new high, unusual volume, patterns) that --signal accepts.", output={"[]": "{value, label}; pass value to screen run --signal"}, narrow=["--filter"])
def signals(ctx, args, target):
    obs, page = screener_page(ctx, {"ft": "4"})
    options = markup.selects(page).get("signalSelect")
    if not options:
        raise obs.fail("structure_changed", "No signal control was found on the screener page.", "Read the saved raw page with read ID --raw.")
    obs.result["target"] = "signals"
    obs.result["data"] = [{"value": markup.query_param(o["value"], "s"), "label": o["label"]} for o in options if markup.query_param(o["value"], "s")]
    return obs.result


@leaf("screen", "columns", help="List the columns available to the custom view: id, title, index and category.", output={"[]": "{id, title, index, category}; pass ids or indices to screen run --columns"}, narrow=["--filter", "--limit"])
def columns(ctx, args, target):
    obs, page = screener_page(ctx, {"v": "152"})
    obs.result["target"], obs.result["data"] = "columns", column_catalog(page, obs)
    return obs.result


def column_catalog(page, obs):
    settings = markup.script_json(page, obs, "route-init-data").get("tableSettings", {})
    categories = [c.get("title") for c in settings.get("categories", [])]
    return [{"id": c["id"], "title": c["title"], "index": c["index"], "category": categories[c["categoryIndex"]] if c.get("categoryIndex") is not None and c["categoryIndex"] < len(categories) else None} for c in settings.get("columnsMap", {}).values()]


@leaf("screen", "views", help="Describe the table views --view accepts; offline.", output={"[]": "{name, view_id, description}"})
def views(ctx, args, target):
    return output.plain("views", [{"name": name, "view_id": view_id, "description": description} for name, (view_id, description) in VIEWS.items()])


RUN_ARGS = [
    (("--filters",), dict(default=None, help="Comma-separated filter values from screen filters, e.g. sec_technology,cap_largeover.")),
    (("--signal",), dict(default=None, help="Signal value from screen signals, e.g. ta_topgainers.")),
    (("--view",), dict(default="overview", choices=list(VIEWS), help="Table view; custom is implied when --columns is given.")),
    (("--columns",), dict(default=None, help="Comma-separated column ids or indices from screen columns for the custom view.")),
    (("--sort",), dict(default=None, help="Sort key from the column header links, e.g. marketcap; write --sort=-marketcap for descending.")),
    (("--start",), dict(type=int, default=1, help="One-based row offset of the first page; take it from a previous continuation.")),
    (("--pages",), dict(type=int, default=1, help="Pages to fetch in this run, following continuations; 20 rows per page for anonymous access.")),
    (("--out",), dict(default=None, help="Write rows as JSON Lines to this path; stdout then carries only the summary.")),
    (("--append",), dict(action="store_true", help="Allow appending to an existing --out file; without it an existing file is refused.")),
]


@leaf("screen", "run", help="Run the screener with filters, a signal, a view or custom columns, sorting and paging; rows keep source strings.", args=RUN_ARGS, output={"[]": "one record per row keyed by the column headers, plus ticker and url; with --out the data is {path, rows_written, pages} instead", "conditions": "filters, signal, columns, sort and start as confirmed by the page's own controls", "coverage": "received rows, source_total from the page count, exhaustive false", "continuation": "{start} for the next page"}, narrow=["--fields", "--limit", "--out", "--pages 1"])
def run(ctx, args, target):
    if args.pages < 1:
        raise Failure("invalid_pages", "--pages must be at least 1.", "Use --pages 1 for a single page.")
    requested_columns = resolve_columns(ctx, args.columns)
    view = "152" if requested_columns else VIEWS[args.view][0]
    query = {"v": view, "ft": "4", "f": args.filters, "s": args.signal, "c": ",".join(map(str, requested_columns)) if requested_columns else None, "o": args.sort, "r": args.start}
    writer = Exporter(args) if args.out else None
    rows, page_ids, first, start = [], [], None, args.start
    for _ in range(args.pages):
        query["r"] = start
        obs, page = screener_page(ctx, query)
        headers, records = page_records(page, obs)
        first = first or obs
        page_ids.append(obs.id)
        if writer:
            writer.write(records, obs.id)
        else:
            rows.extend(records)
        evidence(obs, page, args, requested_columns, start)
        nxt = next_start(page, start)
        if nxt is None:
            start = None
            break
        start = nxt
    result = first.result
    result["target"] = "screen"
    result["coverage"] = {"received": len(rows) if not writer else writer.count, "source_total": markup.total_count(page), "exhaustive": False, "pages": len(page_ids)}
    if start is not None:
        result["continuation"] = {"start": start}
    result["source"]["pages"] = page_ids
    result["data"] = {"path": str(writer.path), "rows_written": writer.count, "pages": len(page_ids)} if writer else rows
    if writer:
        writer.close()
    return result


def resolve_columns(ctx, spec):
    if not spec:
        return None
    tokens = [t.strip() for t in spec.split(",") if t.strip()]
    if all(t.isdigit() for t in tokens):
        return [int(t) for t in tokens]
    obs, page = screener_page(ctx, {"v": "152"})
    catalog = {c["id"]: c["index"] for c in column_catalog(page, obs)}
    unknown = [t for t in tokens if not t.isdigit() and t not in catalog]
    if unknown:
        raise Failure("invalid_columns", "Unknown column ids: " + ", ".join(unknown) + ".", "Use ids or indices from screen columns.")
    return [int(t) if t.isdigit() else catalog[t] for t in tokens]


def page_records(page, obs):
    table = page.select_one("table.screener_table")
    if table is None:
        raise obs.fail("structure_changed", "No screener table was found.", "Read the saved raw page with read ID --raw; the view may not be a table view.")
    return markup.table_records(table, obs.url)


def evidence(obs, page, args, requested_columns, start):
    """Confirm each chosen parameter from the page's own controls; a missing control leaves the condition unverified."""
    controls = markup.selects(page)
    conditions = {}
    if args.filters:
        selected = sorted(key[3:] + "_" + o["value"] for key, options in controls.items() if key.startswith("fs_") for o in options if o["selected"] and o["value"])
        requested = sorted(f.strip() for f in args.filters.split(","))
        if any(k.startswith("fs_") for k in controls):
            conditions["filters"] = condition(args.filters, "confirmed" if requested == selected else "not_applied", selected or None)
        else:
            echoed = [markup.query_param(o["value"], "f") for o in controls.get("signalSelect", []) if o["selected"]]
            conditions["filters"] = condition(args.filters, "unverified", {"echoed_by_server": echoed[0]} if echoed and echoed[0] else None)
            obs.result.setdefault("warnings", []).append("This view has no filter controls, so the filters are unverified; the server echoed them but an unknown filter is echoed too. Run the same filters with --view overview to confirm them.")
    if args.signal:
        chosen = [markup.query_param(o["value"], "s") for o in controls.get("signalSelect", []) if o["selected"]]
        conditions["signal"] = condition(args.signal, ("confirmed" if chosen == [args.signal] else "not_applied") if "signalSelect" in controls else "unverified", chosen[0] if chosen else None)
    if requested_columns:
        try:
            settings = markup.script_json(page, obs, "route-init-data").get("tableSettings", {})
            indices = [settings["columnsMap"][c]["index"] for c in settings.get("selectedColumns", [])]
            conditions["columns"] = condition(args.columns, "confirmed" if indices == requested_columns else "not_applied", settings.get("selectedColumns"))
        except (Failure, KeyError):
            conditions["columns"] = condition(args.columns)
    if args.sort:
        header = page.select_one("th.table-header.is-selected")
        key = args.sort.lstrip("-")
        if header is not None and "o=" in header.get("onclick", ""):
            toggled = markup.query_param("https://finviz.com/" + header["onclick"].split("'")[1], "o") or ""
            direction = "descending" if "is-descending" in header.get("class", []) else "ascending"
            observed = {"column": markup.text(header), "key": toggled.lstrip("-"), "direction": direction}
            wanted = "descending" if args.sort.startswith("-") else "ascending"
            conditions["sort"] = condition(args.sort, "confirmed" if observed["key"] == key and direction == wanted else "not_applied", observed)
        else:
            conditions["sort"] = condition(args.sort)
    pages = [o["value"] for o in controls.get("pageSelect", []) if o["selected"]]
    if pages:
        conditions["start"] = condition(start, "confirmed" if pages[0] == str(start) else "not_applied", int(pages[0]) if pages[0].isdigit() else pages[0])
    elif start != 1:
        conditions["start"] = condition(start)
    obs.result["conditions"] = conditions


def next_start(page, current):
    values = sorted(int(o.get("value")) for o in page.select("#pageSelect option") if str(o.get("value", "")).isdigit())
    return next((v for v in values if v > current), None)


class Exporter:
    """JSON Lines writer that never overwrites a file it did not create in this run unless --append is given."""

    def __init__(self, args):
        self.path = Path(args.out).expanduser().absolute()
        self.count = 0
        if self.path.exists() and not args.append:
            raise Failure("export_exists", str(self.path) + " already exists.", "Choose another --out path, or pass --append to add rows to it.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a" if args.append else "x", encoding="utf-8")

    def write(self, records, page_id):
        for record in records:
            self.handle.write(json.dumps(dict(record, observation_id=page_id), ensure_ascii=False) + "\n")
            self.count += 1

    def close(self):
        self.handle.close()

    @staticmethod
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
