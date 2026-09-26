# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["yfinance[repair]==1.7.0", "pandas", "numpy"]
#
# [tool.uv]
# exclude-newer = "2026-09-13T13:10:00Z"
# ///
"""Purpose-oriented Yahoo Finance CLI. Discover contracts with schema and --help.

This file is the whole command surface: every argument and its help, the closed choices, the argument defaults and
checks, the recovery arguments each command names, and the exit codes. What Yahoo returns and what its values mean
live in yfinance_skill/yahoo, joined to a command here by its `dataset` key.
"""
import argparse
from datetime import date, timedelta
import re

from yfinance_skill import budget, querying, schema
from yfinance_skill.envelope import InputError, error_info, ordered, result

EXIT_CODES = {"ok": 0, "invalid": 2, "local_io": 4, "rate_limited": 5, "upstream": 6, "empty": 7, "partial": 8, "too_large": 9}


def exit_code(status, codes):
    """A printed document's status as an exit code; a document with no usable result takes its most actionable error."""
    if status in ("ok", "partial", "empty", "too_large"):
        return EXIT_CODES[status]
    for code in ("rate_limited", "invalid", "local_io"):
        if code in codes:
            return EXIT_CODES[code]
    return EXIT_CODES["upstream"]


# ---- shared arguments and declaration tools -----------------------------------------------------------------------

GLOBAL_DEFAULTS = {"max_chars": 20000, "filter": "", "ttl_days": 14}

OUT_HELP = ("Write this observation's rows to a new CSV file and print only a summary: every digit and timestamp as saved, one target column, "
            "table indices as columns, option sides as side, mapping keys as key, lists of values as value, nested records as dotted columns, "
            "other objects and lists as JSON cells, nulls as blank cells, and a name that would collide prefixed source. — read the returned columns. "
            "The screen's default window and projection do not apply; an explicit --fields or --limit does. Commands that ask the source for a set number of rows "
            "(news, screen, calendars) still ask for their default unless --limit raises it, and no further pages are fetched. "
            "Targets with nothing selected add no rows and no file is made when none do, so check each target's status before comparing. An existing file is never overwritten.")

# 성진: 공통 인자는 49개 리프 schema마다 반복되면 리프 고유 계약을 묻는다(prices history 4,094자 중 약 1.5k). 루트에 한 번.
SHARED = {
    "max_chars": "every command, before the group or after the whole command",
    "filter": "schema, catalog commands (screen presets/fields/values, market sectors) and --list-fields",
    "store": "every command; read needs the store an id was saved in",
    "fields": "every data command and read",
    "list_fields": "every data command and read",
    "limit": "every data command and read; screen caps it at 250 and calendar at 100",
    "timeout": "every data command, per target",
    "out": "data commands whose results are rows (absent from single-record commands such as prices quote), and read",
    "ttl_days": "before the group only",
}
POINTER = "schema (no scope) describes the shared arguments (--fields, --list-fields, --limit, --timeout, --out, --max-chars, --filter, --store) and the envelope, statuses and exit codes every result uses"


def add_common(parser, selection=True, root=False):
    parser.add_argument("--max-chars", type=int, default=GLOBAL_DEFAULTS["max_chars"] if root else argparse.SUPPRESS, help="Maximum JSON characters. Each command's own default window is what keeps a result to one screen; this is the safety boundary behind it.")
    parser.add_argument("--filter", default=GLOBAL_DEFAULTS["filter"] if root else argparse.SUPPRESS, help="Case-insensitive substring for schema, catalogs or --list-fields.")
    parser.add_argument("--store", default=argparse.SUPPRESS if not root else None, help="Directory holding saved observations; the same path is needed to read an earlier id. Defaults to the user cache, or $YF_STORE.")
    if selection:
        parser.add_argument("--fields", type=lambda value: [f.strip() for f in value.split(",")], help="Comma-separated output fields, replacing this command's default projection. Nested payloads take dotted paths such as content.title; --list-fields names them.")
        parser.add_argument("--list-fields", action="store_true", help="Name the fields available for this dataset and target instead of returning values.")
        parser.add_argument("--limit", type=int, help="Maximum output rows, replacing this command's default window. schema reports which end of the series a limit keeps.")
        parser.add_argument("--timeout", type=int, default=30, help="Wall-clock seconds per target (includes library calls); default 30.")


