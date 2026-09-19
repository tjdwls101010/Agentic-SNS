"""Finviz screener: discovery of filters, signals, columns and views, and screening runs with condition evidence and paging."""

import json
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import markup
import output
from finviz import LEAVES, condition, leaf
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


@leaf("screen", "filters", help="List the current screener filters: id, label, definition and, on request, the value strings --filters accepts.", args=[(("--options",), dict(action="store_true", help="Attach each filter's option values; the whole catalog of options is about fifteen times the size of the filter list, so narrow with --filter when asking for it."))], output={"[]": "{id, label, definition, option_count} and, with --options, options: [{value, label}] whose values go to screen run --filters, plus elite_only labels an anonymous read cannot select"}, narrow=["--filter", "--fields", "--limit"])
def filters(ctx, args, target):
    obs, page = screener_page(ctx, {"ft": "4"})
    found = []
    for select in page.select("select[id^=fs_]"):
        title = select.find_parent("td")
        title = title.find_previous_sibling("td").select_one(".screener-combo-title") if title is not None and title.find_previous_sibling("td") else None
        definition = title.get("data-boxover-html") if title is not None else None
        key = select["id"][3:]
        options = [{"value": key + "_" + o["value"], "label": markup.text(o)} for o in select.select("option") if o.get("value")]
        record = {"id": key, "label": markup.text(title) if title is not None else key, "definition": markup.text(markup.BeautifulSoup(definition, "html.parser")) if definition else None}
        record["options" if args.options else "option_count"] = options if args.options else len(options)
        elite = [markup.text(o) for o in select.select("option[data-elite-only]")]
        if elite and args.options:  # nearly every filter repeats the same Elite-only entry; it belongs beside the option values, not in the catalogue
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
    settings = markup.script_json(page, obs, "route-init-data").get("tableSettings") or {}
    if not isinstance(settings.get("columnsMap"), dict) or not settings["columnsMap"]:
        raise obs.fail("structure_changed", "The screener page has no column map in route-init-data.", "Read the saved raw page with read ID --raw; Finviz may have changed the custom view.")
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


@leaf("screen", "run", help="Run the screener with filters, a signal, a view or custom columns, sorting and paging; rows keep source strings.", args=RUN_ARGS, output={"id": "when --pages > 1, a saved aggregate of all received rows before selection or export; source.pages lists independent page IDs; read ID --raw returns the aggregate JSON, while page IDs return source HTML", "[]": "one record per row keyed by the column headers, plus ticker and url (and observation_id when more than one page or --out); with --out the data is {path, rows_written, pages} instead", "conditions": "filters, signal, columns, sort and start as confirmed by each page's own controls; pages that disagree show evidence per observation id", "coverage": "received rows across pages, shown after selection, source_total from the page count, pages fetched, exhaustive false", "continuation": "{start} for the next page, or for the page that failed"}, narrow=["--fields", "--limit", "--out", "--pages 1"])
def run(ctx, args, target):
    if args.pages < 1:
        raise Failure("invalid_pages", "--pages must be at least 1.", "Use --pages 1 for a single page.")
    requested_columns = resolve_columns(ctx, args.columns)
    view = "152" if requested_columns else VIEWS[args.view][0]
    query = {"v": view, "ft": "4", "f": args.filters, "s": args.signal, "c": ",".join(map(str, requested_columns)) if requested_columns else None, "o": args.sort, "r": args.start}
    writer = Exporter(args) if args.out else None
    pages, failure, start = [], None, args.start
    for index in range(args.pages):
        query["r"] = start
        try:
            obs, page = screener_page(ctx, query)
            headers, records = page_records(page, obs)
        except Failure as exc:
            exc.record()
            if index == 0:
                raise
            failure = exc
            break
        evidence(obs, page, args, requested_columns, start)
        obs.result["data"] = records
        obs.result["coverage"] = {"received": len(records), "source_total": markup.total_count(page), "exhaustive": False}
        pages.append(obs)
        nxt = next_start(page, start)
        if nxt is None:
            start = None
            break
        start = nxt
    result = dict(pages[0].result)
    tagged = [dict(row, observation_id=obs.id) if len(pages) > 1 or writer else row for obs in pages for row in obs.result["data"]]
    selected, total = output.select_records(tagged, args, next(item for item in LEAVES if item.path == "screen run"))
    result["target"], result["selection_applied"] = "screen", True
    result["source"] = dict(result["source"], pages=[obs.id for obs in pages])
    result["conditions"] = merge_conditions(pages)
    result["coverage"] = {"received": total, "shown": len(selected), "source_total": pages[-1].result["coverage"]["source_total"], "exhaustive": False, "pages": len(pages)}
    result["warnings"] = list(dict.fromkeys(w for obs in pages for w in obs.result.get("warnings", [])))
    if start is not None:
        result["continuation"] = {"start": start}
    if failure is not None:
        failed = failure.observation.id if failure.observation is not None else None
        result["status"], result["error"] = "partial", failure.info()
        result["warnings"].append("The page at --start " + str(start) + " failed" + (" (observation " + failed + ")" if failed else "") + "; rows from " + str(len(pages)) + " completed pages are included. Resume with --start " + str(start) + (" and --append" if writer else "") + ".")
    if writer:
        writer.write(selected)
        writer.close()
        result["data"] = {"path": str(writer.path), "rows_written": writer.count, "pages": len(pages)}
        if writer.count == 0 and result["status"] != "partial":
            result["status"] = "empty"
            result["warnings"].append("No rows were written; the source returned no matching rows or the selection removed them all.")
    else:
        result["data"] = selected
    if args.pages > 1:
        result["id"] = uuid4().hex
        result["source"] = {"pages": [obs.id for obs in pages]}
        saved = {k: v for k, v in result.items() if k != "selection_applied"}
        saved["data"] = tagged
        saved["status"] = "partial" if failure else "ok" if tagged else "empty"
        saved["coverage"] = dict(result["coverage"], shown=len(tagged))
        ctx.store.save(saved, json.dumps(saved, ensure_ascii=False).encode("utf-8"))
    return result


def merge_conditions(pages):
    """One condition per parameter across pages; when pages disagree the worst status wins and evidence is listed per observation."""
    order = {"confirmed": 0, "unverified": 1, "not_applied": 2}
    merged = {}
    for key in dict.fromkeys(k for obs in pages for k in obs.result.get("conditions", {})):
        found = [(obs.id, obs.result["conditions"].get(key)) for obs in pages if key in obs.result.get("conditions", {})]
        statuses = {c["status"] for _, c in found}
        if len(statuses) == 1:
            merged[key] = found[0][1]
        else:
            worst = max(statuses, key=order.get)
            merged[key] = condition(found[0][1]["requested"], worst, {obs_id: c["evidence"] for obs_id, c in found})
    return merged


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
        conditions["sort"] = markup.sort_condition(args.sort, page, controls)
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

    def write(self, records):
        for record in records:
            self.handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.count += 1

    def close(self):
        self.handle.close()

