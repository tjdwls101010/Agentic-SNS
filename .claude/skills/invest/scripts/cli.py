# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["yfinance[repair]==1.7.0", "pandas", "numpy"]
#
# [tool.uv]
# exclude-newer = "2026-09-13T13:10:00Z"
# ///
"""Investment research data. `--help` maps the commands; `<command> --help` documents one.

This file is the whole command surface: every command, kind and argument with its help, the closed choices, the argument checks made before any request, the documents --help prints, and the exit codes. What Yahoo returns and what its values mean live in invest/yahoo and arrive in each receipt.
"""
import argparse
from datetime import date, timedelta
import json
import re
import sys

from invest import load, receipts

PROG = "cli.py"
DEFAULTS = {"max_chars": 8000, "ttl_days": 14, "timeout": 30}


class Arg:
    """One argument, and the kinds of its command that take it (None: every kind)."""

    def __init__(self, *flags, kinds=None, **kwargs):
        self.flags, self.kinds, self.kwargs = flags, kinds, kwargs

    @property
    def dest(self):
        return self.kwargs.get("dest") or self.flags[0].lstrip("-").replace("-", "_")

    def add(self, parser):
        kwargs = dict(self.kwargs)
        if not self.flags[0].startswith("-"):
            parser.add_argument(self.dest, **{k: v for k, v in kwargs.items() if k != "dest"})
        else:
            parser.add_argument(*self.flags, **kwargs)


class Command:
    """A command: what it answers, its kinds (each a one-line purpose), its targets, its arguments and what its file holds."""

    def __init__(self, name, purpose, kinds=None, targets="SYMBOL...", args=(), file="result.csv, long format with a target column", failures=None):
        self.name, self.purpose, self.kinds, self.targets = name, purpose, kinds or {}, targets
        self.args, self.file = list(args), file
        self.failures = failures or ["not_found", "no_data", "rate_limited", "upstream", "invalid", "local_io"]


def csv_list(value):
    return [v.strip() for v in value.split(",") if v.strip()]


DATE_HELP = "YYYY-MM-DD"
INTERVALS = ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"]
SEARCH_TYPES = ["all", "stock", "mutualfund", "etf", "index", "future", "currency", "cryptocurrency"]
SCREEN_TYPES = ["equity", "fund", "etf"]
PRESETS = ["aggressive_small_caps", "day_gainers", "day_losers", "growth_technology_stocks", "most_actives", "most_shorted_stocks",
           "small_cap_gainers", "undervalued_growth_stocks", "undervalued_large_caps", "conservative_foreign_funds", "high_yield_bond",
           "portfolio_anchors", "solid_large_growth_funds", "solid_midcap_growth_funds", "top_mutual_funds", "top_etfs_us",
           "top_performing_etfs", "technology_etfs", "bond_etfs"]  # yf.PREDEFINED_SCREENER_QUERIES, checked by tests/invest/test_vocabulary.py
MARKET_REGIONS = ["US", "GB", "ASIA", "EUROPE", "RATES", "COMMODITIES", "CURRENCIES", "CRYPTOCURRENCIES"]  # yf.MarketRegion
# 성진: sector·industry의 region은 MarketRegion이 아니라 ISO 국가 코드이고, Yahoo는 서비스하지 않는 코드에 경고 없이 미국 결과를 준다. 이 목록은
# 각 코드로 top-companies를 불러 미국과 다른 종목이 온 코드만 남긴 실측이다; 바뀌면 test_live의 지역 검사가 실패한다.
DOMAIN_REGIONS = ["US", "AR", "AU", "BR", "CA", "CN", "DE", "DK", "ES", "FI", "FR", "GB", "GR", "HK", "IL", "IN", "IT", "JP", "KR", "MY", "NO", "PT",
                  "QA", "RU", "SE", "SG", "TH", "TR", "TW"]
SECTORS = ["basic-materials", "communication-services", "consumer-cyclical", "consumer-defensive", "energy", "financial-services", "healthcare",
           "industrials", "real-estate", "technology", "utilities"]  # yfinance.const.SECTOR_INDUSTY_MAPPING_LC