class Arg:
    """One argparse argument. `minimum` is checked after parsing, with the same message for every command."""

    def __init__(self, *flags, minimum=None, **kwargs):
        self.flags, self.minimum, self.kwargs = flags, minimum, kwargs

    @property
    def dest(self):
        return self.kwargs.get("dest") or self.flags[-1].lstrip("-").replace("-", "_")

    def add(self, parser):
        parser.add_argument(*self.flags, **self.kwargs)


class OneOf:
    """Arguments of which exactly one (or at most one) is given."""

    def __init__(self, *args, required=False):
        self.args, self.required = args, required

    def add(self, parser):
        group = parser.add_mutually_exclusive_group(required=self.required)
        for arg in self.args:
            arg.add(group)


def dates(help_start, help_end):
    return [Arg("--start", help=help_start), Arg("--end", help=help_end)]


class Command:
    """One command a caller can type. `dataset` names what it reads in yfinance_skill/yahoo.

    `defaults` fills the namespace (execution, schema and the echoed request all read it), `check` only reads it, and
    `forbidden` names the narrowings this call's own mode rejects so a recovery never recommends them. `narrow` is
    every argument a recovery may name, and `coarser` the new request a budget-cut series can step up to.
    """

    def __init__(self, group, name, purpose, dataset, *, args=(), defaults=None, check=None, narrow=(), forbidden=None,
                 coarser=None, end_exclusive=False, epilog=None, exportable=True):
        self.group, self.name, self.purpose, self.dataset = group, name, purpose, dataset
        self.args, self.defaults, self.check, self.narrow = tuple(args), defaults, check, tuple(narrow)
        self.forbidden, self.coarser, self.end_exclusive = forbidden, coarser, end_exclusive
        self.epilog, self.exportable = epilog, exportable

    @property
    def path(self):
        return self.group + (" " + self.name if self.name else "")

    def positionals(self):
        """The targets this command is asked about: its positional arguments, never an option that happens to share a name."""
        return [arg.dest for arg in self.args if isinstance(arg, Arg) and not arg.flags[0].startswith("-")]

    def minimums(self):
        return {arg.dest: arg.minimum for arg in self.args if isinstance(arg, Arg) and arg.minimum is not None}


# ---- argument bundles and closed choices ----------------------------------------------------------------------------

SYMBOLS = Arg("symbols", nargs="+", help="One or more Yahoo symbols; each is queried separately.")
FROM = Arg("--from", dest="from_id", help="Read this saved observation instead of making a new request. prices quote and company profile select different sides of the same assembled response, so the second one costs nothing.")

INTERVALS = ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"]
BAR_ARGS = [SYMBOLS, *dates("ISO date YYYY-MM-DD; inclusive.", "ISO date YYYY-MM-DD; exclusive, so the last bar returned is the day before."),
            Arg("--period", help="Relative range such as 5d, 1mo, 1y, ytd or max; default 1mo only when start/end are absent."),
            Arg("--interval", choices=INTERVALS, default="1d", help="Bar size. Intraday intervals carry range limits the source enforces; schema prices history reports those limits."),
            Arg("--adjust", choices=["none", "auto", "back"], default="auto", help="none: unadjusted OHLC as supplied plus Adj Close; auto: Open/High/Low/Close scaled for splits and dividends, Adj Close removed; back: Close kept raw while Open/High/Low are scaled by the adjustment ratio, Adj Close removed."),
            Arg("--repair", action="store_true", help="Opt into yfinance price repair; OFF by default."),
            Arg("--prepost", action="store_true", help="Include pre/post-market data where available.")]

FREQUENCY_HELP = "trailing means TTM, a rolling twelve months rather than a completed fiscal period."
PERIODS_HELP = "Maximum periods; valuation sends this upstream (0 = Current only), statements select locally."


def periods(minimum):
    return Arg("--periods", type=int, default=5, minimum=minimum, help=PERIODS_HELP)


SEARCH_TYPES = ["all", "stock", "mutualfund", "etf", "index", "future", "currency", "cryptocurrency"]

