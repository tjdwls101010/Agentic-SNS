"""Purpose-oriented Yahoo Finance CLI. Discover contracts with schema and --help."""
import argparse
import contextlib
from datetime import date, timedelta
import re
import signal
import sys

import yfinance as yf

import budget
import company
import leaves
import market
import output
import prices
import store
from budget import EXIT_CODES, STATUSES
from output import InputError, condition, encode, error_info, ordered, result, select

GLOBAL_DEFAULTS = {"max_chars": 20000, "filter": "", "ttl_days": 14}

GROUPS = {
    "search": "Find instruments by name, symbol or keyword",
    "prices": "Quotes, historical bars and corporate actions",
    "company": "Profile, shares outstanding, news and filing links",
    "financials": "Income, balance sheet, cash flow and valuation measures by period",
    "analysts": "Estimates, revisions, recommendations and rating actions",
    "holders": "Institutional, fund and insider ownership",
    "fund": "ETF and mutual fund composition, weights and operations",
    "options": "Expirations and option chains",
    "screen": "Query fields, enumerated values, named presets and screening runs",
    "market": "Market summaries, sectors and industries",
    "calendar": "Earnings, economic, IPO and split events by date",
}
QUERY_HELP = '''JSON query: {"operator":OP,"operands":[...]}; field names come from screen fields, enumerated values from screen values.
EQ [field, string|finite number] (2 operands); IS-IN [field, value, ...] (2+ operands).
BTWN [field, number, number] (3 operands, inclusive lower/upper); GT, LT, GTE, LTE [field, finite number] (2 operands).
AND, OR [query, query, ...] (2+ nested query objects). Booleans, null, NaN and Infinity are not query values.
Nested example: {"operator":"AND","operands":[{"operator":"EQ","operands":["region","us"]},{"operator":"GT","operands":["intradaymarketcap",2000000000]}]}
Use --query 'JSON' or --preset NAME. Fields and values can be narrowed with --filter TEXT and --field NAME.'''

ENVELOPE = {
    "target": "the symbol, query or key this result answers",
    "id": "saved observation id; every adapter return is saved before local selection, so a result that did not fit is still reachable with read",
    "observed_at": "when this CLI received the response",
    "source_time": "the time the source itself put on this data, where it supplies one; after a close it can be hours before observed_at",
    "status": "see statuses",
    "conditions": "only the arguments this response carries evidence for: {requested, status: confirmed|not_applied|unverified, evidence}. A successful call is not evidence that a condition was applied",
    "coverage": "received = rows the adapter returned, shown = rows printed, kept = which end a limit kept, truncated_by = leaf_default (this leaf's own window, status ok) or budget (your range did not fit, status partial), fields = how many of the available fields the projection kept",
    "data": "the selected value; tables are {index, columns, data, index_names, column_names}",
    "warnings": "limitations that affect how this data can be used",
    "error": "{code, message, fix}",
}


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class", argparse.RawTextHelpFormatter)
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise InputError(message)


def common(parser, selection=True, root=False):
    parser.add_argument("--max-chars", type=int, default=GLOBAL_DEFAULTS["max_chars"] if root else argparse.SUPPRESS, help="Maximum JSON characters. Each command's own default window is what keeps a result to one screen; this is the safety boundary behind it.")
    parser.add_argument("--filter", default=GLOBAL_DEFAULTS["filter"] if root else argparse.SUPPRESS, help="Case-insensitive substring for schema, catalogs or --list-fields.")
    parser.add_argument("--store", default=argparse.SUPPRESS if not root else None, help="Directory holding saved observations; the same path is needed to read an earlier id. Defaults to the user cache, or $YF_STORE.")
    if selection:
        parser.add_argument("--fields", type=lambda value: [f.strip() for f in value.split(",")], help="Comma-separated output fields, replacing this command's default projection. Nested payloads take dotted paths such as content.title; --list-fields names them.")
        parser.add_argument("--list-fields", action="store_true", help="Name the fields available for this dataset and target instead of returning values.")
        parser.add_argument("--limit", type=int, help="Maximum output rows, replacing this command's default window. schema reports which end of the series a limit keeps.")
        parser.add_argument("--timeout", type=int, default=30, help="Wall-clock seconds per target (includes library calls); default 30.")