SECTOR_PARTS = ["overview", "top-companies", "research-reports", "industries", "top-etfs", "top-funds"]
INDUSTRY_PARTS = ["overview", "top-companies", "research-reports", "top-performing", "top-growth"]
QUERY_HELP = ('JSON {"operator":OP,"operands":[...]}: EQ [field, value]; IS-IN [field, v, ...]; BTWN [field, low, high] inclusive; GT LT GTE LTE '
              '[field, number]; AND OR [query, ...]. A rate is a ratio (0.2 = 20%), translated to Yahoo\'s scale; screen fields gives each field\'s '
              'input_unit and whether its scale was measured, and a rate with an unmeasured scale is refused. Amounts, prices, counts and multiples '
              'are as Yahoo reports them; text fields take screen values.')

SYMBOLS = Arg("targets", nargs="*", metavar="SYMBOL", help="One or more Yahoo symbols (AAPL, 005930.KS, ^GSPC, EURUSD=X); each is a target.")
FIELDS = Arg("--fields", type=csv_list, metavar="A,B", help="Show only these columns or fields inline (identifying columns stay); the file keeps all.")
TIMEOUT = Arg("--timeout", type=int, default=DEFAULTS["timeout"], metavar="SECONDS",
              help="Seconds per target (default 30). A Unix alarm: it stops Python code, not a call blocked inside a native network read.")
MAX_CHARS = Arg("--max-chars", type=int, default=argparse.SUPPRESS, metavar="N",
                help="Largest receipt to print, in characters (default 8000); a larger receipt is cut in the order the receipt section gives.")