TYPE = Arg("--type", choices=["equity", "fund", "etf"], default="equity", help="Query universe; fields, values and presets differ per type.")
FIELD = Arg("--field", help="Exact query field, useful for allowed-value lookup.")
QUERY_HELP = '''JSON query: {"operator":OP,"operands":[...]}; field names come from screen fields, enumerated values from screen values.
EQ [field, string|finite number] (2 operands); IS-IN [field, value, ...] (2+ operands).
BTWN [field, number, number] (3 operands, inclusive lower/upper); GT, LT, GTE, LTE [field, finite number] (2 operands).
AND, OR [query, query, ...] (2+ nested query objects). Booleans, null, NaN and Infinity are not query values.
Nested example: {"operator":"AND","operands":[{"operator":"EQ","operands":["region","us"]},{"operator":"GT","operands":["intradaymarketcap",2000000000]}]}
Use --query 'JSON' or --preset NAME. Fields and values can be narrowed with --filter TEXT and --field NAME.'''

MARKET_REGIONS = ["US", "GB", "ASIA", "EUROPE", "RATES", "COMMODITIES", "CURRENCIES", "CRYPTOCURRENCIES"]  # yf.MarketRegion in yfinance 1.7.0
# 성진: Sector·Industry의 region은 yf.MarketRegion(US/GB/ASIA/EUROPE/…)이 아니라 ISO 3166-1 alpha-2다 — 다른 이름공간이라
# MarketRegion을 choices로 쓰면 실제로 동작하는 KR·JP·DE가 거절된다. 아래 목록은 실측이다: 각 코드로 top-companies를
# 부르고 US와 같은 종목이 오면 조용한 대체로 판정했다. ZZ·XX·UK·EU와 NL·CH·IE·ZA 등은 전부 그 대체에 걸렸다.
DOMAIN_REGIONS = ["US", "AR", "AU", "BR", "CA", "CN", "DE", "DK", "ES", "FI", "FR", "GB", "GR", "HK", "IL", "IN", "IT", "JP", "KR", "MY", "NO", "PT", "QA", "RU", "SE", "SG", "TH", "TR", "TW"]


def domain_args(datasets):
    # 성진: 닫힌 선택지가 G1을 인터페이스 층에서 없앤다 — 서비스되지 않는 코드는 경고 없이 미국 데이터를 돌려줬다.
    return [Arg("key", help="Sector key from market sectors, or industry key from market sector KEY --dataset industries."),
            Arg("--region", choices=DOMAIN_REGIONS, default="US", help="Country code, restricted to the regions Yahoo serves; others return the United States result with no warning. Outside the US the name column arrives null."),
            Arg("--dataset", choices=["overview", "top-companies", "research-reports"] + datasets, default="overview", help="Part of the sector or industry to return.")]


RANGE = [*dates("ISO date YYYY-MM-DD; inclusive. Defaults to today for market-wide calendars.", "ISO date YYYY-MM-DD; inclusive, so --start D --end D returns that day. Defaults to seven days after --start."),
         Arg("--offset", type=int, default=0, help="Remote row offset; next_offset advances by displayed rows, not native batch size.")]


# ---- argument defaults, checks and recovery wording -----------------------------------------------------------------


def period_unless_dates(args):
    if args.period is None and not (args.start or args.end):
        args.period = "1mo"


BAR_NAMES = {"1d": "daily", "5d": "five-day", "1wk": "weekly", "1mo": "monthly", "3mo": "quarterly"}
COARSER = {"1d": "1wk", "5d": "1wk", "1wk": "1mo", "1mo": "3mo"}


def coarser_bars(args):
    """The next interval up, for a window too long to read row by row; intraday bars step up to daily."""
    if getattr(args, "interval", None) is None:
        return None  # read has no interval: a coarser view is a new request the original command makes
    step = COARSER.get(args.interval) or (None if args.interval == "3mo" else "1d")
    if step is None:
        return None
    was = BAR_NAMES.get(args.interval, args.interval)
    return f"--interval {step}", f"{BAR_NAMES[step]} bars, not a slice of these {was} ones"


def search_check(args):
    if args.dataset != "quotes" and args.type != "all":
        raise InputError("--type only filters instrument quotes; use --dataset quotes")


def screen_check(args):
    if args.limit and args.limit > 250:
        raise InputError("Screen --limit cannot exceed Yahoo's 250-row cap")