def dates(parser, help_start, help_end):
    parser.add_argument("--start", help=help_start)
    parser.add_argument("--end", help=help_end)


def build_parser():
    parser = Parser(description="Query Yahoo Finance data by purpose. stdout: one JSON document; diagnostics: stderr. Discover with schema [GROUP [LEAF]].")
    common(parser, False, root=True)
    parser.add_argument("--ttl-days", type=int, default=GLOBAL_DEFAULTS["ttl_days"], help="Delete saved observations older than this many days. Retention only: an observation inside the window is not therefore current, and source_time is what says whether a value is fresh.")
    groups = parser.add_subparsers(dest="group", required=True)

    schema = groups.add_parser("schema", help="Discover inputs and output contracts offline")
    schema.add_argument("scope", nargs="*", help="GROUP or GROUP LEAF to describe; omit to list every group.")
    common(schema, False)

    reader = groups.add_parser("read", help="Read a saved observation in slices without a new request")
    reader.add_argument("id", help="Observation id from an earlier result.")
    reader.add_argument("--start", dest="row_start", type=int, default=0, help="Zero-based first row to return; each slice names the start of the next one.")
    common(reader)
    reader.set_defaults(leaf="")

    items = {}
    for (group, name), item in leaves.LEAVES.items():
        items.setdefault(group, {})[name] = item
    parsers = {}
    for group, members in items.items():
        gp = groups.add_parser(group, help=GROUPS[group])
        sub = gp.add_subparsers(dest="leaf", required=True) if group != "search" else None
        for name, item in members.items():
            p = sub.add_parser(name, description=item.purpose, help=item.purpose) if sub else gp
            if not sub:
                p.description = item.purpose
                p.set_defaults(leaf="")
            parsers[group, name] = p
            common(p)
            add_arguments(p, group, name)
    return parser, parsers


