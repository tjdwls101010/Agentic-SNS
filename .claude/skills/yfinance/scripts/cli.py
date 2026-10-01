# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["yfinance[repair]==1.7.0", "pandas", "numpy"]
#
# [tool.uv]
# exclude-newer = "2026-09-13T13:10:00Z"
# ///
"""Purpose-oriented Yahoo Finance CLI. `--help` maps the commands; `<command> --help` documents one.

This file is the whole command surface: every argument and its help, the closed choices, the argument defaults and
checks, the recovery arguments each command names, the exit codes, and the documents --help prints. What Yahoo returns and what its values mean
live in yfinance_skill/yahoo, joined to a command here by its `dataset` key; yfinance_skill.describe hands those facts to the documents.
"""
import argparse
from datetime import date, timedelta
import json
import re

from yfinance_skill import budget, describe, querying
from yfinance_skill.envelope import ENVELOPE, STATUSES, InputError, LocalFailure, error_info, ordered, result

EXIT_CODES = {
    "ok": (0, "every target returned usable data"),
    "invalid": (2, "an argument, a saved id or an --out path was refused; the fix says what to change"),
    "local_io": (4, "the store or the --out file could not be read or written"),
    "rate_limited": (5, "Yahoo limited requests before any target returned data; the rest were not attempted"),
    "upstream": (6, "the source failed or timed out for every target"),
    "empty": (7, "the source answered with nothing usable, which does not prove the data does not exist"),
    "partial": (8, "part of what was asked is missing: rows cut to fit the budget, or some targets failed or came back empty"),
    "too_large": (9, "the result does not fit --max-chars; the fix names a narrowing or the saved id to read"),
}


def exit_code(status, codes):
    """A printed document's status as an exit code; a document with no usable result takes its most actionable error."""
    if status in ("ok", "partial", "empty", "too_large"):
        return EXIT_CODES[status][0]
    for code in ("rate_limited", "invalid", "local_io"):
        if code in codes:
            return EXIT_CODES[code][0]
    return EXIT_CODES["upstream"][0]


# ---- shared arguments and declaration tools -----------------------------------------------------------------------

GLOBAL_DEFAULTS = {"max_chars": 20000, "ttl_days": 14}
MAX_CHARS_HELP = "Largest JSON document to print. Each command's default window keeps a result to one screen; this is the boundary behind it, and a result over it comes back narrowed (partial) or refused (too_large) with a recovery."
TTL_HELP = "Delete saved observations older than this many days; 0 keeps every one. Retention only: source_time, not age, says whether a value is current."

OUT_HELP = ("Write every saved row to a new CSV file (an existing one is never overwritten) and print a summary instead: values and timestamps as saved, "
            "a target column, index levels as columns, option sides as side, mapping keys as key, a list of values as value, nested records as dotted columns, "
            "other objects as JSON, nulls blank, and a clashing name prefixed source. — read the summary's columns. The default window and projection do not apply; "
            "an explicit --fields or --limit does. Commands that send the source a count (news, screen, calendars, search) still ask for their default count, "
            "or an explicit --limit, and read no further pages. A target with no rows adds none, so check each target's status before comparing.")

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


def field_list(value):
    return [f.strip() for f in value.split(",")]


# The arguments every data command takes, each with where it applies; read takes all but --timeout. --filter defaults to None so that a given one, even "", can be told apart and refused where it narrows nothing.
SHARED = [
    (Arg("--fields", type=field_list, metavar="A,B", help="Comma-separated fields replacing the default projection; nested payloads take dotted paths such as content.title, and --list-fields names them."), "every data command and read"),
    (Arg("--list-fields", action="store_true", help="List the fields this result offers instead of its values; refused with --out."), "every data command and read"),
    (Arg("--filter", metavar="TEXT", help="Case-insensitive substring narrowing a catalog or a --list-fields listing."), "screen presets, fields and values, and --list-fields; refused elsewhere"),
    (Arg("--limit", type=int, metavar="N", help="Maximum rows, replacing the default window; each kind's 'a limit keeps' line says which end."), "every data command and read; screen run and calendars cap it at 250 and 100 when they ask the source"),
    (Arg("--timeout", type=int, default=30, metavar="SECONDS", help="Seconds per target, library calls included."), "every data command; not read, which makes no request"),
]
OUT = "data commands whose results are rows, and read; the kinds list marks the ones without it"


def add_common(parser, read=False):
    parser.add_argument("--max-chars", type=int, default=argparse.SUPPRESS, help=MAX_CHARS_HELP)
    for arg, _ in SHARED:
        if not (read and arg.dest == "timeout"):
            arg.add(parser)


def dates(help_start, help_end):
    return [Arg("--start", metavar="DATE", help=help_start), Arg("--end", metavar="DATE", help=help_end)]