COMMANDS = {c.name: c for c in [
    Command("search", "Instruments, news, curated lists or research reports matching a name or keyword.", targets="QUERY",
            args=[Arg("targets", nargs="*", metavar="QUERY", help="A company name, symbol fragment or keyword."),
                  Arg("--dataset", choices=["quotes", "news", "lists", "research"], default="quotes", help="quotes: instrument candidates (csv); news, lists, research: records (json)."),
                  Arg("--type", choices=SEARCH_TYPES, default="all", help="Instrument type, for --dataset quotes only."),
                  Arg("--limit", type=int, default=10, metavar="N", help="Matches asked of the first page (default 10); research takes no count.")],
            file="quotes: result.csv; news, lists, research: result.json, a list of {target, data}",
            failures=["no_data", "rate_limited", "upstream", "invalid", "local_io"]),
    Command("quote", "Current price, session state and market fields: Yahoo's whole info response for each symbol.",
            file="result.json, a list of {target, data} holding every field Yahoo sent (the inline copy shows a default selection)"),
    Command("history", "Price bars with dividends and splits over a range, and whether the last bar is final.",
            args=[Arg("--period", metavar="RANGE", help="Relative range: 5d, 1mo, 1y, ytd, max (default 1mo when no --start or --end); not with --start or --end."),
                  Arg("--start", metavar="DATE", help=f"First day, {DATE_HELP}, inclusive."),
                  Arg("--end", metavar="DATE", help=f"{DATE_HELP}, exclusive: bars on or after it are not returned."),
                  Arg("--interval", choices=INTERVALS, default="1d", help="Bar size. Yahoo limits how far back and how many days per request it serves intraday bars."),
                  Arg("--adjust", choices=["auto", "back", "none"], default="auto", help="auto: OHLC adjusted for splits and dividends; back: Close as traded, Open/High/Low scaled; none: as traded plus Adj Close."),
                  Arg("--repair", action="store_true", help="Apply yfinance's price repair (not with --interval 5d)."),
                  Arg("--prepost", action="store_true", help="Include pre- and post-market bars where Yahoo has them."),
                  Arg("--actions", action="store_true", help="Only dates carrying a dividend, split or capital gain.")],
            failures=["not_found", "no_data", "source_constraint", "rate_limited", "upstream", "invalid", "local_io"]),
    Command("company", "One company's profile, shares outstanding, news entries or SEC filing entries.",
            kinds={"profile": "business description, sector, governance risk, headquarters: the same info response as quote (json)",
                   "shares": "shares outstanding as Yahoo reports it over a date range (csv)",
                   "news": "recent news headlines with publisher, link and time, not the articles (json)",
                   "filings": "SEC filing entries: date, form type, title and a map of each document to Yahoo's copy (json)"},
            args=[Arg("--start", metavar="DATE", kinds=["shares"], help=f"{DATE_HELP}; default about 18 months before --end."),
                  Arg("--end", metavar="DATE", kinds=["shares"], help=f"{DATE_HELP}; default now."),
                  Arg("--limit", type=int, metavar="N", kinds=["news"], help="Entries asked for (default 20).")],
            file="shares: result.csv; profile, news, filings: result.json, a list of {target, data}"),
    Command("financials", "Financial statements and valuation measures by period.",
            kinds={"income": "income statement line items by fiscal period", "balance": "balance sheet line items by fiscal period",
                   "cashflow": "cash flow statement line items by fiscal period", "valuation": "market cap, enterprise value and multiples by period"},
            args=[Arg("--frequency", choices=["yearly", "quarterly", "trailing", "monthly"],
                      help="income, cashflow: yearly (default), quarterly or trailing (TTM); balance: yearly or quarterly; valuation: yearly, quarterly (default), monthly or trailing."),
                  Arg("--periods", type=int, metavar="N", kinds=["valuation"], help="Periods asked of Yahoo besides Current (default 5; 0: Current only).")],
            file="result.csv: one row per target and period, a column per line item"),
    Command("analysts", "Analyst targets, recommendations, rating actions, estimates and growth.",
            kinds={"targets": "consensus price target range against the current price", "recommendations": "recommendation counts this month and the three before",
                   "upgrades": "rating actions with firm, grades and price targets", "eps-estimate": "EPS estimates for this and next quarter and year",
                   "revenue-estimate": "revenue estimates for this and next quarter and year", "eps-history": "reported EPS against the estimate, last four quarters",
                   "revisions": "counts of upward and downward EPS revisions", "trend": "how the consensus EPS moved over 90 days",
                   "growth": "expected growth against industry, sector and index"}),
    Command("holders", "Who owns a company: the ownership breakdown, holder lists and insider activity.",
            kinds={"major": "insider and institutional share of the company, and the institution count", "institutional": "largest institutional holders, shares, value, quarter reported",
                   "funds": "largest mutual fund holders, shares, value, quarter reported", "insider-purchases": "six-month totals of insider purchases and sales",
                   "insider-transactions": "recent insider transactions with dates, roles and values", "insider-roster": "insiders and the shares they hold directly"},
            file="result.csv, long format with a target column; major and insider-purchases: metric, source_column, value, unit"),
    Command("fund", "An ETF's or mutual fund's profile, objective, holdings, allocations and reported statistics.",
            kinds={"overview": "family, category and legal type", "description": "the fund's own objective text (json)", "holdings": "top holdings and their weights",
                   "asset-classes": "allocation across cash, stocks, bonds and others", "sectors": "weight in each sector",
                   "equity": "the P/E, P/B, P/S, P/CF and growth the fund reports for its equity holdings", "operations": "expense ratio, turnover, net assets"},
            file="result.csv, long format with a target column; equity and operations: metric, source_column, value, unit; description: result.json",
            failures=["not_found", "no_data", "not_applicable", "rate_limited", "upstream", "invalid", "local_io"]),
    Command("options", "Option expirations and one expiration's chain.",
            kinds={"expirations": "expiration dates with listed contracts", "chain": "every contract of one expiration, by side"},
            args=[Arg("--date", metavar="DATE", kinds=["chain"], help=f"Expiration, {DATE_HELP}; default the nearest one listed."),
                  Arg("--side", choices=["calls", "puts", "both"], kinds=["chain"], help="Side to return (default both).")]),
    Command("screen", "Screen stocks, funds or ETFs with a query or a preset; list query fields, values and presets.", targets="",
            kinds={"fields": "query fields for --type, each with its input_unit and Yahoo scale status (csv)", "values": "values text fields accept (json)",
                   "presets": "Yahoo's predefined screens with the query each runs, on the skill's scale (json)", "run": "instruments matching --query or --preset (csv)"},
            args=[Arg("--type", choices=SCREEN_TYPES, help="Universe (default equity); a --preset fixes its own."),
                  Arg("--field", metavar="NAME", kinds=["fields", "values"], help="One query field."),
                  Arg("--filter", metavar="TEXT", kinds=["fields", "values", "presets"], help="Case-insensitive text narrowing the catalog."),
                  Arg("--query", metavar="JSON", kinds=["run"], help=QUERY_HELP),
                  Arg("--source-units", action="store_true", kinds=["run"], help="Send --query exactly as written, in Yahoo's own units; the receipt warns."),
                  Arg("--preset", choices=PRESETS, kinds=["run"], help="A predefined screen instead of --query."),
                  Arg("--sort", metavar="FIELD", kinds=["run"], help="Sort field from screen fields (default ticker for --query, the preset's own otherwise)."),
                  Arg("--ascending", action=argparse.BooleanOptionalAction, default=None, kinds=["run"], help="Sort direction (default descending, or the preset's)."),
                  Arg("--limit", type=int, metavar="N", kinds=["run"], help="Rows asked for, at most 250 (default 100)."),
                  Arg("--offset", type=int, metavar="N", kinds=["run"], help="Row offset for the next page (coverage.next_offset gives it).")],
            file="fields, run: result.csv; values, presets: result.json",
            failures=["no_data", "rate_limited", "upstream", "invalid", "local_io"]),
    Command("market", "Market summaries by region, and a sector's or industry's overview, companies, funds or research.", targets="",
            kinds={"summary": "benchmark quotes for a region, one row per exchange", "sector": "one sector (KEY): --dataset picks the part",
                   "industry": "one industry (KEY, from sector --dataset industries): --dataset picks the part"},
            args=[Arg("targets", nargs="*", metavar="KEY", kinds=["sector", "industry"], help=f"sector: {', '.join(SECTORS)}; industry: a key from market sector KEY --dataset industries."),
                  Arg("--region", metavar="CODE", help=f"summary: {', '.join(MARKET_REGIONS)} (default US); sector, industry: {' '.join(DOMAIN_REGIONS)} (default US), the countries Yahoo serves."),
                  Arg("--dataset", metavar="PART", kinds=["sector", "industry"],
                      help=f"sector: {', '.join(SECTOR_PARTS)}; industry: {', '.join(INDUSTRY_PARTS)} (default overview).")],
            file="result.csv, except overview and research-reports: result.json", failures=["no_data", "rate_limited", "upstream", "invalid", "local_io"]),
    Command("calendar", "Earnings, economic, IPO and split events by date, or one company's earnings dates.", targets="",
            kinds={"earnings": "US earnings in the range, or with SYMBOL that company's past and upcoming dates", "economic": "economic releases in the range, every region",
                   "ipo": "IPO listings, filings and amendments in the range", "splits": "splits payable in the range"},
            args=[Arg("targets", nargs="*", metavar="SYMBOL", kinds=["earnings"], help="One symbol for its own earnings dates; not with --start, --end or --most-active."),
                  Arg("--start", metavar="DATE", help=f"{DATE_HELP}, inclusive (default today)."),
                  Arg("--end", metavar="DATE", help=f"{DATE_HELP}, inclusive: --start D --end D is that day (default seven days after --start)."),
                  Arg("--limit", type=int, metavar="N", help="Rows asked for, at most 100 (default 100)."),
                  Arg("--offset", type=int, default=0, metavar="N", help="Row offset for the next page (coverage.next_offset gives it)."),
                  Arg("--most-active", action="store_true", kinds=["earnings"], help="Yahoo's most-active filter; market-wide, at --offset 0 only.")],
            failures=["no_data", "rate_limited", "upstream", "invalid", "local_io"]),
]}
for _command in COMMANDS.values():
    if _command.targets == "SYMBOL...":
        _command.args.insert(0, SYMBOLS)
    _command.args += [FIELDS, TIMEOUT, MAX_CHARS]


