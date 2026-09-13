"""Purpose-oriented Yahoo Finance CLI. Discover contracts with schema and --help."""
import argparse
import contextlib
from datetime import date, timedelta
import re
import signal
import sys

import yfinance as yf

import company
import market
import prices
from output import InputError, emit, error_info, result, select

GLOBAL_DEFAULTS = {"max_chars": 20000, "filter": ""}

COMMANDS = {
    "search": {"": "Find instrument candidates by name, symbol and asset type; only the first Lookup page is available."},
    "prices": {"quote": "Current quote and company market fields.", "history": "Price start is inclusive; end is exclusive. Naive dates use the exchange timezone.", "actions": "Dividends, splits and capital gains over the selected price range; start inclusive, end exclusive."},
    "company": {"profile": "Company profile and quote metadata.", "shares": "Historical shares outstanding (full shares query; deprecated shares is not used).", "news": "Related articles; links are not full article contents.", "filings": "SEC filing links and metadata; use the SEC skill for original filing contents.", "sustainability": "Reported sustainability metrics."},
    "financials": {"income": "Native income statement items by fiscal period; earnings aliases merge here.", "balance": "Native balance sheet items by fiscal period; TTM is unavailable.", "cashflow": "Native cash flow items by fiscal period.", "valuation": "Valuation measures by period; Current is a snapshot, not a fiscal period."},
    "analysts": {"targets": "Analyst price targets.", "recommendations": "Recommendation counts by period.", "summary": "Recommendation summary.", "upgrades": "Rating upgrade and downgrade history.", "earnings-estimate": "Earnings estimates.", "revenue-estimate": "Revenue estimates.", "history": "Historical earnings estimates and actuals.", "revisions": "EPS revisions.", "trend": "EPS estimate trends.", "growth": "Growth estimates."},
    "holders": {"major": "Major holder breakdown.", "institutional": "Institutional holders.", "fund": "Mutual fund holders.", "insider-purchases": "Insider purchase summary.", "insider-transactions": "Insider transactions.", "insider-roster": "Insider ownership roster."},
    "fund": {"overview": "Fund overview.", "description": "Fund investment description.", "holdings": "Top reported holdings, not a complete portfolio.", "asset-classes": "Asset allocation.", "sector-weights": "Sector allocation.", "equity": "Equity holding metrics.", "bond": "Bond holding metrics.", "rating": "Bond rating allocation.", "operations": "Fund operational metrics."},
    "options": {"expirations": "Available option expiration dates.", "chain": "Option contracts for an expiration and side; discover dates with options expirations."},
    "screen": {"presets": "Available named screeners.", "fields": "Filterable query field catalog, using public valid_fields.", "values": "Filterable allowed values, using public valid_values.", "run": "Run a preset or JSON query; equity, fund and ETF query types are supported."},
    "market": {"status": "Trading status; Yahoo may not provide regional status outside US.", "summary": "Market benchmark summary.", "sectors": "Sector keys accepted by market sector.", "sector": "Sector overview, industries, companies, funds or research.", "industry": "Industry overview, companies or research; discover keys through market sector --dataset industries."},
    "calendar": {"earnings": "With SYMBOL: earnings dates via get_earnings_dates, no date filter. Without SYMBOL: market earnings, native US scope, most-active filtering OFF by default; startdatetime >= start and <= end.", "economic": "Economic events: native startdatetime >= start and <= end; country appears per row.", "ipo": "IPO events: native gtelt range matches ANY of listing startdatetime, filingdate or amendeddate; endpoint boundary semantics are not independently verified.", "splits": "Split calendar: payable startdatetime >= start and <= end."},
}
QUERY_HELP = '''JSON query: {"operator":OP,"operands":[...]}; field names come from screen fields, enumerated values from screen values.
EQ [field, string|finite number] (2 operands); IS-IN [field, value, ...] (2+ operands).
BTWN [field, number, number] (3 operands, inclusive lower/upper); GT, LT, GTE, LTE [field, finite number] (2 operands).
AND, OR [query, query, ...] (2+ nested query objects). Booleans, null, NaN and Infinity are not query values.
Nested example: {"operator":"AND","operands":[{"operator":"EQ","operands":["region","us"]},{"operator":"GT","operands":["intradaymarketcap",2000000000]}]}
Use --query 'JSON' or --preset NAME. Fields and values can be narrowed with --filter TEXT and --field NAME.'''


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class", argparse.RawTextHelpFormatter)
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise InputError(message)