def add_arguments(p, group, leaf):
    if group in {"prices", "company", "financials", "analysts", "holders", "fund", "options"}:
        p.add_argument("symbols", nargs="+", help="One or more Yahoo symbols; each is queried separately.")
    if group == "prices" and leaf in {"history", "actions"}:
        dates(p, "ISO date YYYY-MM-DD; inclusive.", "ISO date YYYY-MM-DD; exclusive, so the last bar returned is the day before.")
        p.add_argument("--period", help="Relative range such as 5d, 1mo, 1y, ytd or max; default 1mo only when start/end are absent.")
        p.add_argument("--interval", choices=["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"], default="1d", help="Bar size. Intraday intervals carry range limits the source enforces; schema prices history reports the measured values.")
        p.add_argument("--adjust", choices=["none", "auto", "back"], default="auto", help="none: unadjusted OHLC as supplied plus Adj Close; auto: Open/High/Low/Close scaled for splits and dividends, Adj Close removed; back: Close kept raw while Open/High/Low are scaled by the adjustment ratio, Adj Close removed.")
        p.add_argument("--repair", action="store_true", help="Opt into yfinance price repair; OFF by default.")
        p.add_argument("--prepost", action="store_true", help="Include pre/post-market data where available.")
    if (group, leaf) in {("prices", "quote"), ("company", "profile")}:
        p.add_argument("--from", dest="from_id", help="Read this saved observation instead of making a new request. prices quote and company profile select different sides of the same assembled response, so the second one costs nothing.")
    if group == "company" and leaf == "shares":
        dates(p, "ISO date YYYY-MM-DD; default is about 18 months ago.", "ISO date YYYY-MM-DD; default is now.")
    if group == "company" and leaf == "news":
        p.add_argument("--tab", choices=["news", "all", "press releases"], default="news", help="Article source: news articles, press releases, or all.")
    if group == "financials":
        p.add_argument("--frequency", choices=["yearly", "quarterly"] if leaf == "balance" else ["yearly", "quarterly", "monthly", "trailing"] if leaf == "valuation" else ["yearly", "quarterly", "trailing"], default="quarterly" if leaf == "valuation" else "yearly", help="trailing means TTM, a rolling twelve months rather than a completed fiscal period.")
        p.add_argument("--periods", type=int, default=5, help="Maximum periods; valuation sends this upstream (0 = Current only), statements select locally.")
    if group == "options" and leaf == "chain":
        p.add_argument("--date", help="Expiration YYYY-MM-DD; omitted selects the nearest available expiry.")
        p.add_argument("--side", choices=["calls", "puts", "both"], default="both", help="Contract side to return; each side is limited separately.")
    if group == "search":
        p.add_argument("query", help="Company name, symbol fragment or keyword.")
        p.add_argument("--type", choices=["all", "stock", "mutualfund", "etf", "index", "future", "currency", "cryptocurrency"], default="all", help="Instrument type filter; applies to --dataset quotes only.")
        p.add_argument("--dataset", choices=["quotes", "news", "lists", "research"], default="quotes", help="quotes: instrument candidates; news: articles; lists: Yahoo curated lists; research: research reports.")
    if group == "screen":
        p.add_argument("--type", choices=["equity", "fund", "etf"], default="equity", help="Query universe; fields, values and presets differ per type.")
        if leaf in {"fields", "values"}:
            p.add_argument("--field", help="Exact query field, useful for allowed-value lookup.")
        if leaf == "run":
            p.epilog = QUERY_HELP
            q = p.add_mutually_exclusive_group(required=True)
            q.add_argument("--query", help="JSON operator/operands object; see examples below.")
            q.add_argument("--preset", help="Preset name from screen presets. A preset's name does not state its condition; the result carries the query it ran.")
            p.add_argument("--offset", type=int, default=0, help="Remote row offset for the next page; coverage next_offset supplies it.")
            p.add_argument("--sort", help="Sort field from screen fields; custom query default ticker, preset uses its defined sort.")
            p.add_argument("--ascending", action=argparse.BooleanOptionalAction, default=None, help="Sort direction: --ascending or --no-ascending; omitted means the preset's own direction, or descending for a custom query.")
    if group == "market":
        if leaf == "summary":
            p.add_argument("--region", choices=[r.value for r in yf.MarketRegion], default="US", help="Yahoo market region.")
        if leaf in {"sector", "industry"}:
            p.add_argument("key", help="Sector key from market sectors, or industry key from market sector KEY --dataset industries.")
            # 성진: 닫힌 선택지가 G1을 인터페이스 층에서 없앤다 — 서비스되지 않는 코드는 경고 없이 미국 데이터를 돌려줬다.
            p.add_argument("--region", choices=market.DOMAIN_REGIONS, default="US", help="Country code, restricted to the regions measured as actually served; others returned the United States result with no warning. Outside the US the name column arrives null.")
            choices = ["overview", "top-companies", "research-reports"] + (["industries", "top-etfs", "top-funds"] if leaf == "sector" else ["top-performing", "top-growth"])
            p.add_argument("--dataset", choices=choices, default="overview", help="Part of the sector or industry to return.")
    if group == "calendar":
        dates(p, "ISO date YYYY-MM-DD; inclusive. Defaults to today for market-wide calendars.", "ISO date YYYY-MM-DD; inclusive, so --start D --end D returns that day. Defaults to seven days after --start.")
        p.add_argument("--offset", type=int, default=0, help="Remote row offset; next_offset advances by displayed rows, not native batch size.")
        if leaf == "earnings":
            p.add_argument("symbol", nargs="?", help="Optional single symbol; omit for market-wide US earnings.")
            p.add_argument("--most-active", action="store_true", help="Opt into native most-active filter; only market earnings at offset 0.")


