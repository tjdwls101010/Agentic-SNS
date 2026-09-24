"""Finviz screener: the filter, signal and column catalogues, and screening runs with condition evidence and paging."""

import json
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import contract
import markup
import selection
from contract import Collection, Selector, condition, leaf
from transport import Failure

BASE = "https://finviz.com/screener"
VIEWS = {
    "overview": ("111", "ticker, company, sector, industry, country, market cap, P/E, price, change, volume"),
    "valuation": ("121", "P/E, forward P/E, PEG, P/S, P/B, P/C, P/FCF, EPS and sales growth"),
    "ownership": ("131", "shares outstanding and float, insider and institutional ownership and transactions, short float"),
    "performance": ("141", "performance from week to year, volatility, relative and average volume"),
    "financial": ("161", "dividend yield, ROA, ROE, ROI, current and quick ratios, debt, margins, payout"),
    "technical": ("171", "beta, ATR, SMA distances, 52-week distances, RSI, price and change"),
    "etf": ("181", "ETF category, sponsor, AUM, expense ratio, flows"),
    "etf-performance": ("191", "ETF performance over standard periods"),
    "custom": ("152", "the columns named with --columns, from screen columns"),
}


def screener_page(ctx, query):
    url = BASE + "?" + urlencode({k: v for k, v in query.items() if v is not None}, safe=",")
    obs = ctx.observe(url)
    return obs, markup.soup(obs)


def with_options(records, attach, context):
    if attach:
        return records
    return [dict({k: v for k, v in r.items() if k not in ("options", "elite_only")}, option_count=len(r.get("options") or [])) for r in records]


OPTIONS = Selector(("--options",), dict(action="store_true", help="Attach each filter's option values; the option lists together are many times the size of the filter list, so narrow with --filter first."), with_options)


@leaf(
    "screen",
    "filters",
    help="List the screener filters: id, label and definition, and on request the option values --filters accepts.",
    collections={"filters": Collection("{id, label, definition, option_count}; with --options, options [{value, label}] whose values go to screen run --filters, and elite_only labels an anonymous read cannot select", local=[OPTIONS])},
)
def filters(ctx, args, target):
    obs, page = screener_page(ctx, {"ft": "4"})
    found = []
    for select in page.select("select[id^=fs_]"):
        title = select.find_parent("td")
        title = title.find_previous_sibling("td").select_one(".screener-combo-title") if title is not None and title.find_previous_sibling("td") else None
        definition = title.get("data-boxover-html") if title is not None else None
        key = select["id"][3:]
        record = {"id": key, "label": markup.text(title) if title is not None else key, "definition": markup.text(markup.BeautifulSoup(definition, "html.parser")) if definition else None}
        record["options"] = [{"value": key + "_" + o["value"], "label": markup.text(o)} for o in select.select("option") if o.get("value")]
        elite = [markup.text(o) for o in select.select("option[data-elite-only]")]
        if elite:
            record["elite_only"] = elite
        found.append(record)
    if not found:
        raise obs.fail("structure_changed", "No filter controls were found on the screener page.", "Read the saved raw page with read ID --raw.")
    obs.result["target"], obs.result["collections"] = "filters", {"filters": found}
    return obs.result


@leaf("screen", "signals", help="List the screener signals (top gainers, new high, unusual volume, patterns) that --signal accepts.", collections={"signals": Collection("{value, label}; pass value to screen run --signal")})
def signals(ctx, args, target):
    obs, page = screener_page(ctx, {"ft": "4"})
    options = markup.selects(page).get("signalSelect")
    if not options:
        raise obs.fail("structure_changed", "No signal control was found on the screener page.", "Read the saved raw page with read ID --raw.")
    obs.result["target"] = "signals"
    obs.result["collections"] = {"signals": [{"value": markup.query_param(o["value"], "s"), "label": o["label"]} for o in options if markup.query_param(o["value"], "s")]}
    return obs.result


@leaf("screen", "columns", help="List the columns the custom view accepts: id, title, index and category.", collections={"columns": Collection("{id, title, index, category}; pass ids or indices to screen run --columns")})
def columns(ctx, args, target):
    obs, page = screener_page(ctx, {"v": "152"})
    obs.result["target"], obs.result["collections"] = "columns", {"columns": column_catalog(page, obs)}
    return obs.result


def column_catalog(page, obs):
    settings = markup.script_json(page, obs, "route-init-data").get("tableSettings") or {}
    if not isinstance(settings.get("columnsMap"), dict) or not settings["columnsMap"]:
        raise obs.fail("structure_changed", "The screener page has no column map in route-init-data.", "Read the saved raw page with read ID --raw; Finviz may have changed the custom view.")
    categories = [c.get("title") for c in settings.get("categories", [])]
    return [{"id": c["id"], "title": c["title"], "index": c["index"], "category": categories[c["categoryIndex"]] if c.get("categoryIndex") is not None and c["categoryIndex"] < len(categories) else None} for c in settings.get("columnsMap", {}).values()]