class Command:
    """One command a caller can type. `dataset` names what it reads in yfinance_skill/yahoo.

    `defaults` fills the namespace (execution and the echoed request read it), `check` only reads it, and
    `forbidden` names the narrowings this call's own mode rejects so a recovery never recommends them. `narrow` is
    every argument a recovery may name. `rows` and `fields` are the default window, what one screen shows when --limit and --fields are omitted; for a command whose source is sent a count, `rows` is also that count. A `catalog` lists names rather than data, so --filter narrows it without --list-fields.
    """

    def __init__(self, group, name, purpose, dataset, *, args=(), defaults=None, check=None, narrow=(), forbidden=None,
                 rows=None, fields=(), end_exclusive=False, epilog=None, exportable=True, catalog=False):
        self.group, self.name, self.purpose, self.dataset = group, name, purpose, dataset
        self.args, self.defaults, self.check, self.narrow = tuple(args), defaults, check, tuple(narrow)
        self.forbidden, self.end_exclusive = forbidden, end_exclusive
        self.rows, self.fields = rows, tuple(fields)
        self.epilog, self.exportable, self.catalog = epilog, exportable, catalog

    @property
    def path(self):
        return self.group + (" " + self.name if self.name else "")

    def positionals(self):
        """The targets this command is asked about: its positional arguments, never an option that happens to share a name."""
        return [arg.dest for arg in self.args if isinstance(arg, Arg) and not arg.flags[0].startswith("-")]

    def minimums(self):
        return {arg.dest: arg.minimum for arg in self.args if isinstance(arg, Arg) and arg.minimum is not None}


# ---- argument bundles, closed choices and default projections -------------------------------------------------------

QUOTE_FIELDS = ("symbol", "shortName", "quoteType", "currency", "financialCurrency", "marketState", "exchange", "fullExchangeName", "exchangeTimezoneName",
                "regularMarketPrice", "regularMarketChange", "regularMarketChangePercent", "regularMarketTime", "regularMarketOpen", "regularMarketDayHigh",
                "regularMarketDayLow", "regularMarketPreviousClose", "regularMarketVolume", "bid", "ask", "bidSize", "askSize",
                "postMarketPrice", "postMarketChangePercent", "postMarketTime", "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "fiftyTwoWeekChangePercent",
                "fiftyDayAverage", "twoHundredDayAverage", "averageDailyVolume10Day", "averageDailyVolume3Month", "marketCap", "sharesOutstanding",
                "trailingPE", "forwardPE", "epsTrailingTwelveMonths", "dividendYield", "dividendRate", "exDividendDate", "beta")
PROFILE_FIELDS = ("symbol", "longName", "quoteType", "currency", "financialCurrency", "sector", "sectorKey", "industry", "industryKey",
                  "country", "state", "city", "address1", "zip", "phone", "website", "irWebsite", "fullTimeEmployees", "longBusinessSummary",
                  "auditRisk", "boardRisk", "compensationRisk", "shareHolderRightsRisk", "overallRisk", "governanceEpochDate",
                  "heldPercentInsiders", "heldPercentInstitutions", "lastFiscalYearEnd", "mostRecentQuarter", "lastSplitDate", "lastSplitFactor")
NEWS_FIELDS = ("content.title", "content.pubDate", "content.provider.displayName", "content.canonicalUrl.url", "content.summary")
FILING_FIELDS = ("date", "type", "title", "edgarUrl")
SCREEN_FIELDS = ("symbol", "shortName", "regularMarketPrice", "regularMarketChangePercent", "regularMarketVolume",
                 "marketCap", "trailingPE", "fiftyTwoWeekChangePercent", "averageAnalystRating", "fullExchangeName")

SYMBOLS = Arg("symbols", nargs="+", help="One or more Yahoo symbols; each is queried separately.")
FROM = Arg("--from", dest="from_id", metavar="ID", help="Select from this saved prices quote or company profile observation instead of making a new request.")

INTERVALS = ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"]
BAR_ARGS = [SYMBOLS, *dates("ISO date YYYY-MM-DD; inclusive.", "ISO date YYYY-MM-DD; exclusive: bars dated on or after it are not returned."),
            Arg("--period", metavar="RANGE", help="Relative range such as 5d, 1mo, 1y, ytd or max; refused with --start or --end, and 1mo when all three are absent."),
            Arg("--interval", choices=INTERVALS, default="1d", help="Bar size. Intraday intervals carry range limits the source enforces; history's limit lines below say what is known."),
            Arg("--adjust", choices=["none", "auto", "back"], default="auto", help="none: unadjusted OHLC as supplied plus Adj Close; auto: Open/High/Low/Close scaled for splits and dividends, Adj Close removed; back: Close kept raw while Open/High/Low are scaled by the adjustment ratio, Adj Close removed."),
            Arg("--repair", action="store_true", help="Opt into yfinance price repair; off by default, and refused with --interval 5d, which yfinance does not repair."),
            Arg("--prepost", action="store_true", help="Include pre/post-market data where available.")]

FREQUENCY_HELP = "trailing means TTM, a rolling twelve months rather than a completed fiscal period."
def periods(minimum, help):
    return Arg("--periods", type=int, default=5, minimum=minimum, metavar="N", help=help)


SEARCH_TYPES = ["all", "stock", "mutualfund", "etf", "index", "future", "currency", "cryptocurrency"]