def resolve_defaults(args):
    """One policy used by execution and schema; no requests or input mutation outside this namespace."""
    if hasattr(args, "period") and args.period is None and not (args.start or args.end):
        args.period = "1mo"
    if args.group == "calendar" and not getattr(args, "symbol", None):
        args.start = args.start or date.today().isoformat()
        args.end = args.end or (date.fromisoformat(args.start) + timedelta(days=7)).isoformat()
    if (args.group, args.leaf) == ("screen", "run"):
        if args.preset:
            if args.preset not in yf.PREDEFINED_SCREENER_QUERIES:
                raise InputError("Unknown --preset; use screen presets --filter TEXT")
            preset = yf.PREDEFINED_SCREENER_QUERIES[args.preset]
            args.type = next(kind for kind, cls in market.QUERY_TYPES.items() if isinstance(preset["query"], cls))
            args.sort = args.sort or preset["sortField"]
            if args.ascending is None:
                args.ascending = preset["sortType"].lower() == "asc"
        else:
            args.sort = args.sort or "ticker"
            if args.ascending is None:
                args.ascending = False


# ---- schema ------------------------------------------------------------------------------------------------------


def describe(parser, item):
    defaults = argparse.Namespace(group=item.group, leaf=item.name, **{a.dest: a.default for a in parser._actions if a.dest != "help"})
    with contextlib.suppress(InputError):
        resolve_defaults(defaults)
    arguments = {}
    for action in parser._actions:
        if action.dest == "help":
            continue
        name = action.option_strings[0] if action.option_strings else action.dest
        value = GLOBAL_DEFAULTS.get(action.dest) if action.default == argparse.SUPPRESS else getattr(defaults, action.dest, action.default)
        if action.dest == "limit" and value is None:
            value = item.limit  # 성진: 실효 기본창은 leaves가 갖는다; argparse의 None을 그대로 실으면 두 자리가 서로 다른 말을 한다
        arguments[name] = {"help": action.help, "default": value, "choices": list(action.choices) if action.choices else None, "required": bool(action.required) if action.option_strings else action.nargs not in ("?", "*")}
    described = {
        "command": item.path,
        "description": item.purpose,
        "arguments": arguments,
        "default_window": {"rows": item.limit, "fields": list(item.fields) or None, "limit_keeps": item.limit_keeps()},
        "units": item.units or None,
        "interpretation": item.interpretation or None,
        "limits": item.limits or None,
        "narrowing": list(item.narrow) or None,
        "gotchas": list(item.gotchas) or None,
        "notes": parser.epilog,
        # 성진: 봉투·상태·종료코드는 리프마다 같다. 49번 싣는 순간 그건 밀도가 아니라 반복이고, 리프 고유의 계약을 그 안에 묻는다.
        "output": "every result uses the shared envelope; run schema with no scope for its fields, statuses and exit codes",
    }
    return {k: v for k, v in described.items() if v is not None}


def schema_data(args, parsers):
    scope = tuple(args.scope)
    if len(scope) > 2 or (scope and scope[0] not in GROUPS):
        raise InputError("schema expects an existing GROUP [LEAF]; run schema with no scope to list the groups.")
    if scope == ("search",):
        scope = ("search", "")
    if len(scope) == 2:
        item = leaves.get(*scope)
        if item is None:
            raise InputError(f"No command {' '.join(scope)}; use schema {scope[0]} to list its commands.")
        data = describe(parsers[scope], item)
        if args.filter:
            data["arguments"] = {k: v for k, v in data["arguments"].items() if args.filter.lower() in (k + str(v)).lower()}
        return data
    listed = {}
    for (group, name), item in leaves.LEAVES.items():
        if scope and group != scope[0]:
            continue
        listed.setdefault(group, {})[name or ""] = item.purpose
    commands = listed.get(scope[0], {}) if scope else listed
    matched = {k: v for k, v in commands.items() if args.filter.lower() in (k + str(v)).lower()}
    # 성진: 걸러낸 목록이 돌려주지 않은 그룹까지 설명하면, 좁히려고 준 --filter가 출력을 거의 줄이지 못한다.
    shown_groups = {scope[0]} if scope else set(matched)
    described = {"commands": matched, "group_purposes": {k: v for k, v in GROUPS.items() if k in shown_groups},
                 "next": "schema GROUP LEAF for that command's arguments, default window, units and known limits"}
    if not scope and not args.filter:
        # 성진: --filter를 준 호출은 명령을 찾는 중이다. 그때까지 봉투 설명을 함께 실으면 좁히려는 시도가 같은 예산에 다시 걸린다.
        described["output"] = {"envelope": ENVELOPE, "statuses": STATUSES, "exit_codes": EXIT_CODES}
    return described