def common(parser, selection=True, root=False):
    parser.add_argument("--max-chars", type=int, default=GLOBAL_DEFAULTS["max_chars"] if root else argparse.SUPPRESS, help="Maximum JSON characters; oversized data is replaced by a recovery error, never truncated.")
    parser.add_argument("--filter", default=GLOBAL_DEFAULTS["filter"] if root else argparse.SUPPRESS, help="Case-insensitive substring for schema, catalogs or --list-fields.")
    if selection:
        parser.add_argument("--fields", type=lambda value: value.split(","), help="Comma-separated exact output fields; financial statement fields are native line items.")
        parser.add_argument("--list-fields", action="store_true", help="Discover available fields for this dataset/target instead of returning values.")
        parser.add_argument("--limit", type=int, help="Maximum output rows; list APIs also receive this count. History/financial limits are local selection.")
        parser.add_argument("--timeout", type=int, default=30, help="Wall-clock seconds per target (includes library calls); default 30.")


def dates(parser):
    parser.add_argument("--start", help="ISO date YYYY-MM-DD; interpretation is described for this dataset.")
    parser.add_argument("--end", help="ISO date YYYY-MM-DD; prices exclude end, calendars use native date predicates.")


def build_parser():
    parser = Parser(description="Query Yahoo Finance data by purpose. stdout: one JSON document; diagnostics: stderr. Discover with schema [GROUP [LEAF]].")
    common(parser, False, root=True)
    groups = parser.add_subparsers(dest="group", required=True)
    schema = groups.add_parser("schema", help="Discover inputs and output contracts offline")
    schema.add_argument("scope", nargs="*")
    common(schema, False)
    leaves = {}
    for group, commands in COMMANDS.items():
        gp = groups.add_parser(group, help="; ".join(commands) if group != "search" else "Find instruments and supported search results")
        sub = gp.add_subparsers(dest="leaf", required=True) if group != "search" else None
        for leaf, description in commands.items():
            p = sub.add_parser(leaf, description=description, help=description) if sub else gp
            if not sub:
                p.description = description
                p.set_defaults(leaf="")
            leaves[group, leaf] = p
            common(p)
            if group == "calendar":
                p.set_defaults(limit=12)
            elif group == "search" or (group, leaf) == ("company", "news"):
                p.set_defaults(limit=10)
            elif (group, leaf) == ("screen", "run"):
                p.set_defaults(limit=25)
            if group in {"prices", "company", "financials", "analysts", "holders", "fund", "options"}:
                p.add_argument("symbols", nargs="+", help="One or more Yahoo symbols; each is queried separately.")
            if group == "prices" and leaf in {"history", "actions"}:
                dates(p)
                p.add_argument("--period", help="Relative range such as 5d, 1mo, 1y, ytd or max; default 1mo only when start/end are absent.")
                p.add_argument("--interval", choices=["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"], default="1d")
                p.add_argument("--adjust", choices=["none", "auto", "back"], default="auto", help="Price adjustment; none retains Adj Close, auto adjusts OHLC, back adjusts OHL.")
                p.add_argument("--repair", action="store_true", help="Opt into yfinance price repair; OFF by default.")
                p.add_argument("--prepost", action="store_true", help="Include pre/post-market data where available.")
            if group == "company" and leaf == "shares":
                dates(p)
            if group == "company" and leaf == "news":
                p.add_argument("--tab", choices=["news", "all", "press releases"], default="news")
            if group == "financials":
                p.add_argument("--frequency", choices=["yearly", "quarterly"] if leaf == "balance" else ["yearly", "quarterly", "monthly", "trailing"] if leaf == "valuation" else ["yearly", "quarterly", "trailing"], default="quarterly" if leaf == "valuation" else "yearly", help="trailing means TTM; statement dates are fiscal period ends.")
                p.add_argument("--periods", type=int, default=5, help="Maximum periods; valuation sends this upstream (0 = Current only), statements select locally.")
            if group == "options" and leaf == "chain":
                p.add_argument("--date", help="Expiration YYYY-MM-DD; omitted selects nearest available expiry.")
                p.add_argument("--side", choices=["calls", "puts", "both"], default="both")
            if group == "search":
                p.add_argument("query")
                p.add_argument("--type", choices=["all", "stock", "mutualfund", "etf", "index", "future", "currency", "cryptocurrency"], default="all")
                p.add_argument("--dataset", choices=["quotes", "news", "lists", "research", "nav"], default="quotes")
            if group == "screen":
                p.add_argument("--type", choices=["equity", "fund", "etf"], default="equity")
                if leaf in {"fields", "values"}:
                    p.add_argument("--field", help="Exact query field, useful for allowed-value lookup.")
                if leaf == "run":
                    p.epilog = QUERY_HELP
                    q = p.add_mutually_exclusive_group(required=True)
                    q.add_argument("--query", help="JSON operator/operands object; see examples below.")
                    q.add_argument("--preset", help="Preset name from screen presets.")
                    p.add_argument("--offset", type=int, default=0)
                    p.add_argument("--sort", help="Sort field from screen fields; custom query default ticker, preset uses its defined sort.")
                    p.add_argument("--ascending", action=argparse.BooleanOptionalAction, default=None)
            if group == "market":
                if leaf in {"status", "summary"}:
                    p.add_argument("--region", choices=[r.value for r in yf.MarketRegion], default="US")
                if leaf in {"sector", "industry"}:
                    p.add_argument("key")
                    p.add_argument("--region", default="US", help="Yahoo region code.")
                    choices = ["overview", "top-companies", "research-reports"] + (["industries", "top-etfs", "top-funds"] if leaf == "sector" else ["top-performing", "top-growth"])
                    p.add_argument("--dataset", choices=choices, default="overview")
            if group == "calendar":
                dates(p)
                p.add_argument("--offset", type=int, default=0, help="Remote row offset; next_offset advances by displayed rows, not native batch size.")
                if leaf == "earnings":
                    p.add_argument("symbol", nargs="?", help="Optional single symbol; omit for market-wide US earnings.")
                    p.add_argument("--most-active", action="store_true", help="Opt into native most-active filter; only market earnings at offset 0.")
    return parser, leaves


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