TYPE = Arg("--type", choices=["equity", "fund", "etf"], default="equity", help="Query universe; fields, values and presets differ per type.")
# 성진: --field·--sort(equity만 93개, --type마다 다름)와 산업 키(약 145개)는 choices로 두면 --help를 덮는다. 발견 명령
# (screen fields, market sector KEY --dataset industries)과 오류의 fix가 그 목록을 맡는다. 작은 닫힌 집합만 choices다.
FIELD = Arg("--field", metavar="NAME", help="Exact query field, useful for allowed-value lookup.")
PRESETS = ["aggressive_small_caps", "day_gainers", "day_losers", "growth_technology_stocks", "most_actives", "most_shorted_stocks",
           "small_cap_gainers", "undervalued_growth_stocks", "undervalued_large_caps", "conservative_foreign_funds", "high_yield_bond",
           "portfolio_anchors", "solid_large_growth_funds", "solid_midcap_growth_funds", "top_mutual_funds", "top_etfs_us",
           "top_performing_etfs", "technology_etfs", "bond_etfs"]  # yf.PREDEFINED_SCREENER_QUERIES in yfinance 1.7.0
QUERY_HELP = '''JSON query: {"operator":OP,"operands":[...]}; field names come from screen fields, enumerated values from screen values.
EQ [field, string|finite number] (2 operands); IS-IN [field, value, ...] (2+ operands).
BTWN [field, number, number] (3 operands, inclusive lower/upper); GT, LT, GTE, LTE [field, finite number] (2 operands).
AND, OR [query, query, ...] (2+ nested query objects). Booleans, null, NaN and Infinity are not query values.
Nested example: {"operator":"AND","operands":[{"operator":"EQ","operands":["region","us"]},{"operator":"GT","operands":["intradaymarketcap",2000000000]}]}'''

MARKET_REGIONS = ["US", "GB", "ASIA", "EUROPE", "RATES", "COMMODITIES", "CURRENCIES", "CRYPTOCURRENCIES"]  # yf.MarketRegion in yfinance 1.7.0
# 성진: Sector·Industry의 region은 yf.MarketRegion(US/GB/ASIA/EUROPE/…)이 아니라 ISO 3166-1 alpha-2다 — 다른 이름공간이라
# MarketRegion을 choices로 쓰면 실제로 동작하는 KR·JP·DE가 거절된다. 아래 목록은 실측이다: 각 코드로 top-companies를
# 부르고 US와 같은 종목이 오면 조용한 대체로 판정했다. ZZ·XX·UK·EU와 NL·CH·IE·ZA 등은 전부 그 대체에 걸렸다.
DOMAIN_REGIONS = ["US", "AR", "AU", "BR", "CA", "CN", "DE", "DK", "ES", "FI", "FR", "GB", "GR", "HK", "IL", "IN", "IT", "JP", "KR", "MY", "NO", "PT", "QA", "RU", "SE", "SG", "TH", "TR", "TW"]


SECTOR_KEYS = ["basic-materials", "communication-services", "consumer-cyclical", "consumer-defensive", "energy", "financial-services",
               "healthcare", "industrials", "real-estate", "technology", "utilities"]  # the keys of yfinance.const.SECTOR_INDUSTY_MAPPING_LC in yfinance 1.7.0


def domain_args(key, datasets):
    # 성진: 닫힌 선택지가 G1을 인터페이스 층에서 없앤다 — 서비스되지 않는 코드는 경고 없이 미국 데이터를 돌려줬다.
    return [key,
            Arg("--region", choices=DOMAIN_REGIONS, default="US", help="Country code; only the codes Yahoo serves this dataset for are accepted."),
            Arg("--dataset", choices=["overview", "top-companies", "research-reports"] + datasets, default="overview", help="Part of the sector or industry to return.")]


RANGE = [*dates("ISO date YYYY-MM-DD; inclusive. Defaults to today for market-wide calendars.", "ISO date YYYY-MM-DD; inclusive, so --start D --end D returns that day. Defaults to seven days after --start."),
         Arg("--offset", type=int, default=0, metavar="N", help="Row offset for the next source page, a new request; context.next_offset supplies it. Rows the budget cut are read with the continuation instead.")]


# ---- argument defaults, checks and recovery wording -----------------------------------------------------------------


def bars_check(args):
    if args.repair and args.interval == "5d":
        raise InputError("yfinance refuses to repair five-day bars", fix="Drop --repair, or choose another --interval such as 1d or 1wk.")


def period_unless_dates(args):
    if args.period is None and not (args.start or args.end):
        args.period = "1mo"


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
    "search": "Find instruments, news, curated lists or research reports by name, symbol or keyword",
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
                   narrow=["--fields", "--limit", "--start/--end", "--offset"], rows=12, **spec)


def statement_command(name, what):
    frequencies = ["yearly", "quarterly"] if name == "balance" else ["yearly", "quarterly", "trailing"]
    return Command("financials", name, what + " line items by fiscal period, as reported.", f"financials.{name}",
                   args=[SYMBOLS, Arg("--frequency", choices=frequencies, default="yearly",
                                      help="yearly or quarterly periods; a balance sheet has no trailing (TTM) form." if name == "balance" else FREQUENCY_HELP),
                         periods(1, "Maximum fiscal periods, newest first, selected locally from what the source returned.")],
                   narrow=["--fields", "--periods", "--frequency"])