# ---- validation --------------------------------------------------------------------------------------------------


def validate(args):
    targets = list(getattr(args, "symbols", []))
    targets.extend(getattr(args, name) for name in ("symbol", "key") if getattr(args, name, None) is not None)
    if args.group == "search":
        targets.append(args.query)
    if any(not target.strip() for target in targets):
        raise InputError("Target symbols, search text and domain keys must not be empty")
    if args.timeout <= 0:
        raise InputError("--timeout must be positive")
    for name in ("limit", "periods"):
        minimum = 0 if name == "periods" and (args.group, args.leaf) == ("financials", "valuation") else 1
        if getattr(args, name, None) is not None and getattr(args, name) < minimum:
            raise InputError(f"--{name} must be >= {minimum}")
    if getattr(args, "offset", 0) < 0:
        raise InputError("--offset must be nonnegative")
    if getattr(args, "row_start", 0) < 0:
        raise InputError("--start must be nonnegative")
    for name in ("start", "end", "date"):
        value = getattr(args, name, None)
        if isinstance(value, str):
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                raise InputError(f"--{name} expects YYYY-MM-DD") from None
    start, end = getattr(args, "start", None), getattr(args, "end", None)
    if isinstance(start, str) and isinstance(end, str) and (start > end or (args.group == "prices" and start == end)):
        raise InputError("Invalid date range; a price --end is exclusive so it must be after --start, and a calendar --end is inclusive so it may equal --start")
    if hasattr(args, "period"):
        if args.period and (start or end):
            raise InputError("--period cannot be combined with --start or --end")
        if args.period and not re.fullmatch(r"([1-9][0-9]*(d|wk|mo|y)|ytd|max)", args.period):
            raise InputError("--period expects a positive range such as 5d, 1mo, 1y, ytd or max")
    if args.group == "calendar":
        if args.limit and args.limit > 100:
            raise InputError("Calendar --limit cannot exceed Yahoo's 100-row cap")
        if getattr(args, "symbol", None):
            if start or end or args.most_active:
                raise InputError("Single-symbol earnings supports --limit/--offset, not date or most-active filters; omit SYMBOL for market dates")
        if getattr(args, "most_active", False) and args.offset:
            raise InputError("Native most-active filter is unavailable with --offset; remove --most-active")
    if args.group == "search" and args.dataset != "quotes" and args.type != "all":
        raise InputError("--type only filters instrument quotes; use --dataset quotes")
    if args.group == "screen" and args.limit and args.limit > 250:
        raise InputError("Screen --limit cannot exceed Yahoo's 250-row cap")
    resolve_defaults(args)
    if args.fields and any(not f for f in args.fields):
        raise InputError("--fields requires nonempty comma-separated field names")


class DeadlineExpired(BaseException):
    """Bypass upstream broad Exception handlers so a CLI deadline stays bounded."""


def timed_out(signum, frame):
    raise DeadlineExpired("Target exceeded --timeout; narrow the request or raise --timeout")


# ---- execution ---------------------------------------------------------------------------------------------------


