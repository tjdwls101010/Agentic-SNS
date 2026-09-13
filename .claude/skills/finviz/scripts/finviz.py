"""Read-only Finviz CLI."""

import argparse
import json
import os
from pathlib import Path
import sys
import re
import subprocess
import sqlite3
from uuid import uuid4
from urllib.parse import urlencode

from runtime import Failure, Store, fetch
from extract import parse
from collect import collect
from maps import enrich


def parser():
    common = argparse.ArgumentParser(add_help=False, description="Shared output, storage and transport arguments.")
    common.add_argument(
        "--full",
        action="store_true",
        help="Explicitly emit full selected data, including large arrays; otherwise large outputs are previews.",
    )
    common.add_argument("--json", action="store_true", help="Emit structured JSON instead of compact text.")
    common.add_argument(
        "--store",
        default=os.environ.get("FINVIZ_STORE", str(Path.home() / ".cache/finviz-skill/observations.sqlite3")),
        help="SQLite observation store; reuse this location when reading saved IDs.",
    )
    common.add_argument("--connect-timeout", type=float, default=10, help="Connection timeout in seconds.")
    common.add_argument("--timeout", type=float, default=60, help="Per-request timeout in seconds.")
    common.add_argument(
        "--max-bytes",
        type=int,
        default=16 * 1024 * 1024,
        help="Maximum bytes per response; incomplete responses are marked.",
    )
    p = argparse.ArgumentParser(
        description="Explore public Finviz data. Commands describe inputs; schema explains results.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    sub = p.add_subparsers(dest="command", required=True)
    lookup = sub.add_parser(
        "lookup",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Find security candidates by name or ticker.",
    )
    lookup.add_argument("query", help="Company name or ticker.")
    read = sub.add_parser(
        "read",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Read a saved observation without fetching the network.",
    )
    read.add_argument("id", help="Saved observation ID.")
    read.add_argument("--pointer", default="", help="JSON Pointer inside the saved observation, e.g. /data/results/0.")
    read.add_argument(
        "--raw", action="store_true", help="Read the original response text, including failed extraction."
    )
    screen = sub.add_parser(
        "screen",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Screen stocks using current Finviz conditions; catalog lists filter values.",
    )
    screen.add_argument(
        "--filter",
        default=None,
        help="Comma-separated native filters, e.g. sec_technology,cap_largeover; discover with catalog.",
    )
    screen.add_argument("--view", default="111", help="Finviz view identifier; use catalog for current choices.")
    screen.add_argument("--columns", help="Comma-separated native column indices for the custom view.")
    screen.add_argument("--sort", help="Native sort key, prefix - for descending; use --sort=-marketcap.")
    screen.add_argument(
        "--start", type=int, default=1, help="One-based row offset; follow returned continuation instead of guessing."
    )
    stock = sub.add_parser(
        "stock",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Read a company or ETF, preserving source metrics and initial data.",
    )
    stock.add_argument("ticker", help="Resolved ticker from lookup.")
    stock.add_argument(
        "--section",
        choices=[
            "overview",
            "earnings",
            "dividends",
            "revenue",
            "forecast",
            "short-interest",
            "options",
            "filings",
            "income",
            "balance",
            "cashflow",
        ],
        default="overview",
        help="Dataset to read; overview also includes available ETF and ownership data.",
    )
    stock.add_argument("--expiry", help="Options expiration YYYY-MM-DD from returned expiries.")
    stock.add_argument("--page", type=int, help="Filings page, one-based.")
    stock.add_argument("--sort", help="Filings sort key from returned controls.")
    stock.add_argument(
        "--period",
        choices=["annual", "quarterly"],
        default="annual",
        help="Financial statement period; returned source periods remain authoritative.",
    )
    prices = sub.add_parser(
        "prices",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Read source price bars; date and price array lengths are validated.",
    )
    prices.add_argument("ticker", help="Ticker or market instrument identifier.")
    prices.add_argument(
        "--instrument", default="stock", choices=["stock", "futures", "forex", "crypto"], help="Instrument family."
    )
    prices.add_argument("--timeframe", default="d", help="Source timeframe identifier, e.g. d, w, m.")
    prices.add_argument("--bars", type=int, default=30, help="Requested number of bars; response coverage may differ.")
    calendar = sub.add_parser(
        "calendar",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Read earnings, dividend and economic events with source dates intact.",
    )
    calendar.add_argument(
        "kind", choices=["earnings", "dividends", "economic", "season-preview"], help="Calendar dataset."
    )
    calendar.add_argument(
        "--date", help="Starting date YYYY-MM-DD; application is confirmed only with response evidence."
    )
    calendar.add_argument("--page", type=int, default=1, help="One-based page.")
    calendar.add_argument("--sort", default=None, help="Source ordering key.")
    opened = sub.add_parser(
        "open",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Read a supported Finviz URL; external article and filing URLs stay links.",
    )
    opened.add_argument("url", help="HTTPS Finviz read URL.")
    groups = sub.add_parser(
        "groups",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Read sector, industry, country or capitalization groups.",
    )
    groups.add_argument(
        "--group", default="sector", help="Native grouping identifier; catalog groups lists page controls."
    )
    groups.add_argument("--view", default="210", help="210 uses performance API; other views read group tables.")
    groups.add_argument("--sort", default="name", help="Native sort identifier.")
    groups.add_argument("--period", default="d1", help="Performance period identifier.")
    market = sub.add_parser(
        "market",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Read market instrument data without reclassifying source instruments.",
    )
    market.add_argument("kind", choices=["futures", "forex", "crypto"], help="Source market surface.")
    market.add_argument("--timeframe", default="d", help="Source price timeframe.")
    market.add_argument(
        "--performance", action="store_true", help="Read period performance instead of price summaries."
    )
    maps = sub.add_parser(
        "map",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Read map performance and classification data; no visual rendering.",
    )
    maps.add_argument(
        "--type", default="sec", help="Source map universe, e.g. sec, geo, sec_all, etf; catalog map lists navigation."
    )
    maps.add_argument("--period", default="d1", help="Performance period, e.g. d1, w1.")
    maps.add_argument(
        "--performance-only", action="store_true", help="Read performance values without classification assets."
    )
    maps.add_argument(
        "--bubbles", action="store_true", help="Read bubble observations instead of hierarchical map data."
    )
    maps.add_argument("--x", default="sector", help="Bubble x field.")
    maps.add_argument("--y", default="lastChange", help="Bubble y field.")
    maps.add_argument("--size", default="marketCap", help="Bubble size field.")
    maps.add_argument("--color", default="sector", help="Bubble color field.")
    maps.add_argument("--index", default="sp500", help="Bubble stock universe.")
    news = sub.add_parser(
        "news",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Read Finviz news lists, own articles or source-generated Market Pulse explanations.",
    )
    news.add_argument("--view", default="2", help="Source view: 2 source, 3 stocks, 4 ETFs, 5 crypto, 6 Market Pulse.")
    news.add_argument("--pulse", type=int, help="Market Pulse ID returned by a news row.")
    news.add_argument("--url", help="Finviz-hosted article URL; use external readers for other hosts.")
    insiders = sub.add_parser(
        "insiders",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Read insider trade lists and original filing links.",
    )
    insiders.add_argument(
        "--transaction", choices=["all", "buy", "sale"], default="all", help="Native transaction filter."
    )
    insiders.add_argument("--owner", help="Native owner identifier returned by source links.")
    insiders.add_argument("--sort", help="Native ordering identifier.")
    insiders.add_argument("--value", help="Native transaction-value threshold.")
    catalog = sub.add_parser(
        "catalog",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Discover current source controls, column definitions and navigation.",
    )
    catalog.add_argument(
        "surface",
        choices=["screen", "stock", "map", "groups", "calendar", "news", "insiders", "market"],
        default="screen",
        nargs="?",
        help="Surface whose current interface to inspect.",
    )
    catalog.add_argument(
        "--ticker",
        default="A",
        help="Example security for stock-specific choices; lookup resolves the intended security.",
    )
    sub.add_parser(
        "doctor",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Check local Python, curl and observation storage; does not contact Finviz.",
    )
    sub.add_parser(
        "schema",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Describe output semantics and recovery without fetching the network.",
    )
    inspect = sub.add_parser(
        "inspect",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="List saved JSON Pointer locations and counts, without dumping records.",
    )
    inspect.add_argument("id", help="Saved observation ID.")
    read.add_argument("--start", type=int, default=0, help="Zero-based array slice start at the selected pointer.")
    read.add_argument(
        "--limit", type=int, default=20, help="Number of selected array entries to display; saved content is unchanged."
    )
    collecting = sub.add_parser(
        "collect",
        parents=[common],
        formatter_class=argparse.RawTextHelpFormatter,
        help="Continue a saved query; resume with its c_ collection ID after failure or page limit.",
    )
    collecting.add_argument("id", help="Starting observation ID or existing c_ collection ID.")
    collecting.add_argument(
        "--max-pages",
        type=int,
        default=20,
        help="Maximum additional pages in this invocation; the checkpoint retains the next URL.",
    )
    collecting.add_argument(
        "--out",
        help="JSONL export path: one full observation per line, preserving headers, metadata and errors; edited files are refused.",
    )
    return p


def run(args):
    store = Store(args.store)
    if args.command == "collect":
        if args.max_pages < 0:
            raise Failure(
                "invalid_argument",
                "max-pages cannot be negative.",
                "Use zero to inspect a checkpoint or a positive page budget.",
            )
        return collect(args, store)
    if args.command == "doctor":
        proc = subprocess.run(["curl", "--version"], capture_output=True, text=True)
        version = re.search(r"curl (\d+)\.(\d+)\.(\d+)", proc.stdout)
        valid = version is not None and tuple(map(int, version.groups())) >= (8, 4, 0) and sys.version_info >= (3, 11)
        return dict(
            status="ok" if valid else "error",
            data=dict(
                python=sys.version.split()[0],
                curl=proc.stdout.splitlines()[0] if proc.stdout else proc.stderr,
                store=str(store.path),
            ),
            errors=[] if valid else [dict(code="runtime_version", fix="Install Python 3.11+ and curl 8.4+.")],
        )
    if args.command == "schema":
        return dict(status="ok", data=SCHEMA)
    if args.command == "inspect":
        return dict(
            id=args.id,
            status="ok",
            data=inventory(store.collection(args.id) if args.id.startswith("c_") else store.get(args.id)),
        )
    if args.command == "read":
        if (
            args.start < 0
            or args.limit < 0
            or (args.pointer and not args.pointer.startswith("/"))
            or re.search(r"~(?![01])", args.pointer)
        ):
            raise Failure(
                "invalid_selection",
                "Invalid JSON Pointer or negative read window.",
                "Use pointers from inspect and non-negative start/limit values.",
            )
        if args.raw and (args.pointer or args.id.startswith("c_")):
            raise Failure(
                "invalid_selection",
                "Raw reads require an observation ID without a pointer.",
                "Use read OBSERVATION_ID --raw.",
            )
        data = store.collection(args.id) if args.id.startswith("c_") else store.get(args.id, raw=args.raw)
        if args.raw:
            data = data.decode("utf-8", errors="replace")
        else:
            for token in args.pointer.split("/")[1:]:
                token = token.replace("~1", "/").replace("~0", "~")
                if isinstance(data, list):
                    if not re.fullmatch(r"0|[1-9][0-9]*", token):
                        raise Failure(
                            "invalid_pointer",
                            "Array pointer requires a non-negative integer.",
                            "Use a returned array position from inspect.",
                        )
                    data = data[int(token)]
                else:
                    data = data[token]
        count = len(data) if isinstance(data, list) else None
        if isinstance(data, list):
            data = data[args.start : args.start + args.limit]
        context = {} if args.id.startswith("c_") else store.get(args.id)
        return dict(
            id=args.id,
            status="ok",
            observation_status=context.get("status"),
            source=context.get("source"),
            conditions=context.get("conditions"),
            coverage=context.get("coverage"),
            errors=context.get("errors", []),
            data=data,
            selection=dict(
                pointer=args.pointer,
                received=count,
                shown=len(data) if isinstance(data, list) else None,
                start=args.start,
            ),
        )
    if args.command == "catalog":
        url = (
            "https://finviz.com"
            + {
                "screen": "/screener?ft=4&v=151",
                "stock": "/stock?t=" + args.ticker,
                "map": "/map",
                "groups": "/groups",
                "calendar": "/calendar/earnings",
                "news": "/news",
                "insiders": "/insidertrading",
                "market": "/futures",
            }[args.surface]
        )
    elif args.command == "open":
        url = args.url
    elif args.command == "groups":
        path = "/api/groups_perf" if args.view == "210" else "/groups"
        url = (
            "https://finviz.com"
            + path
            + "?"
            + urlencode({"g": args.group, "v": args.view, "o": args.sort, "st": args.period})
        )
    elif args.command == "market":
        url = (
            "https://finviz.com/api/"
            + args.kind
            + ("_perf" if args.performance else "_all?" + urlencode({"timeframe": args.timeframe}))
        )
    elif args.command == "insiders":
        query = {
            "tc": {"all": "7", "buy": "1", "sale": "2"}[args.transaction],
            "oc": args.owner,
            "o": args.sort,
            "tv": args.value,
        }
        url = "https://finviz.com/insidertrading?" + urlencode({k: v for k, v in query.items() if v is not None})
    elif args.command == "news":
        url = args.url or (
            "https://finviz.com/api/stocks-why-moving/by-id/" + str(args.pulse)
            if args.pulse
            else "https://finviz.com/news?" + urlencode({"v": args.view})
        )
    elif args.command == "map":
        if args.bubbles:
            url = "https://finviz.com/api/bubbles?" + urlencode(
                {"x": args.x, "y": args.y, "size": args.size, "color": args.color, "idx": args.index}
            )
        else:
            url = "https://finviz.com/api/map_perf?" + urlencode({"t": args.type, "st": args.period})
    elif args.command == "calendar":
        path = (
            "/calendar/earnings/season-preview"
            if args.kind == "season-preview"
            else ("/api/calendar/earnings" if args.kind == "earnings" and args.date else "/calendar/" + args.kind)
        )
        query = {
            "dateFrom": args.date,
            "page": args.page,
            "sort": args.sort or ("earningsDate" if args.kind == "earnings" else None),
        }
        url = "https://finviz.com" + path + "?" + urlencode({k: v for k, v in query.items() if v is not None})
    elif args.command == "screen":
        query = {"ft": "4", "v": args.view, "f": args.filter, "c": args.columns, "o": args.sort, "r": args.start}
        url = "https://finviz.com/screener?" + urlencode({k: v for k, v in query.items() if v is not None})
    elif args.command == "prices":
        url = "https://finviz.com/api/quote?" + urlencode(
            {"instrument": args.instrument, "ticker": args.ticker, "timeframe": args.timeframe, "barsCount": args.bars}
        )
    elif args.command == "stock" and args.section in ("income", "balance", "cashflow"):
        kind = {"income": "I", "balance": "B", "cashflow": "C"}[args.section] + (
            "A" if args.period == "annual" else "Q"
        )
        url = "https://finviz.com/api/statement?" + urlencode({"t": args.ticker, "so": "F", "s": kind})
    elif args.command == "stock":
        section = {
            "overview": "c",
            "earnings": "ea",
            "dividends": "dv",
            "revenue": "rv",
            "forecast": "fc",
            "short-interest": "si",
            "options": "oc",
            "filings": "lf",
        }[args.section]
        query = {"t": args.ticker, "ty": section, "e": args.expiry, "page": args.page, "sort": args.sort}
        url = "https://finviz.com/stock?" + urlencode({k: v for k, v in query.items() if v is not None})
    else:
        url = "https://finviz.com/api/suggestions?" + urlencode({"input": args.query})
    result = fetch(url, args, store, parse)
    if (
        args.command == "catalog"
        and args.surface == "screen"
        and result["status"] != "error"
        and not any((c["id"] or "").startswith("fs_") for c in result["data"]["controls"])
    ):
        filters = fetch("https://finviz.com/screener?ft=4", args, store, parse)
        combined = dict(
            result,
            id=uuid4().hex,
            data=dict(result["data"]),
            dependencies=[result["id"], filters["id"]],
            errors=list(result["errors"]),
        )
        if filters["status"] == "ok":
            combined["data"]["controls"] = filters["data"]["controls"]
            combined["data"]["controls_source"] = filters["source"]
        else:
            combined["status"] = "partial"
            combined["errors"].extend(filters["errors"])
        store.save(combined, store.get(result["id"], raw=True))
        result = combined
    return (
        enrich(result, args, store)
        if args.command == "map" and not args.performance_only and not args.bubbles
        else result
    )


SCHEMA = {
    "status": "ok: usable extraction; partial: usable data with gaps; error: no usable requested result. Exit 1 for error, 2 for invalid CLI syntax.",
    "source": "url, requested_url, observed_at (UTC collection time), HTTP status, headers, received_complete and redirect observation IDs. Collection time is not market time.",
    "conditions": "Each query parameter carries requested, status (confirmed / not_applied / unverified) and source evidence. HTTP success alone never confirms a condition.",
    "data": "Source JSON remains intact. HTML supplies initial named JSON, ordered metric records with definitions, tables with ordered cells and links, controls and article paragraphs. Same-name metrics remain separate.",
    "coverage": "received is extracted items on this response, shown is displayed items, source_total is the provider claim or null. Exhaustive is false for a changing remote population; pagination_end only describes navigation.",
    "continuation": "URL for the next page of the same query or null when none can be established. Null alone does not prove completeness.",
    "errors": "code, message and fix; a saved raw response remains available even after extraction failure. Access restrictions may carry Retry-After in source.headers.",
    "export": "collect --out writes one complete observation per JSONL line, preserving table headers, enclosing source metadata, status and errors. unique_items counts distinct extracted items; export retains page observations including repeated items.",
    "reading": "read.status reports retrieval success; observation_status, source, conditions, coverage and errors retain the original observation context even for a slice. selection describes only the displayed slice.",
    "storage": "Observations are immutable. read --raw retrieves received text; inspect lists pointers; read ID --pointer /data/... --start 0 --limit 20 reads a slice without network access.",
    "dates": "Source timestamp, reporting period, estimated event date and observed_at retain different roles. Source units, currencies, nulls, placeholder times and extra fields are not guessed or replaced.",
}


def inventory(value, pointer="", depth=0):
    entries = [
        dict(pointer=pointer, type=type(value).__name__, count=len(value) if isinstance(value, (dict, list)) else None)
    ]
    if depth < 5:
        if isinstance(value, dict):
            for key, child in value.items():
                entries.extend(
                    inventory(child, pointer + "/" + str(key).replace("~", "~0").replace("/", "~1"), depth + 1)
                )
        elif isinstance(value, list) and value:
            entries.extend(inventory(value[0], pointer + "/0", depth + 1))
    return entries


def preview(value, depth=0):
    if depth >= 5 and isinstance(value, (dict, list)):
        return {"type": type(value).__name__, "count": len(value), "preview_omitted": True}
    if isinstance(value, dict):
        return {k: preview(v, depth + 1) for k, v in list(value.items())[:8]}
    if isinstance(value, list):
        return [preview(v, depth + 1) for v in value[:5]]
    return value[:180] + "…" if isinstance(value, str) and len(value) > 180 else value


def presentation(result, args):
    if args.full or len(json.dumps(result, ensure_ascii=False)) <= 16000:
        return result
    output = dict(result, data=preview(result.get("data")))
    output["presentation"] = {
        "truncated": True,
        "fix": "Use inspect ID, then read ID --pointer /data/... --start 0 --limit 20; --full explicitly emits all selected data.",
    }
    if isinstance(output.get("coverage"), dict):
        output["coverage"] = dict(output["coverage"], shown=None)
    if len(json.dumps(output, ensure_ascii=False)) > 16000:
        output["data"] = {"pointer": "/data", "preview_omitted": True}
    return output


def main():
    args = parser().parse_args()
    try:
        if args.timeout <= 0 or args.connect_timeout <= 0 or args.max_bytes <= 0:
            raise Failure("invalid_argument", "Limits must be positive.", "Use positive timeout and byte limits.")
        result = run(args)
    except (Failure, ValueError, KeyError, IndexError, OSError, sqlite3.Error) as exc:
        result = dict(
            status="error",
            errors=[
                exc.detail
                if isinstance(exc, Failure)
                else dict(
                    code="invalid_input", message=str(exc), fix="Check the command help and returned IDs or pointers."
                )
            ],
        )
    result = presentation(result, args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print("status=" + result["status"] + " id=" + result.get("id", "-"))
        for key, value in result.items():
            if key not in ("status", "id"):
                print(key + ": " + json.dumps(value, ensure_ascii=False, separators=(",", ":")))

    return 1 if result["status"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