COMMANDS = {command.path: command for command in [
    Command("search", "", "Find instrument candidates by name, symbol or keyword.", "search",
            args=[Arg("query", help="Company name, symbol fragment or keyword."),
                  Arg("--type", choices=SEARCH_TYPES, default="all", help="Instrument type filter for --dataset quotes; any other dataset refuses a --type other than all."),
                  Arg("--dataset", choices=["quotes", "news", "lists", "research"], default="quotes", help="quotes: instrument candidates; news: articles; lists: Yahoo curated lists; research: research reports.")],
            narrow=["--limit", "--type", "--dataset"], check=search_check, rows=10,
            forbidden=lambda args: ["--type"] if getattr(args, "dataset", "quotes") != "quotes" else []),

    Command("prices", "quote", "Current price, trading session and market-capitalisation fields for one instrument.", "prices.quote",
            args=[SYMBOLS, FROM], narrow=["--fields"], fields=QUOTE_FIELDS, exportable=False),
    Command("prices", "history", "OHLCV bars, dividends and splits over a date range or relative period.", "prices.history",
            args=BAR_ARGS, end_exclusive=True, check=bars_check, defaults=period_unless_dates,
            narrow=["--fields", "--limit", "--period", "--start/--end", "--interval"]),
    Command("prices", "actions", "Dividends, splits and capital gains within a date range or relative period.", "prices.actions",
            args=BAR_ARGS, end_exclusive=True, check=bars_check, defaults=period_unless_dates, narrow=["--limit", "--period", "--start/--end"]),

    Command("company", "profile", "Business description, sector, governance risk and headquarters for one company.", "company.profile",
            args=[SYMBOLS, FROM], narrow=["--fields"], fields=PROFILE_FIELDS, exportable=False),
    Command("company", "shares", "Shares outstanding as Yahoo observed it over a date range.", "company.shares",
            args=[SYMBOLS, *dates("ISO date YYYY-MM-DD; default is about 18 months before --end.", "ISO date YYYY-MM-DD; default is now.")],
            narrow=["--limit", "--start/--end"]),
    Command("company", "news", "Recent article and press-release entries referencing this company.", "company.news",
            args=[SYMBOLS, Arg("--tab", choices=["news", "all", "press releases"], default="news", help="Article source: news articles, press releases, or all.")],
            narrow=["--fields", "--limit", "--tab"], rows=10, fields=NEWS_FIELDS),
    symbol_command("company", "filings", "SEC filing entries with their Yahoo EDGAR links.", ["--fields", "--limit"], rows=20, fields=FILING_FIELDS),

    statement_command("income", "Income statement"),
    statement_command("balance", "Balance sheet"),
    statement_command("cashflow", "Cash flow statement"),
    Command("financials", "valuation", "Valuation multiples and market-size measures by period.", "financials.valuation",
            args=[SYMBOLS, Arg("--frequency", choices=["yearly", "quarterly", "monthly", "trailing"], default="quarterly", help=FREQUENCY_HELP),
                  periods(0, "Maximum periods, sent upstream; 0 returns Current only.")],
            narrow=["--fields", "--periods", "--frequency"]),

    symbol_command("analysts", "targets", "Current analyst price target range.", ["--fields"], exportable=False),
    symbol_command("analysts", "recommendations", "Analyst recommendation counts by month.", ["--fields", "--limit"]),
    symbol_command("analysts", "upgrades", "Rating upgrade and downgrade actions with their firms and dates.", ["--fields", "--limit"], rows=20),
    symbol_command("analysts", "earnings-estimate", "EPS estimates for the current and next quarter and year.", ["--fields"]),
    symbol_command("analysts", "revenue-estimate", "Revenue estimates for the current and next quarter and year.", ["--fields"]),
    symbol_command("analysts", "history", "Reported EPS against the estimate for past quarters.", ["--fields", "--limit"]),
    symbol_command("analysts", "revisions", "Counts of upward and downward EPS estimate revisions.", ["--fields"]),
    symbol_command("analysts", "trend", "How the consensus EPS estimate moved over the last 90 days.", ["--fields"]),
    symbol_command("analysts", "growth", "Expected growth for this instrument against its index.", ["--fields"]),

    symbol_command("holders", "major", "Insider and institutional ownership percentages for the whole company.", ["--limit"]),
    symbol_command("holders", "institutional", "Institutional holders with their reported share counts.", ["--fields", "--limit"], rows=20),
    symbol_command("holders", "fund", "Mutual fund holders with their reported share counts.", ["--fields", "--limit"], rows=20),
    symbol_command("holders", "insider-purchases", "Insider purchase and sale totals over the last six months.", ["--fields"]),
    symbol_command("holders", "insider-transactions", "Individual insider transactions with dates, roles and values.", ["--fields", "--limit"], rows=20),
    symbol_command("holders", "insider-roster", "Insiders and the shares they hold directly.", ["--fields", "--limit"], rows=20),

    symbol_command("fund", "overview", "Fund family, category and legal type.", ["--fields"], exportable=False),
    symbol_command("fund", "description", "The fund's own investment objective text.", (), exportable=False),
    symbol_command("fund", "holdings", "Largest reported holdings and their weights.", ["--fields", "--limit"], rows=20),
    symbol_command("fund", "asset-classes", "Allocation across cash, stock, bond, preferred and convertible.", ["--fields"], exportable=False),
    symbol_command("fund", "sector-weights", "Portfolio weight by sector.", ["--fields"], exportable=False),
    symbol_command("fund", "equity", "Valuation multiples and growth for the fund's equity holdings.", ["--fields"]),
    symbol_command("fund", "operations", "Expense ratio, turnover and reported net assets.", ["--fields"]),

    symbol_command("options", "expirations", "Expiration dates with listed contracts for this underlying.", ["--limit"]),
    Command("options", "chain", "Option contracts for one expiration, by side.", "options.chain",
            args=[SYMBOLS, Arg("--date", metavar="DATE", help="Expiration YYYY-MM-DD; omitted selects the nearest available expiry."),
                  Arg("--side", choices=["calls", "puts", "both"], default="both", help="Contract side to return; --limit applies to each side.")],
            narrow=["--fields", "--limit", "--side", "--date"], rows=20),

    Command("screen", "presets", "Named screeners with the query each one actually runs.", "screen.presets",
            args=[TYPE], check=screen_check, narrow=["--filter", "--type"], catalog=True),
    Command("screen", "fields", "Query fields available for the selected --type.", "screen.fields",
            args=[TYPE, FIELD], check=screen_check, narrow=["--filter", "--field", "--type"], catalog=True),
    Command("screen", "values", "Enumerated values accepted by query fields of the selected --type.", "screen.values",
            args=[TYPE, FIELD], check=screen_check, narrow=["--filter", "--field", "--type"], exportable=False, catalog=True),
    Command("screen", "run", "Run a preset or a JSON query and return matching instruments.", "screen.run",
            args=[TYPE, OneOf(Arg("--query", metavar="JSON", help="JSON operator/operands object; the grammar is under [run] below."),
                              Arg("--preset", choices=PRESETS, help="Named screener; describe its results by context.preset_query, the query it ran, not by its name."), required=True),
                  Arg("--offset", type=int, default=0, metavar="N", help="Remote row offset for the next page; context.next_offset supplies it."),
                  Arg("--sort", metavar="FIELD", help="Sort field from screen fields; custom query default ticker, preset uses its defined sort."),
                  Arg("--ascending", action=argparse.BooleanOptionalAction, default=None, help="Sort direction; omitted means the preset's own direction, or descending for a custom query.")],
            epilog=QUERY_HELP, check=screen_check, defaults=custom_sort,
            narrow=["--fields", "--limit", "--query", "--preset", "--offset"], rows=25, fields=SCREEN_FIELDS),

    Command("market", "summary", "Benchmark index quotes for a market region.", "market.summary",
            args=[Arg("--region", choices=MARKET_REGIONS, default="US", help="Yahoo market region.")], narrow=["--fields", "--limit", "--region"]),
    Command("market", "sector", "One sector's overview, industries, top companies, funds or research.", "market.sector",
            args=domain_args(Arg("key", choices=SECTOR_KEYS, help="Sector key."), ["industries", "top-etfs", "top-funds"]),
            narrow=["--fields", "--limit", "--dataset"], rows=20),
    Command("market", "industry", "One industry's overview, companies or research.", "market.industry",
            args=domain_args(Arg("key", help="Industry key from market sector KEY --dataset industries."), ["top-performing", "top-growth"]),
            narrow=["--fields", "--limit", "--dataset"], rows=20),

    calendar_command("earnings", "Earnings events, market-wide over a date range or one company's history.",
                     args=[*RANGE, Arg("symbol", nargs="?", help="Optional single symbol: that company's earnings history and upcoming dates, paged by --limit and --offset, and refused with --start, --end or --most-active; omit for market-wide US earnings."),
                           Arg("--most-active", action="store_true", help="Opt into Yahoo's most-active filter; market-wide earnings at --offset 0 only.")],
                     forbidden=lambda args: ["--start/--end"] if getattr(args, "symbol", None) else []),
    calendar_command("economic", "Scheduled economic releases over a date range."),
    calendar_command("ipo", "IPO listings, filings and amendments over a date range."),
    calendar_command("splits", "Split events payable over a date range."),
]}