def custom_sort(args):
    """A custom query sorts by ticker, descending, unless told otherwise; a preset's own sort is its dataset's to fill."""
    if not args.preset:
        args.sort = args.sort or "ticker"
        if args.ascending is None:
            args.ascending = False


def week_from_today(args):
    if not getattr(args, "symbol", None):
        args.start = args.start or date.today().isoformat()
        args.end = args.end or (date.fromisoformat(args.start) + timedelta(days=7)).isoformat()


def calendar_check(args):
    if args.limit and args.limit > 100:
        raise InputError("Calendar --limit cannot exceed Yahoo's 100-row cap")
    if getattr(args, "symbol", None):
        if args.start or args.end or args.most_active:
            raise InputError("Single-symbol earnings supports --limit/--offset, not date or most-active filters; omit SYMBOL for market dates")
    if getattr(args, "most_active", False) and args.offset:
        raise InputError("Native most-active filter is unavailable with --offset; remove --most-active")


# ---- the commands -------------------------------------------------------------------------------------------------

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


def symbol_command(group, name, purpose, narrow, **spec):
    return Command(group, name, purpose, f"{group}.{name}", args=[SYMBOLS], narrow=narrow, **spec)


def calendar_command(name, purpose, args=RANGE, **spec):
    return Command("calendar", name, purpose, f"calendar.{name}", args=args, defaults=week_from_today, check=calendar_check,
                   narrow=["--fields", "--limit", "--start/--end", "--offset"], **spec)


def statement_command(name, what):
    frequencies = ["yearly", "quarterly"] if name == "balance" else ["yearly", "quarterly", "trailing"]
    return Command("financials", name, what + " line items by fiscal period, as reported.", f"financials.{name}",
                   args=[SYMBOLS, Arg("--frequency", choices=frequencies, default="yearly", help=FREQUENCY_HELP), periods(1)],
                   narrow=["--fields", "--periods", "--frequency"])