# ---- the documents --help prints ------------------------------------------------------------------------------------

RECEIPT = [
    "stdout is one JSON receipt; the whole result is a file under the skill's data/results/<id>/, never overwritten.",
    "  status ok|partial|empty|error, command, receipt_path (receipt.json: every unit, warning, note and time, untrimmed),",
    "  file {path, format, rows, columns} (null when nothing came back), units {column: unit, \"*\": every other column},",
    "  warnings [{code, text}]: facts that change how a value may be used; notes: explanations;",
    "  results, one per target: target, status ok|empty|error|not_attempted, rows, warnings (codes), observed_at (UTC),",
    "  as_of (source times, last bar final|provisional|unknown), currency, financial_currency, coverage (what the rows",
    "  cover; requested, received, next_offset where a count is sent), conditions ({requested, status confirmed|",
    "  not_applied|unverified, evidence}), data (inline rows) or first/last (preview), error {code, message, fix};",
    "  trimmed: cut to fit --max-chars in this order: data, preview, notes, units, per-target detail; projected: a selection.",
    "  units: ratio (0.25 = 25%), multiple, shares, count, rank, money or per_share :quote (currency) | :financial",
    "  (financial_currency) | :unconfirmed, date, datetime, text, unverified (do not compute with it).",
]
EXIT_LINE = "exit codes: " + " · ".join(f"{n} {name}" for name, (n, _) in receipts.EXIT_CODES.items())
GLOBAL_LINE = "before COMMAND: --ttl-days N deletes saved results older than N days (default 14; 0 keeps all)."