# ---- the documents --help prints ------------------------------------------------------------------------------------
# The root map, then one document per group that `<group> --help` and every `<group> <kind> --help` print alike: usage and kinds, the arguments with the kinds they apply to, the shared arguments, the output, the exit codes, and last what each kind's values mean. Arguments and choices come from the declarations above; what values mean comes from yfinance_skill.describe.

PROG = "cli.py"
LEAD = f"usage: {PROG} [--max-chars N] [--ttl-days N]"
READ_PURPOSE = "Read a saved observation again, in slices, by fields or to a file, without a new request."
READ_ARGS = [Arg("id", metavar="ID", help="Observation id from an earlier result."),
             Arg("--start", dest="row_start", type=int, default=0, metavar="N", help="Zero-based first row to return; each slice names the start of the next one.")]
READ_LIMIT = "Maximum rows, counted forward from --start in saved order; unlike the first call, read does not keep the newest end. The same slice goes to --out."
DOCUMENT = ["stdout is one JSON document {status, request, results}: status is the results' own when they share one, partial when they differ, and error when none is usable; request echoes what you chose and what a default filled in; results holds one envelope per target in the order given.",
            "If an --out file was written but its summaries do not fit --max-chars, a receipt replaces results: {out, rows (the file's total), and each target's status and rows, or in_file and missing (targets without rows, by status)}."]