def describe(parser, group, leaf):
    defaults = argparse.Namespace(group=group, leaf=leaf, **{a.dest: a.default for a in parser._actions if a.dest != "help"})
    resolve_defaults(defaults)
    return {"description": parser.description, "arguments": {a.option_strings[-1] if a.option_strings else a.dest: {"help": a.help, "default": GLOBAL_DEFAULTS.get(a.dest) if a.default == argparse.SUPPRESS else getattr(defaults, a.dest, a.default), "choices": a.choices, "required": a.required} for a in parser._actions if a.dest != "help"}, "notes": parser.epilog, "default_context": "Defaults resolve for omitted options on this host at schema time; supplied dates disable the default price period, and presets select their own universe and sort.", "output": {"table": ["index", "columns", "data", "index_names", "column_names"], "statuses": ["ok", "empty", "partial", "error", "not_attempted"], "exit_codes": {"ok": 0, "invalid": 2, "rate_limited": 5, "upstream": 6, "empty": 7, "partial": 8, "too_large": 9}, "empty": "Not proof of absence", "selection": "--fields selects output fields; --list-fields discovers target-specific fields; --limit clips rows locally even if upstream returns more."}}


def schema_data(args, leaves):
    scope = tuple(args.scope)
    if len(scope) > 2 or (scope and scope[0] not in COMMANDS):
        raise InputError("schema expects an existing GROUP [LEAF]")
    if scope == ("search",):
        scope = ("search", "")
    if len(scope) == 2:
        if scope not in leaves:
            raise InputError("Unknown schema leaf; use schema GROUP")
        data = describe(leaves[scope], *scope)
        if args.filter:
            data["arguments"] = {k: v for k, v in data["arguments"].items() if args.filter.lower() in (k + str(v)).lower()}
        return data
    commands = COMMANDS[scope[0]] if scope else COMMANDS
    return {"commands": {k: v for k, v in commands.items() if args.filter.lower() in (k + str(v)).lower()}, "next": "schema GROUP LEAF for full inputs and output contract"}


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
    for name in ("start", "end", "date"):
        value = getattr(args, name, None)
        if value is not None:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                raise InputError(f"--{name} expects YYYY-MM-DD") from None
    start, end = getattr(args, "start", None), getattr(args, "end", None)
    if start and end and (start > end or (args.group == "prices" and start == end)):
        raise InputError("Invalid date range; price start must precede exclusive end, calendar start may equal inclusive end")
    if hasattr(args, "period"):
        if args.period and (start or end):
            raise InputError("--period cannot be combined with --start or --end")
        if args.period and not re.fullmatch(r"([1-9][0-9]*(d|wk|mo|y)|ytd|max)", args.period):
            raise InputError("--period expects a positive range such as 5d, 1mo, 1y, ytd or max")
    if args.group == "calendar":
        if args.limit > 100:
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
    if args.group == "calendar" and not getattr(args, "symbol", None) and args.start > args.end:
        raise InputError("Calendar --end precedes the applied --start")
    if args.fields and any(not f for f in args.fields):
        raise InputError("--fields requires nonempty comma-separated field names")