def lead():
    return f"usage: {PROG} [--max-chars N] [--ttl-days N]"


def usage(command):
    kind = " KIND" if command.kinds else ""
    targets = {"SYMBOL...": " SYMBOL...", "QUERY": " QUERY", "": ""}[command.targets]
    if command.name == "market":
        targets = " [KEY]"
    if command.name == "calendar":
        targets = " [SYMBOL]"
    return f"{command.name}{kind}{targets}"


def spec(arg):
    kwargs = arg.kwargs
    if not arg.flags[0].startswith("-"):
        typed = kwargs.get("metavar", arg.dest.upper()) + ("..." if arg.dest == "targets" and kwargs.get("metavar") == "SYMBOL" else "")
    elif kwargs.get("action") == argparse.BooleanOptionalAction:
        typed = f"{arg.flags[0]}, --no-{arg.flags[0][2:]}"
    elif kwargs.get("action") == "store_true":
        typed = arg.flags[0]
    elif kwargs.get("choices"):
        typed = f"{arg.flags[0]} {{{','.join(kwargs['choices'])}}}"
    else:
        typed = f"{arg.flags[0]} {kwargs.get('metavar', arg.dest.upper())}"
    tag = f"[{', '.join(arg.kinds)}] " if arg.kinds else ""
    default = kwargs.get("default")
    shown = f" (default {default})" if kwargs.get("choices") and default not in (None, False, argparse.SUPPRESS) else ""
    return f"  {typed}  {tag}{kwargs.get('help', '')}{shown}"


def command_document(command):
    lines = [f"{lead()} {usage(command)} [options]", command.purpose]
    if command.kinds:
        width = max(len(k) for k in command.kinds) + 2
        lines += ["", "kinds:"] + [f"  {k:<{width}}{text}" for k, text in command.kinds.items()]
    lines += ["", "arguments:"] + [spec(a) for a in command.args]
    lines += ["", "receipt:"] + RECEIPT + [f"  file: {command.file}."]
    lines += ["", "failures (error.code): " + ", ".join(command.failures) + "; error.fix says what to do.", EXIT_LINE, GLOBAL_LINE]
    return "\n".join(lines)


def root_document():
    width = max(len(usage(c)) for c in COMMANDS.values()) + 2
    lines = [f"{lead()} COMMAND ...", "Investment research data from Yahoo Finance. stdout: one JSON receipt; the whole result is a file under data/.",
             "`COMMAND --help` states that command's kinds, arguments, receipt, failures and exit codes.", "", "commands:"]
    for command in COMMANDS.values():
        kinds = " | ".join(command.kinds) if command.kinds else command.purpose.split(":")[0].rstrip(".")
        lines.append(f"  {usage(command):<{width}}{kinds}")
    lines += ["", "options:", "  --max-chars N  largest receipt to print, in characters (default 8000); also accepted after the command",
              "  --ttl-days N   delete saved results older than N days (default 14; 0 keeps everything); before COMMAND only", "", EXIT_LINE]
    return "\n".join(lines)