def members(group):
    return [command for command in COMMANDS.values() if command.group == group]


def shape(command):
    """How a command's targets are typed: SYMBOL..., QUERY, KEY or [SYMBOL]."""
    parts = []
    for arg in command.args:
        if isinstance(arg, Arg) and not arg.flags[0].startswith("-"):
            name, nargs = arg.dest.upper(), arg.kwargs.get("nargs")
            parts.append(f"{name.removesuffix('S')}..." if nargs == "+" else f"[{name}]" if nargs == "?" else name)
    return " ".join(parts)


def usage(group):
    kinds = members(group)
    if kinds[0].name == "":
        return f"{group} {shape(kinds[0])}"
    shapes = {shape(command) for command in kinds}
    if len(shapes) == 1:
        return f"{group} {{{','.join(command.name for command in kinds)}}} {shapes.pop()}".rstrip()
    return f"{group} {{{' | '.join((command.name + ' ' + shape(command)).strip() for command in kinds)}}}"


def spec(arg, help=None):
    """One argument as a line: how it is typed, its help, its choices and its default."""
    kwargs = arg.kwargs
    if not arg.flags[0].startswith("-"):
        typed = arg.kwargs.get("metavar") or shape(Command("", "", "", "", args=[arg]))
    elif kwargs.get("action") == argparse.BooleanOptionalAction:
        typed = f"{arg.flags[0]}, --no-{arg.flags[0][2:]}"
    elif kwargs.get("action") == "store_true":
        typed = arg.flags[0]
    else:
        typed = f"{arg.flags[0]} " + ("{" + ",".join(kwargs["choices"]) + "}" if kwargs.get("choices") else (kwargs.get("metavar") or arg.dest.upper()))
    if not arg.flags[0].startswith("-") and kwargs.get("choices"):
        typed += " {" + ",".join(kwargs["choices"]) + "}"
    default = kwargs.get("default")
    shown = f" (default {default})" if default is not None and default is not False and kwargs.get("action") != "store_true" else ""
    return typed, (help or kwargs.get("help", "")) + shown


def exit_lines():
    lead = ("  The exit code is the document's: its status ok, empty, partial or too_large as such; when no result is usable, the most actionable error among them,"
            " rate_limited before invalid before local_io, else upstream.")
    return [lead] + [f"  {number}  {name}: {meaning}" for name, (number, meaning) in EXIT_CODES.items()]


def argument_lines(kinds):
    """Each argument of these kinds once, tagged with the kinds that take it when not all of them do."""
    entries, required = {}, []
    for command in kinds:
        for arg in command.args:
            for one in (arg.args if isinstance(arg, OneOf) else [arg]):
                key = (one.flags, repr(sorted(one.kwargs.items(), key=lambda item: item[0])))
                entries.setdefault(key, (one, []))[1].append(command.name)
            if isinstance(arg, OneOf) and arg.required:
                required.append((" or ".join(one.flags[0] for one in arg.args), command.name))
    lines = []
    for arg, names in entries.values():
        typed, text = spec(arg)
        tag = "" if len(names) == len(kinds) else f"[{', '.join(names)}] "
        minimum = f" (at least {arg.minimum})" if arg.minimum is not None else ""
        lines.append(f"  {typed}  {tag}{text}{minimum}")
    for flags, name in required:
        lines.append(f"  exactly one of {flags} is required" + (f" [{name}]" if len(kinds) > 1 else ""))
    return lines


def shared_lines(read=False):
    lines = []
    for arg, applies in SHARED:
        if read and arg.dest == "timeout":
            continue
        typed, text = spec(arg, READ_LIMIT if read and arg.dest == "limit" else None)
        lines.append(f"  {typed}  {text} [{applies}]")
    lines.append(f"  --out FILE  {OUT_HELP} [{OUT}]")
    lines.append(f"  --max-chars N  {MAX_CHARS_HELP} (default {GLOBAL_DEFAULTS['max_chars']}) (at least {budget.MIN_CHARS}) [before COMMAND or after the whole command]")
    lines.append(f"  --ttl-days N  {TTL_HELP} (default {GLOBAL_DEFAULTS['ttl_days']}) [before COMMAND only]")
    return lines


def output_lines():
    return ([f"  {line}" for line in DOCUMENT] + ["  envelope keys, in this order:"]
            + [f"    {key}: {text}" for key, text in ENVELOPE.items()] + ["  statuses:"]
            + [f"    {status}: {text}" for status, text in STATUSES.items()])