COMMANDS = {command.path: command for command in [
    Command("search", "", "Find instrument candidates by name, symbol or keyword.", "search",
            args=[Arg("query", help="Company name, symbol fragment or keyword."),
                  Arg("--type", choices=SEARCH_TYPES, default="all", help="Instrument type filter; applies to --dataset quotes only."),
                  Arg("--dataset", choices=["quotes", "news", "lists", "research"], default="quotes", help="quotes: instrument candidates; news: articles; lists: Yahoo curated lists; research: research reports.")],
            narrow=["--limit", "--type", "--dataset"], check=search_check,
            forbidden=lambda args: ["--type"] if getattr(args, "dataset", "quotes") != "quotes" else []),

    Command("prices", "quote", "Current price, trading session and market-capitalisation fields for one instrument.", "prices.quote",
            args=[SYMBOLS, FROM], narrow=["--fields"], exportable=False),
    Command("prices", "history", "OHLCV bars, dividends and splits over a date range or relative period.", "prices.history",
            args=BAR_ARGS, end_exclusive=True, defaults=period_unless_dates, coarser=coarser_bars,
            narrow=["--fields", "--limit", "--period", "--start/--end", "--interval"]),
    Command("prices", "actions", "Dividends, splits and capital gains within a date range or relative period.", "prices.actions",
            args=BAR_ARGS, end_exclusive=True, defaults=period_unless_dates, narrow=["--limit", "--period", "--start/--end"]),

    Command("company", "profile", "Business description, sector, governance risk and headquarters for one company.", "company.profile",
            args=[SYMBOLS, FROM], narrow=["--fields"], exportable=False),
    Command("company", "shares", "Shares outstanding as Yahoo observed it over a date range.", "company.shares",
            args=[SYMBOLS, *dates("ISO date YYYY-MM-DD; default is about 18 months ago.", "ISO date YYYY-MM-DD; default is now.")],
            narrow=["--limit", "--start/--end"]),
    Command("company", "news", "Recent article and press-release entries referencing this company.", "company.news",
            args=[SYMBOLS, Arg("--tab", choices=["news", "all", "press releases"], default="news", help="Article source: news articles, press releases, or all.")],
            narrow=["--fields", "--limit", "--tab"]),
    symbol_command("company", "filings", "SEC filing entries with their Yahoo EDGAR links.", ["--fields", "--limit"]),

    statement_command("income", "Income statement"),
    statement_command("balance", "Balance sheet"),
    statement_command("cashflow", "Cash flow statement"),
    Command("financials", "valuation", "Valuation multiples and market-size measures by period.", "financials.valuation",
            args=[SYMBOLS, Arg("--frequency", choices=["yearly", "quarterly", "monthly", "trailing"], default="quarterly", help=FREQUENCY_HELP), periods(0)],
            narrow=["--fields", "--periods", "--frequency"]),

    symbol_command("analysts", "targets", "Current analyst price target range.", ["--fields"], exportable=False),
    symbol_command("analysts", "recommendations", "Analyst recommendation counts by month.", ["--fields", "--limit"]),
    symbol_command("analysts", "summary", "Analyst recommendation summary by month.", ["--fields", "--limit"]),
    symbol_command("analysts", "upgrades", "Rating upgrade and downgrade actions with their firms and dates.", ["--fields", "--limit"]),
    symbol_command("analysts", "earnings-estimate", "EPS estimates for the current and next quarter and year.", ["--fields"]),
    symbol_command("analysts", "revenue-estimate", "Revenue estimates for the current and next quarter and year.", ["--fields"]),
    symbol_command("analysts", "history", "Reported EPS against the estimate for past quarters.", ["--fields", "--limit"]),
    symbol_command("analysts", "revisions", "Counts of upward and downward EPS estimate revisions.", ["--fields"]),
    symbol_command("analysts", "trend", "How the consensus EPS estimate moved over the last 90 days.", ["--fields"]),
    symbol_command("analysts", "growth", "Expected growth for this instrument against its index.", ["--fields"]),

    symbol_command("holders", "major", "Insider and institutional ownership percentages for the whole company.", ["--limit"]),
    symbol_command("holders", "institutional", "Institutional holders with their reported share counts.", ["--fields", "--limit"]),
    symbol_command("holders", "fund", "Mutual fund holders with their reported share counts.", ["--fields", "--limit"]),
    symbol_command("holders", "insider-purchases", "Insider purchase and sale totals over the last six months.", ["--fields"]),
    symbol_command("holders", "insider-transactions", "Individual insider transactions with dates, roles and values.", ["--fields", "--limit"]),
    symbol_command("holders", "insider-roster", "Insiders and the shares they hold directly.", ["--fields", "--limit"]),

    symbol_command("fund", "overview", "Fund family, category and legal type.", ["--fields"], exportable=False),
    symbol_command("fund", "description", "The fund's own investment objective text.", (), exportable=False),
    symbol_command("fund", "holdings", "Largest reported holdings and their weights.", ["--fields", "--limit"]),
    symbol_command("fund", "asset-classes", "Allocation across cash, stock, bond, preferred and convertible.", ["--fields"], exportable=False),
    symbol_command("fund", "sector-weights", "Portfolio weight by sector.", ["--fields"], exportable=False),
    symbol_command("fund", "equity", "Valuation multiples and growth for the fund's equity holdings.", ["--fields"]),
    symbol_command("fund", "operations", "Expense ratio, turnover and reported net assets.", ["--fields"]),

    symbol_command("options", "expirations", "Expiration dates with listed contracts for this underlying.", ["--limit"]),
    Command("options", "chain", "Option contracts for one expiration, by side.", "options.chain",
            args=[SYMBOLS, Arg("--date", help="Expiration YYYY-MM-DD; omitted selects the nearest available expiry."),
                  Arg("--side", choices=["calls", "puts", "both"], default="both", help="Contract side to return; each side is limited separately.")],
            narrow=["--fields", "--limit", "--side", "--date"]),

    Command("screen", "presets", "Named screeners with the query each one actually runs.", "screen.presets",
            args=[TYPE], check=screen_check, narrow=["--filter", "--type"]),
    Command("screen", "fields", "Query fields available for the selected --type.", "screen.fields",
            args=[TYPE, FIELD], check=screen_check, narrow=["--filter", "--field", "--type"]),
    Command("screen", "values", "Enumerated values accepted by query fields of the selected --type.", "screen.values",
            args=[TYPE, FIELD], check=screen_check, narrow=["--filter", "--field", "--type"], exportable=False),
    Command("screen", "run", "Run a preset or a JSON query and return matching instruments.", "screen.run",
            args=[TYPE, OneOf(Arg("--query", help="JSON operator/operands object; see examples below."),
                              Arg("--preset", help="Preset name from screen presets. Its name does not state its condition: describe results by context.preset_query, the query it actually ran."), required=True),
                  Arg("--offset", type=int, default=0, help="Remote row offset for the next page; context.next_offset supplies it."),
                  Arg("--sort", help="Sort field from screen fields; custom query default ticker, preset uses its defined sort."),
                  Arg("--ascending", action=argparse.BooleanOptionalAction, default=None, help="Sort direction: --ascending or --no-ascending; omitted means the preset's own direction, or descending for a custom query.")],
            epilog=QUERY_HELP, check=screen_check, defaults=custom_sort,
            narrow=["--fields", "--limit", "--query", "--preset", "--offset"]),

    Command("market", "summary", "Benchmark index quotes for a market region.", "market.summary",
            args=[Arg("--region", choices=MARKET_REGIONS, default="US", help="Yahoo market region.")], narrow=["--fields", "--region"]),
    Command("market", "sectors", "Sector keys accepted by market sector.", "market.sectors", narrow=["--filter"]),
    Command("market", "sector", "One sector's overview, industries, top companies, funds or research.", "market.sector",
            args=domain_args(["industries", "top-etfs", "top-funds"]), narrow=["--fields", "--limit", "--dataset"]),
    Command("market", "industry", "One industry's overview, companies or research.", "market.industry",
            args=domain_args(["top-performing", "top-growth"]), narrow=["--fields", "--limit", "--dataset"]),

    calendar_command("earnings", "Earnings events, market-wide over a date range or one company's history.",
                     args=[*RANGE, Arg("symbol", nargs="?", help="Optional single symbol; omit for market-wide US earnings."),
                           Arg("--most-active", action="store_true", help="Opt into native most-active filter; only market earnings at offset 0.")],
                     forbidden=lambda args: ["--start/--end"] if getattr(args, "symbol", None) else []),
    calendar_command("economic", "Scheduled economic releases over a date range."),
    calendar_command("ipo", "IPO listings, filings and amendments over a date range."),
    calendar_command("splits", "Split events payable over a date range."),
]}