class Document(argparse.Action):
    """-h/--help: print a document and exit before any other argument is checked or anything is opened."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, render=None, help=None):
        super().__init__(option_strings, dest, default=default, nargs=0, help=help)
        self.render = render

    def __call__(self, parser, namespace, values, option_string=None):
        print(self.render())
        parser.exit()


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, render=None, **kwargs):
        kwargs.setdefault("add_help", False)
        kwargs.setdefault("allow_abbrev", False)
        super().__init__(*args, **kwargs)
        if render:
            self.add_argument("-h", "--help", action=Document, render=render)

    def error(self, message):
        raise receipts.Invalid(message)


def build_parser():
    parser = Parser(prog=PROG, render=root_document)
    parser.add_argument("--max-chars", type=int, default=DEFAULTS["max_chars"])
    parser.add_argument("--ttl-days", type=int, default=DEFAULTS["ttl_days"])
    sub = parser.add_subparsers(dest="name", required=True, parser_class=Parser)
    for command in COMMANDS.values():
        p = sub.add_parser(command.name, render=lambda command=command: command_document(command))
        if command.kinds:
            p.add_argument("kind", choices=list(command.kinds), metavar="KIND")
        for arg in command.args:
            arg.add(p)
    return parser


# ---- checks before any request, and the arguments in force ----------------------------------------------------------

def check_date(name, value):
    if value is None:
        return
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise receipts.Invalid(f"--{name} expects {DATE_HELP}, got {value!r}") from None


def given(args, arg):
    value = getattr(args, arg.dest, None)
    return value not in (None, False, []) and value is not argparse.SUPPRESS


def refuse(condition, message, fix=None):
    if condition:
        raise receipts.Invalid(message, fix=fix)


def prepare(command, args):
    """Check the arguments and fill in the defaults that depend on the kind; nothing is opened or requested here."""
    kind = getattr(args, "kind", None)
    for arg in command.args:
        if arg.kinds and kind not in arg.kinds and given(args, arg):
            name = arg.kwargs.get("metavar", arg.dest.upper()) if arg.dest == "targets" else arg.flags[0]
            raise receipts.Invalid(f"{name} applies to {command.name} {' or '.join(arg.kinds)}, not {kind}")
    refuse(getattr(args, "timeout", 1) <= 0, "--timeout must be a positive number of seconds")
    refuse(args.ttl_days < 0, "--ttl-days must be 0 or more; 0 keeps every saved result")
    refuse(args.max_chars <= 0, "--max-chars must be positive")
    for name in ("start", "end", "date"):
        check_date(name, getattr(args, name, None))
    targets = list(args.targets or []) if hasattr(args, "targets") else []
    refuse(any(not t.strip() for t in targets), "Targets must not be empty")
    name = command.name
    if command.targets == "SYMBOL...":
        refuse(not targets, f"{name} needs at least one SYMBOL")
    handler = globals().get(f"prepare_{name}")
    if handler:
        handler(args, targets)
    if getattr(args, "limit", None) is not None:
        refuse(args.limit < 1, "--limit must be at least 1")
    if getattr(args, "offset", None) is not None:
        refuse(args.offset < 0, "--offset must be 0 or more")
    if not hasattr(args, "label"):
        args.label = targets
    args.command = f"{name} {kind}" if kind else name
    args.targets = args.label
    return f"{name}.{kind}" if kind else name


def prepare_search(args, targets):
    refuse(len(targets) != 1, "search takes one QUERY; quote it if it has spaces")
    refuse(args.dataset != "quotes" and args.type != "all", "--type filters instrument candidates only; use it with --dataset quotes")
    args.query = targets[0]


def prepare_history(args, targets):
    refuse(args.period and (args.start or args.end), "--period cannot be combined with --start or --end")
    refuse(args.period and not re.fullmatch(r"([1-9][0-9]*(d|wk|mo|y)|ytd|max)", args.period), "--period expects a range such as 5d, 1mo, 1y, ytd or max")
    refuse(args.start and args.end and args.start >= args.end, "--end is exclusive, so it must be after --start")
    refuse(args.repair and args.interval == "5d", "yfinance does not repair five-day bars", "Drop --repair, or choose another --interval such as 1d or 1wk.")
    if not (args.period or args.start or args.end):
        args.period = "1mo"


def prepare_company(args, targets):
    if args.kind == "news":
        args.limit = 20 if args.limit is None else args.limit
    if args.kind == "shares":
        refuse(args.start and args.end and args.start > args.end, "--start must not be after --end")


def prepare_financials(args, targets):
    allowed = {"income": ("yearly", "quarterly", "trailing"), "cashflow": ("yearly", "quarterly", "trailing"), "balance": ("yearly", "quarterly"),
               "valuation": ("yearly", "quarterly", "monthly", "trailing")}[args.kind]
    args.frequency = args.frequency or ("quarterly" if args.kind == "valuation" else "yearly")
    refuse(args.frequency not in allowed, f"financials {args.kind} takes --frequency {', '.join(allowed)}")
    if args.kind == "valuation":
        args.periods = 5 if args.periods is None else args.periods
        refuse(args.periods < 0, "--periods must be 0 or more")


def prepare_options(args, targets):
    if args.kind == "chain":
        args.side = args.side or "both"


def prepare_screen(args, targets):
    if args.kind == "run":
        refuse(bool(args.query) == bool(args.preset), "screen run needs exactly one of --query or --preset")
        refuse(args.source_units and not args.query, "--source-units applies to --query")
        refuse(args.preset and args.type is not None, "A --preset fixes its own universe; drop --type")
        args.limit = 100 if args.limit is None else args.limit
        refuse(args.limit > 250, "Yahoo returns at most 250 screen rows per request; use --limit 250 and --offset for the next page")
        args.offset = 0 if args.offset is None else args.offset
        args.label = [args.preset or "query"]
    else:
        args.label = [args.type or "equity"]
    args.type = args.type or ("equity" if not getattr(args, "preset", None) else None)


def prepare_market(args, targets):
    if args.kind == "summary":
        refuse(targets, "market summary takes no KEY")
        args.region = args.region or "US"
        refuse(args.region not in MARKET_REGIONS, f"market summary --region is one of {', '.join(MARKET_REGIONS)}")
        args.label = [args.region]
        return
    refuse(len(targets) != 1, f"market {args.kind} takes one KEY")
    args.key = targets[0]
    refuse(args.kind == "sector" and args.key not in SECTORS, f"Unknown sector {args.key}; the sectors are {', '.join(SECTORS)}")
    args.region = args.region or "US"
    refuse(args.region not in DOMAIN_REGIONS, f"--region {args.region} is not served for sectors and industries; the served codes are {' '.join(DOMAIN_REGIONS)}")
    parts = SECTOR_PARTS if args.kind == "sector" else INDUSTRY_PARTS
    args.dataset = args.dataset or "overview"
    refuse(args.dataset not in parts, f"market {args.kind} --dataset is one of {', '.join(parts)}")
    args.label = [args.key]


def prepare_calendar(args, targets):
    args.limit = 100 if args.limit is None else args.limit
    refuse(args.limit > 100, "Yahoo returns at most 100 calendar rows per request; use --offset for the next page")
    refuse(len(targets) > 1, "calendar earnings takes at most one SYMBOL")
    args.symbol = targets[0] if targets else None
    if args.symbol:
        refuse(args.start or args.end or args.most_active, "One company's earnings dates take --limit and --offset, not --start, --end or --most-active")
        args.label = [args.symbol]
        return
    refuse(args.most_active and args.offset, "--most-active works at --offset 0 only")
    args.start = args.start or date.today().isoformat()
    args.end = args.end or (date.fromisoformat(args.start) + timedelta(days=7)).isoformat()
    refuse(args.start > args.end, "--end is inclusive and must not be before --start")
    args.label = [f"{args.start}..{args.end}"]


def emit(document):
    print(json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
    return receipts.exit_code(document)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    command_text = None
    try:
        args = build_parser().parse_args(argv)
        command = COMMANDS[args.name]
        command_text = f"{args.name} {getattr(args, 'kind', '')}".strip()
        key = prepare(command, args)
        document, code = load.run(key, args)
        print(json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":")))
        return code
    except receipts.Invalid as exc:
        return emit(receipts.invalid(command_text, exc))


if __name__ == "__main__":
    raise SystemExit(main())