def observe(symbol, args, item, saved):
    """One target: fetch, note what the response itself confirms, and hand back the encoded value before selection."""
    context, warnings = {}, []
    if getattr(args, "from_id", None):
        record = saved.load(args.from_id)
        if record.get("target") != symbol:
            raise InputError(f"Observation {args.from_id} holds {record.get('target')}, not {symbol}; pass the id returned for this symbol or drop --from.")
        if record.get("command") not in ("prices quote", "company profile"):
            raise InputError(f"Observation {args.from_id} came from {record.get('command')}, which does not hold this command's fields; drop --from to request it.")
        return record["data"], record.get("context") or {}, list(record.get("warnings") or []), record.get("conditions") or {}, record.get("observed_at"), record.get("source_time"), args.from_id

    if args.group in {"search", "screen", "market", "calendar"}:
        data = market.fetch(args, context, warnings)
    else:
        ticker = yf.Ticker(symbol)
        data = prices.fetch(ticker, args, context, warnings) if args.group == "prices" and args.leaf in {"history", "actions"} else company.fetch(ticker, args, context, warnings)

    if isinstance(data, dict) and args.group == "options" and args.leaf == "chain":
        encoded = {side: encode(frame) for side, frame in data.items()}
    else:
        encoded = encode(data)
    conditions = judge(encoded, args, item, context)
    when = context.pop("source_time", None) or (company.source_time(encoded) if isinstance(encoded, dict) and (args.group, args.leaf) in company.INFO_LEAVES else None)
    return encoded, context, warnings, conditions, output.now(), when, None


def judge(encoded, args, item, context):
    """Conditions come from the response, so an argument the source ignored is reported as not applied."""
    if not item.conditions:
        return {}
    if args.group == "screen" and args.leaf == "run":
        return market.screen_conditions(encoded, args, context)
    if args.group == "calendar" and not getattr(args, "symbol", None):
        return market.calendar_conditions(encoded, args)
    if args.group == "prices":
        return prices.dates_applied(encoded, args)
    if (args.group, args.leaf) == ("options", "chain") and args.date:
        applied = context.get("expiration") == args.date
        return {"date": condition(args.date, "confirmed" if applied else "not_applied", {"expiration": context.get("expiration")})}
    return {}


def select_sides(encoded, args, item, coverage):
    """An option chain holds two independently limited tables, so each side reports its own coverage."""
    data, per_side = {}, {}
    for side, table in encoded.items():
        seen = {}
        data[side], _ = select(table, args, item, seen)
        per_side[side] = seen
    coverage.update(per_side)
    return data


def run(args, item, saved, request):
    results, stopped = [], False
    plural = list(getattr(args, "symbols", [])) or [getattr(args, "symbol", None) or getattr(args, "query", None) or getattr(args, "key", None) or args.group]
    for symbol in plural:
        if stopped:
            results.append(result(symbol, status="not_attempted", error=error_info("not_attempted", "Stopped after rate limiting", "Retry later with fewer targets.")))
            continue
        try:
            signal.signal(signal.SIGALRM, timed_out)
            signal.alarm(args.timeout)
            with contextlib.redirect_stdout(sys.stderr):
                encoded, context, warnings, conditions, observed_at, when, reused = observe(symbol, args, item, saved)
                ident = reused or saved.save(store.record(item, symbol, request, encoded, context, warnings, "empty" if output.is_empty(encoded) else "ok", conditions, observed_at, when))
                coverage = {}
                if output.is_sided(encoded) and not args.list_fields:
                    data = select_sides(encoded, args, item, coverage)
                else:
                    data, coverage = select(encoded, args, item, coverage)
            envelope = result(symbol, data, context, warnings, conditions=conditions, coverage=coverage, ident=ident, observed_at=observed_at, source_time=when)
            envelope["_full"] = encoded
            results.append(ordered(envelope))
            stopped = context.get("rate_limited", False)
        except (Exception, DeadlineExpired) as exc:
            code = "invalid" if isinstance(exc, InputError) else "rate_limited" if "429" in str(exc) or "RateLimit" in type(exc).__name__ else "upstream"
            stopped = code == "rate_limited"
            fix = (f"Correct the arguments; schema {item.path} reports this command's choices and defaults." if code == "invalid"
                   else "Retry later with fewer targets; remaining targets were not attempted." if code == "rate_limited"
                   else budget.upstream_fix(exc, item, args))
            results.append(ordered(result(symbol, error=error_info(code, exc, fix))))
        finally:
            signal.alarm(0)
    return results