def kind_lines(command, seen):
    """What one kind returns: its default window, which end a limit keeps, how a recovery narrows it, its units, and what its values mean.

    `seen` maps each fact line already printed in this document to the kind it was printed under; a repeated one is named once as `same as [kind]: label, …`.
    """
    facts = describe.describe(command)
    name = command.name or command.group
    lines = [f"[{name}]"]
    if command.rows:
        lines.append(f"  default rows: {command.rows}")
    if command.fields:
        lines.append(f"  default fields: {', '.join(command.fields)}")
    lines.append(f"  a limit keeps {facts['limit_keeps']}" if command.exportable else "  --limit does not apply: the result is a single record")
    if command.narrow:
        lines.append(f"  narrow with: {', '.join(command.narrow)}")
    meaning = [("units", json.dumps(facts["units"], ensure_ascii=False, separators=(",", ":")))] if facts.get("units") else []
    meaning += list(facts.get("interpretation", {}).items())
    meaning += [("limit", text) for text in facts.get("limits", {}).values()] + [("gotcha", text) for text in facts.get("gotchas", [])]
    repeated = {}
    for label, text in meaning:
        if (label, text) in seen:
            repeated.setdefault(seen[label, text], []).append(label)
        else:
            seen[label, text] = name
            lines.append(f"  {label}: {text}")
    lines += [f"  same as [{earlier}]: {', '.join(labels)}" for earlier, labels in repeated.items()]
    if command.epilog:
        lines += ["  query:"] + [f"    {line}" for line in command.epilog.splitlines()]
    return lines


def group_document(group):
    kinds = members(group)
    lines = [f"{LEAD} {usage(group)} [options]", GROUPS[group] + "."]
    if kinds[0].name:
        width = max(len(command.name) for command in kinds) + 2
        lines += ["", "kinds:"] + [f"  {command.name:<{width}}{command.purpose}" + ("" if command.exportable else " (no --out)") for command in kinds]
    lines += ["", "arguments:"] + argument_lines(kinds)
    lines += ["", "shared arguments:"] + shared_lines()
    lines += ["", "output:"] + output_lines()
    lines += ["", "exit codes:"] + exit_lines()
    seen = {}
    lines += ["", "what each kind returns:"] + [line for command in kinds for line in kind_lines(command, seen)]
    return "\n".join(lines)


def read_document():
    lines = [f"{LEAD} read ID [--start N] [options]", READ_PURPOSE, "", "arguments:"]
    lines += [f"  {typed}  {text}" for typed, text in (spec(arg) for arg in READ_ARGS)] + shared_lines(read=True)
    lines += ["", "output:", "  The same document and envelope as the command that saved the observation, except that request is {read: ID} and each envelope adds stored_age_seconds; continuation names the next slice, forward from --start in saved order."]
    lines += output_lines()
    lines += ["", "read cannot reach an id saved in another store (the skill's data/observations, or $YF_STORE when it is set) or one --ttl-days deleted — rerun the original command — nor one saved by a command this version no longer has: choose a command from --help instead."]
    lines += ["", "exit codes:"] + exit_lines()
    return "\n".join(lines)


def root_map():
    commands = [(usage(group), GROUPS[group]) for group in GROUPS] + [("read ID", READ_PURPOSE)]
    width = min(max(len(typed) for typed, _ in commands), 48) + 2
    lines = [f"{LEAD} COMMAND ...", "Yahoo Finance data by purpose. stdout: one JSON document; stderr: diagnostics.",
             "`COMMAND --help` states that command's kinds, arguments, output, what each kind's values mean, and exit codes.", "", "commands:"]
    lines += [f"  {typed:<{width}}{purpose}" if len(typed) < width else f"  {typed}  {purpose}" for typed, purpose in commands]
    lines += ["", "options:", f"  --max-chars N  {MAX_CHARS_HELP} (default {GLOBAL_DEFAULTS['max_chars']}) (at least {budget.MIN_CHARS}) [before COMMAND or after the whole command]",
              f"  --ttl-days N  {TTL_HELP} (default {GLOBAL_DEFAULTS['ttl_days']}) [before COMMAND only]", "", "exit codes:"] + exit_lines()
    return "\n".join(lines)