# ---- parsing, validation and dispatch -------------------------------------------------------------------------------


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class", argparse.RawTextHelpFormatter)
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise InputError(message)


def build_parser():
    parser = Parser(description="Query Yahoo Finance data by purpose. stdout: one JSON document; diagnostics: stderr. Discover with schema [GROUP [LEAF]].")
    add_common(parser, False, root=True)
    parser.add_argument("--ttl-days", type=int, default=GLOBAL_DEFAULTS["ttl_days"], help="Delete saved observations older than this many days. Retention only: an observation inside the window is not therefore current, and source_time is what says whether a value is fresh.")
    groups_parser = parser.add_subparsers(dest="group", required=True)

    scoped = groups_parser.add_parser("schema", help="Discover inputs and output contracts offline")
    scoped.add_argument("scope", nargs="*", help="GROUP or GROUP LEAF to describe; omit to list every group.")
    add_common(scoped, False)

    reader = groups_parser.add_parser("read", help="Read a saved observation in slices without a new request")
    reader.add_argument("id", help="Observation id from an earlier result.")
    reader.add_argument("--start", dest="row_start", type=int, default=0, help="Zero-based first row to return; each slice names the start of the next one.")
    add_common(reader)
    reader._option_string_actions["--limit"].help = "Maximum rows, counted forward from --start in saved order; unlike the first call, read does not keep the newest end. The same slice goes to --out."
    reader.add_argument("--out", help=OUT_HELP)
    reader.set_defaults(leaf="")

    members = {}
    for command in COMMANDS.values():
        members.setdefault(command.group, {})[command.name] = command
    parsers = {}
    for group, items in members.items():
        gp = groups_parser.add_parser(group, help=GROUPS[group])
        alone = list(items) == [""]  # a group whose only command is the group itself takes its arguments directly
        sub = None if alone else gp.add_subparsers(dest="leaf", required=True)
        for name, command in items.items():
            p = gp if alone else sub.add_parser(name, description=command.purpose, help=command.purpose)
            if alone:
                p.description = command.purpose
                p.set_defaults(leaf="")
            if command.epilog:
                p.epilog = command.epilog
            parsers[group, name] = p
            add_common(p)
            if command.exportable:
                p.add_argument("--out", help=OUT_HELP)
            for arg in command.args:
                arg.add(p)
    parsers["read"] = reader
    return parser, parsers