def read(args, saved):
    """Re-read a saved observation through the same selector that printed it the first time.

    Reusing the leaf's own selector rather than a generic JSON pointer is why a slice of a table keeps its column
    names: a pointer into the encoded rows would hand back an unlabelled array.
    """
    record = saved.load(args.id)
    item = leaves.get(*record["command"].split(" ", 1)) if " " in record["command"] else leaves.get(record["command"], "")
    if item is None:
        raise InputError(f"Observation {args.id} came from {record['command']}, which this version no longer offers.")
    coverage = {}
    if output.is_sided(record["data"]) and not args.list_fields:
        data = select_sides(record["data"], args, item, coverage)
    else:
        data, coverage = select(record["data"], args, item, coverage)
    warnings = list(record.get("warnings") or [])
    age = store.age_seconds(record.get("observed_at"))
    if record.get("status") == "empty":
        warnings.append("The original observation returned nothing usable; reading it again does not change that.")
    if output.is_sided(record["data"]):
        sides = [v for v in coverage.values() if isinstance(v, dict) and "received" in v]
        coverage = dict(coverage, received=sum(s["received"] for s in sides), shown=sum(s.get("shown", 0) for s in sides)) if sides else coverage
    shown, received, start = coverage.get("shown"), coverage.get("received"), coverage.get("start", 0)
    extra = {}
    if shown is not None and received is not None and start + shown < received:
        following = start + shown
        extra["continuation"] = {"start": following, "command": budget.read_command(args.id, item, args, shown, following)}
    envelope = result(record["target"], data, record.get("context"), warnings, status=record.get("status") if record.get("status") == "empty" else None,
                      conditions=record.get("conditions"), coverage=coverage, ident=args.id,
                      observed_at=record.get("observed_at"), source_time=record.get("source_time"), extra=extra)
    envelope["stored_age_seconds"] = age
    envelope["_full"] = record["data"]
    return [ordered(envelope)], item


def main():
    args = None
    try:
        parser, parsers = build_parser()
        args = parser.parse_args()
        if args.max_chars < budget.MIN_CHARS:
            raise InputError(f"--max-chars must be >= {budget.MIN_CHARS} so recovery instructions remain readable")
        saved = store.Store(args.store)
        saved.prune(args.ttl_days)
        if args.group == "schema":
            return budget.emit([ordered(result("schema", schema_data(args, parsers)))], args, None, {"scope": args.scope}, scoped=bool(args.scope))
        if args.group == "read":
            results, item = read(args, saved)
            return budget.emit(results, args, item, {"read": args.id})
        validate(args)
        item = leaves.get(args.group, args.leaf)
        yf.config.debug.hide_exceptions = False
        request = {k: v for k, v in vars(args).items() if k not in ("symbols", "store", "ttl_days", "max_chars", "list_fields")}
        return budget.emit(run(args, item, saved, request), args, item, request)
    except InputError as exc:
        fix = "Use --help for this command's arguments, or schema GROUP LEAF for its defaults, units and limits."
        results = [ordered(result("request", error=error_info("invalid", exc, fix)))]
        # 성진: 잘못된 --max-chars 자체가 입력 오류일 때 그 값으로 오류 문서를 재면 too_large가 invalid를 가린다 —
        # 무엇이 틀렸는지 말하는 문서는 틀린 예산의 적용 대상이 아니다.
        reporting = argparse.Namespace(max_chars=max(getattr(args, "max_chars", 0) or 0, GLOBAL_DEFAULTS["max_chars"]))
        return budget.emit(results, reporting, None, None)


if __name__ == "__main__":
    raise SystemExit(main())