class Document(argparse.Action):
    """-h/--help: print a document and exit, before any other argument is checked or anything is opened."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, render=None, help=None):
        super().__init__(option_strings, dest, default=default, nargs=0, help=help)
        self.render = render

    def __call__(self, parser, namespace, values, option_string=None):
        print(self.render())
        parser.exit()


# ---- parsing, validation and dispatch -------------------------------------------------------------------------------


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, render=None, **kwargs):
        kwargs.setdefault("add_help", False)
        kwargs.setdefault("allow_abbrev", False)  # --field is screen's query field, never a shortened --fields
        super().__init__(*args, **kwargs)
        if render:
            self.add_argument("-h", "--help", action=Document, render=render, help="Show this command's document and exit.")

    def error(self, message):
        raise InputError(message)


def build_parser():
    parser = Parser(render=root_map)
    parser.add_argument("--max-chars", type=int, default=GLOBAL_DEFAULTS["max_chars"], help=MAX_CHARS_HELP)
    parser.add_argument("--ttl-days", type=int, default=GLOBAL_DEFAULTS["ttl_days"], help=TTL_HELP)
    groups_parser = parser.add_subparsers(dest="group", required=True, parser_class=Parser)

    reader = groups_parser.add_parser("read", render=read_document)
    for arg in READ_ARGS:
        arg.add(reader)
    add_common(reader, read=True)
    reader._option_string_actions["--limit"].help = READ_LIMIT
    reader.add_argument("--out", help=OUT_HELP)
    reader.set_defaults(leaf="")

    parsers = {}
    for group in GROUPS:
        document = lambda group=group: group_document(group)  # noqa: E731 — one renderer per group, bound now
        gp = groups_parser.add_parser(group, render=document)
        kinds = members(group)
        alone = kinds[0].name == ""  # a group whose only command is the group itself takes its arguments directly
        sub = None if alone else gp.add_subparsers(dest="leaf", required=True, parser_class=Parser)
        for command in kinds:
            p = gp if alone else sub.add_parser(command.name, render=document)
            if alone:
                p.set_defaults(leaf="")
            parsers[group, command.name] = p
            add_common(p)
            if command.exportable:
                p.add_argument("--out", help=OUT_HELP)
            for arg in command.args:
                arg.add(p)
    parsers["read"] = reader
    return parser, parsers


def validate(args, command=None):
    """What the arguments themselves must satisfy, before anything is looked up or paid for. read has no command."""
    targets = []
    for dest in command.positionals() if command else []:
        value = getattr(args, dest, None)
        targets.extend(value if isinstance(value, list) else [value] if value is not None else [])
    if any(not target.strip() for target in targets):
        raise InputError("Target symbols, search text and domain keys must not be empty")
    if getattr(args, "timeout", 1) <= 0:  # read makes no request and takes no --timeout
        raise InputError("--timeout must be positive")
    if args.filter is not None and not (args.list_fields or (command and command.catalog)):
        raise InputError("--filter narrows a catalog (screen presets, fields, values) or a --list-fields listing, and this call is neither; drop it or add --list-fields.")
    minimums = dict({"limit": 1}, **(command.minimums() if command else {}))
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
    date_range(args, command)
    start, end = getattr(args, "start", None), getattr(args, "end", None)
    if hasattr(args, "period"):
        if args.period and (start or end):
            raise InputError("--period cannot be combined with --start or --end")
        if args.period and not re.fullmatch(r"([1-9][0-9]*(d|wk|mo|y)|ytd|max)", args.period):
            raise InputError("--period expects a positive range such as 5d, 1mo, 1y, ytd or max")
    if getattr(args, "out", None) and args.list_fields:
        raise InputError("--list-fields names columns and --out writes rows; use one of them.")


def date_range(args, command=None):
    start, end = getattr(args, "start", None), getattr(args, "end", None)
    if isinstance(start, str) and isinstance(end, str) and (start > end or (command and command.end_exclusive and start == end)):
        raise InputError("Invalid date range; a price --end is exclusive so it must be after --start, and a calendar --end is inclusive so it may equal --start")


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
        if args.ttl_days < 0:
            raise InputError("--ttl-days must be >= 0; 0 keeps every saved observation")
        # 성진: 인자 검증은 저장소를 열기(생성·보존기간 정리) 전에 끝난다 — 거절될 호출이 관측을 지우거나 디렉터리를 만들면 안 된다.
        if args.group == "read":
            validate(args)
            return exit_code(*querying.read(args, querying.open_store(args), COMMANDS))
        command = COMMANDS[args.group + (" " + args.leaf if args.leaf else "")]
        given = dict(vars(args))  # a copy: prepare fills defaults in, and chosen() tells them apart from what was typed
        validate(args, command)
        querying.prepare(command, args)
        date_range(args, command)  # a default can complete a range the caller gave one end of
        if args.fields and any(not f for f in args.fields):
            raise InputError("--fields requires nonempty comma-separated field names")
        saved = querying.open_store(args)
        request = {k: v for k, v in vars(args).items() if k not in ("symbols", "ttl_days", "max_chars", "list_fields") and not (k == "filter" and v is None)}
        return exit_code(*querying.answer(args, command, COMMANDS, saved, request, chosen(request, given, parsers[args.group, args.leaf])))
    except InputError as exc:
        fix = exc.fix or "Correct the argument; COMMAND --help states each command's arguments, choices and defaults."
        results = [ordered(result("request", error=error_info("invalid", exc, fix)))]
        # 성진: 잘못된 --max-chars 자체가 입력 오류일 때 그 값으로 오류 문서를 재면 too_large가 invalid를 가린다 —
        # 무엇이 틀렸는지 말하는 문서는 틀린 예산의 적용 대상이 아니다.
        reporting = argparse.Namespace(max_chars=max(getattr(args, "max_chars", 0) or 0, GLOBAL_DEFAULTS["max_chars"]))
        return exit_code(*budget.emit(results, reporting, None, None))
    except LocalFailure as exc:
        results = [ordered(result("request", error=error_info("local_io", exc, querying.LOCAL_FIX)))]
        return exit_code(*budget.emit(results, args, None, None))


if __name__ == "__main__":
    raise SystemExit(main())