def validate(args, command):
    """What the arguments themselves must satisfy, before anything is looked up or paid for."""
    targets = []
    for dest in command.positionals():
        value = getattr(args, dest, None)
        targets.extend(value if isinstance(value, list) else [value] if value is not None else [])
    if any(not target.strip() for target in targets):
        raise InputError("Target symbols, search text and domain keys must not be empty")
    if args.timeout <= 0:
        raise InputError("--timeout must be positive")
    minimums = dict({"limit": 1}, **command.minimums())
    for name, minimum in minimums.items():
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
    if isinstance(start, str) and isinstance(end, str) and (start > end or (command.end_exclusive and start == end)):
        raise InputError("Invalid date range; a price --end is exclusive so it must be after --start, and a calendar --end is inclusive so it may equal --start")
    if hasattr(args, "period"):
        if args.period and (start or end):
            raise InputError("--period cannot be combined with --start or --end")
        if args.period and not re.fullmatch(r"([1-9][0-9]*(d|wk|mo|y)|ytd|max)", args.period):
            raise InputError("--period expects a positive range such as 5d, 1mo, 1y, ytd or max")
    if getattr(args, "out", None) and args.list_fields:
        raise InputError("--list-fields names columns and --out writes rows; use one of them.")


def chosen(request, given, parser):
    """The printed request: what the caller chose and what a default filled in, not every parser default echoed back.

    The saved observation keeps the whole request, since reproducing it needs every value.
    """
    defaults = {a.dest: GLOBAL_DEFAULTS.get(a.dest) if a.default == argparse.SUPPRESS else a.default for a in parser._actions}
    return {k: v for k, v in request.items() if k not in ("group", "leaf") and (v != given.get(k) or v != defaults.get(k, v))}


def main():
    args = None
    try:
        parser, parsers = build_parser()
        args = parser.parse_args()
        if args.max_chars < budget.MIN_CHARS:
            raise InputError(f"--max-chars must be >= {budget.MIN_CHARS} so recovery instructions remain readable")
        saved = querying.open_store(args)
        if args.group == "schema":
            return exit_code(*schema.run(args, parsers, parser, groups=GROUPS, commands=COMMANDS, defaults=GLOBAL_DEFAULTS,
                                         applies=SHARED, pointer=POINTER, exit_codes=EXIT_CODES))
        if args.group == "read":
            return exit_code(*querying.read(args, saved, COMMANDS))
        command = COMMANDS[args.group + (" " + args.leaf if args.leaf else "")]
        given = dict(vars(args))  # a copy: prepare fills defaults in, and chosen() tells them apart from what was typed
        validate(args, command)
        querying.prepare(command, args)
        if args.fields and any(not f for f in args.fields):
            raise InputError("--fields requires nonempty comma-separated field names")
        request = {k: v for k, v in vars(args).items() if k not in ("symbols", "store", "ttl_days", "max_chars", "list_fields")}
        return exit_code(*querying.answer(args, command, COMMANDS, saved, request, chosen(request, given, parsers[args.group, args.leaf])))
    except InputError as exc:
        fix = "Use --help for this command's arguments, or schema GROUP LEAF for its defaults, units and limits."
        results = [ordered(result("request", error=error_info("invalid", exc, fix)))]
        # 성진: 잘못된 --max-chars 자체가 입력 오류일 때 그 값으로 오류 문서를 재면 too_large가 invalid를 가린다 —
        # 무엇이 틀렸는지 말하는 문서는 틀린 예산의 적용 대상이 아니다.
        reporting = argparse.Namespace(max_chars=max(getattr(args, "max_chars", 0) or 0, GLOBAL_DEFAULTS["max_chars"]))
        return exit_code(*budget.emit(results, reporting, None, None))


if __name__ == "__main__":
    raise SystemExit(main())