class DeadlineExpired(BaseException):
    """Bypass upstream broad Exception handlers so a CLI deadline stays bounded."""


def timed_out(signum, frame):
    raise DeadlineExpired("Target exceeded --timeout; narrow the request or raise --timeout")


def main():
    try:
        parser, leaves = build_parser()
        args = parser.parse_args()
        if args.max_chars < 1000:
            raise InputError("--max-chars must be >= 1000 so recovery instructions remain readable")
        if args.group == "schema":
            return emit([result("schema", {"scope": args.scope}, schema_data(args, leaves))], args.max_chars)
        validate(args)
        yf.config.debug.hide_exceptions = False
        request = {k: v for k, v in vars(args).items() if k != "symbols"}
        results = []
        stopped = False
        for symbol in getattr(args, "symbols", [getattr(args, "symbol", None) or getattr(args, "query", None) or getattr(args, "key", None) or args.group]):
            if stopped:
                results.append(result(symbol, request, status="not_attempted", error=error_info("not_attempted", "Stopped after rate limiting", "Retry later with fewer targets.")))
                continue
            context, warnings = {}, []
            try:
                signal.signal(signal.SIGALRM, timed_out)
                signal.alarm(args.timeout)
                with contextlib.redirect_stdout(sys.stderr):
                    if args.group in {"search", "screen", "market", "calendar"}:
                        data = market.fetch(args, context, warnings)
                    else:
                        ticker = yf.Ticker(symbol)
                        data = prices.fetch(ticker, args, context, warnings) if args.group == "prices" and args.leaf in {"history", "actions"} else company.fetch(ticker, args, context, warnings)
                    if (args.group, args.leaf) != ("options", "chain"):
                        data = select(data, args, context)
                results.append(result(symbol, request, data, context, warnings))
                stopped = context.get("rate_limited", False)
            except (Exception, DeadlineExpired) as exc:
                code = "invalid" if isinstance(exc, InputError) else "rate_limited" if "429" in str(exc) or "RateLimit" in type(exc).__name__ else "upstream"
                stopped = code == "rate_limited"
                results.append(result(symbol, request, context=context, warnings=warnings, error=error_info(code, exc, f"Use schema {args.group} {args.leaf} to correct inputs." if code == "invalid" else "Retry later with fewer targets; remaining targets were not attempted." if code == "rate_limited" else "Retry later or verify the symbol/dataset; use --timeout SECONDS if the target timed out.")))
            finally:
                signal.alarm(0)
        return emit(results, args.max_chars)
    except InputError as exc:
        return emit([result("request", {}, error=error_info("invalid", exc, "Use --help or schema GROUP LEAF."))])


if __name__ == "__main__":
    raise SystemExit(main())