RUN_ARGS = [
    (("--filters",), dict(default=None, help="Comma-separated filter values from screen filters --options, e.g. sec_technology,cap_largeover.")),
    (("--signal",), dict(default=None, help="Signal value from screen signals, e.g. ta_topgainers.")),
    (("--view",), dict(default="overview", choices=list(VIEWS), help="Table view: " + "; ".join(name + " (" + text + ")" for name, (_, text) in VIEWS.items()) + ". custom is implied by --columns.")),
    (("--columns",), dict(default=None, help="Comma-separated column ids or indices from screen columns for the custom view.")),
    (("--sort",), dict(default=None, help="Sort key from a result's sort_keys, e.g. marketcap; write --sort=-marketcap for descending.")),
    (("--row",), dict(type=int, default=1, help="One-based source row the first page starts at (20 rows per page); a next command sets it.")),
    (("--pages",), dict(type=int, default=1, help="Source pages to fetch in this run, following each page's next row.")),
    (("--out",), dict(default=None, help="Write the selected rows as JSON Lines to this path; the result then reports the file instead of the rows.")),
    (("--append",), dict(action="store_true", help="Allow appending to an existing --out file; without it an existing file is refused.")),
]


@leaf(
    "screen",
    "run",
    help="Run the screener with filters, a signal, a view or custom columns, sorting and paging; rows keep source strings.",
    args=RUN_ARGS,
    collections={"rows": Collection("one record per row keyed by the column headers, plus ticker and url, and observation_id when several pages were fetched or --out was given")},
    context={"sort_keys": "column label -> the key --sort accepts for it, from this page's own header links; columns the source does not sort are absent", "export": "with --out: {path, rows_written, pages}"},
    paging="row",
)
def run(ctx, args, target):
    if args.pages < 1 or args.row < 1:
        raise Failure("invalid_argument", "--pages and --row start at 1.", "Use --pages 1 --row 1 for the first page.")
    requested_columns = resolve_columns(ctx, args.columns)
    view = "152" if requested_columns else VIEWS[args.view][0]
    query = {"v": view, "ft": "4", "f": args.filters, "s": args.signal, "c": ",".join(map(str, requested_columns)) if requested_columns else None, "o": args.sort, "r": args.row}
    writer = Exporter(args) if args.out else None
    pages, failure, row = [], None, args.row
    for index in range(args.pages):
        query["r"] = row
        try:
            obs, page = screener_page(ctx, query)
            records = page_records(page, obs)
        except Failure as exc:
            exc.record()
            if index == 0:
                raise
            failure = exc
            break
        evidence(obs, page, args, requested_columns, row)
        obs.result["collections"] = {"rows": records}
        obs.result["totals"] = {"rows": {"source_total": markup.total_count(page)}}
        nxt = next_row(page, row)
        if nxt is not None:
            obs.result["next_page"] = nxt
        pages.append(obs)
        if nxt is None:
            row = None
            break
        row = nxt
    if len(pages) == 1 and failure is None and not writer:
        return pages[0].result
    tagged = [dict(r, observation_id=obs.id) for obs in pages for r in obs.result["collections"]["rows"]]
    result = {"id": uuid4().hex if args.pages > 1 else pages[0].id, "leaf": "screen run", "target": "screen", "observed_at": pages[0].result["observed_at"], "source": {"pages": [obs.id for obs in pages]}, "status": "ok", "context": pages[0].result["context"], "collections": {"rows": tagged}, "conditions": merge_conditions(pages), "totals": {"rows": {"source_total": pages[-1].result["totals"]["rows"]["source_total"]} | ({"pages": len(pages)} if args.pages > 1 else {})}, "warnings": list(dict.fromkeys(w for obs in pages for w in obs.result.get("warnings", [])))}
    if row is not None:
        result["next_page"] = row
    if failure is not None:
        failed = failure.observation.id if failure.observation is not None else None
        result["status"], result["error"] = "partial", failure.info()
        result["warnings"].append("The page at --row " + str(row) + " failed" + (" (observation " + failed + ")" if failed else "") + "; rows from " + str(len(pages)) + " completed pages are included. The next command resumes there.")
    if args.pages > 1:
        result["request"] = contract.request_of(args, contract.find("screen run"))
        ctx.store.save(result, json.dumps(result, ensure_ascii=False).encode("utf-8"))
    if not writer:
        return result
    picked = selection.pick(result, contract.find("screen run"), "rows", args)
    writer.write(picked.records)
    writer.close()
    shown = dict(result, export={"path": str(writer.path), "rows_written": writer.count, "pages": len(pages)})
    shown["export_coverage"] = selection.coverage(picked, len(picked.records), result["totals"]["rows"])
    return shown


def merge_conditions(pages):
    """One condition per parameter across pages; when pages disagree the worst status wins and evidence is listed per observation."""
    order = {"confirmed": 0, "unverified": 1, "not_applied": 2}
    merged = {}
    for key in dict.fromkeys(k for obs in pages for k in obs.result.get("conditions", {})):
        found = [(obs.id, obs.result["conditions"].get(key)) for obs in pages if key in obs.result.get("conditions", {})]
        statuses = {c["status"] for _, c in found}
        if len(statuses) == 1 and len({json.dumps(c["evidence"]) for _, c in found}) == 1:
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
    obs.result["context"] = {"sort_keys": markup.sort_keys(table)}
    return markup.table_records(table, obs.url)[1]


def evidence(obs, page, args, requested_columns, row):
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
            obs.result.setdefault("warnings", []).append("This view has no filter controls, so the filters are unverified; the server echoes an unknown filter too. Run the same filters with --view overview to confirm them.")
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
        conditions["row"] = condition(row, "confirmed" if pages[0] == str(row) else "not_applied", int(pages[0]) if pages[0].isdigit() else pages[0])
    elif row != 1:
        conditions["row"] = condition(row)
    obs.result["conditions"] = conditions


def next_row(page, current):
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

