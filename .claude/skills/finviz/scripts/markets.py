"""Groups, market quotes and performance, the market map with its classification tree, and bubbles."""

import argparse
import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
import json5

import markup
from contract import Collection, Selector, condition, leaf
from transport import Failure

GROUP_VIEWS = {"overview": "110", "valuation": "120", "performance": "140", "financial": "160", "custom": "150"}
SECTORS = ["basicmaterials", "communicationservices", "consumercyclical", "consumerdefensive", "energy", "financial", "healthcare", "industrials", "realestate", "technology", "utilities"]
GROUP_IDS = ["sector", "industry", "country", "capitalization"] + ["industry/" + s for s in SECTORS]
GROUP_ARG = (("--group",), dict(dest="group_key", default="sector", choices=GROUP_IDS, help="Group universe: sector, industry, country, capitalization, or industry/<sector> for one sector's industries."))
GROUP_SORTS = {"name": "Name", "marketcap": "Market Capitalization", "pe": "Price/Earnings", "forwardpe": "Forward Price/Earnings", "peg": "PEG", "ps": "Price/Sales", "pb": "Price/Book", "pc": "Price/Cash", "pfcf": "Price/Free Cash Flow", "enterprisevalue": "Enterprise Value", "evebitda": "EV/EBITDA", "evsales": "EV/Sales", "dividendyield": "Dividend Yield", "eps3years": "EPS growth past 3 years", "eps5years": "EPS growth past 5 years", "estltgrowth": "EPS growth next 5 years", "sales3years": "Sales growth past 3 years", "sales5years": "Sales growth past 5 years", "shortinterestshare": "Short Interest Share", "roa": "Return on Assets", "roe": "Return on Equity", "roi": "Return on Invested Capital", "curratio": "Current Ratio", "quickratio": "Quick Ratio", "ltdebteq": "LT Debt/Equity", "debteq": "Total Debt/Equity", "grossmargin": "Gross Margin", "opermargin": "Operating Margin", "netmargin": "Net Profit Margin", "recom": "Analyst Recommendation", "perf1w": "Performance (Week)", "perf4w": "Performance (Month)", "perf13w": "Performance (Quarter)", "perf26w": "Performance (Half Year)", "perf52w": "Performance (Year)", "perfytd": "Performance (Year To Date)", "averagevolume": "Average Volume (3 Month)", "relativevolume": "Relative Volume", "change": "Change %", "volume": "Volume", "count": "Number of Stocks", "employees": "Employees"}


def sort_key(value, keys=GROUP_SORTS):
    if value.lstrip("-") not in keys:
        raise argparse.ArgumentTypeError("invalid sort key " + repr(value) + "; choose from " + ", ".join(keys) + ", with a leading - for descending")
    return value


def group_query(group):
    head, _, sub = group.partition("/")
    return {"g": head, "sg": sub or None}


def group_id(url):
    return markup.query_param(url, "g") + ("/" + markup.query_param(url, "sg") if markup.query_param(url, "sg") else "") if markup.query_param(url, "g") else None


@leaf("groups", "table", help="Group table for a view: overview, valuation, performance, financial or custom; rows keep source strings.", args=[GROUP_ARG, (("--view",), dict(default="overview", choices=list(GROUP_VIEWS), help="Table view.")), (("--sort",), dict(default=None, type=sort_key, metavar="KEY", help="Sort key: " + ", ".join(k + " (" + v + ")" for k, v in GROUP_SORTS.items()) + "; write --sort=-marketcap for descending."))], collections={"groups": Collection("rows keyed by the table headers plus filter, the screener filter value that selects the group's stocks")}, context={"sort_keys": "column label -> the key --sort accepts for it, from this page's header links"})
def table(ctx, args, target):
    query = dict(group_query(args.group_key), v=GROUP_VIEWS[args.view], o=args.sort)
    obs = ctx.observe("https://finviz.com/groups?" + urlencode({k: v for k, v in query.items() if v is not None}))
    page = markup.soup(obs)
    node = page.select_one("table.groups_table")
    if node is None:
        raise obs.fail("structure_changed", "No groups table was found.", "Read the saved raw page with read ID --raw.")
    rows = markup.table_records(node, obs.url)[1]
    trs = [tr for tr in node.select("tr") if tr.find_all("td", recursive=False)]
    for row, tr in zip(rows, trs):
        link = next((a for a in tr.select("a[href]") if "screener" in a["href"]), None)
        row["filter"] = markup.query_param(urljoin(obs.url, link["href"]), "f") if link else None
    controls = markup.selects(page)
    chosen = [group_id(o["value"]) for o in controls.get("groupSelect", []) if o["selected"]]
    conditions = {"group": condition(args.group_key, ("confirmed" if args.group_key in chosen else "not_applied") if chosen else "unverified", max(chosen, key=len) if chosen else None)}
    if args.sort:
        conditions["sort"] = markup.sort_condition(args.sort, page, controls)
    obs.result["target"], obs.result["conditions"] = args.group_key, conditions
    obs.result["context"], obs.result["collections"] = {"sort_keys": markup.sort_keys(node)}, {"groups": rows}
    return obs.result


@leaf("groups", "performance", help="Performance of every group over all standard periods from Finviz's groups API.", args=[GROUP_ARG], collections={"groups": Collection("{ticker, label, screenerUrl, perfT, perfW, perfM, perfQ, perfH, perfY, perfYtd} per group; percentages as published")})
def performance(ctx, args, target):
    obs = ctx.observe("https://finviz.com/api/groups_perf?" + urlencode({k: v for k, v in group_query(args.group_key).items() if v is not None}))
    records = obs.json()
    if not isinstance(records, list):
        raise obs.fail("structure_changed", "The groups API did not return a list.", "Read the saved raw response with read ID --raw.")
    first = records[0].get("screenerUrl") if records and isinstance(records[0], dict) else None
    obs.result["conditions"] = {"group": condition(args.group_key, "unverified", {"first_screener_url": first} if first else None)}
    obs.result["target"], obs.result["collections"] = args.group_key, {"groups": records}
    return obs.result


KIND = (("kind",), dict(metavar="KIND", choices=["futures", "forex", "crypto"], help="Market surface: futures, forex or crypto."))
SPARKLINE = ("sparkline", "sparklineDateChanges")


def keep_sparklines(records, keep, context):
    return records if keep else [{k: v for k, v in r.items() if k not in SPARKLINE} for r in records]


def keyed_records(mapping):
    """A mapping of instrument -> quote as records; the key is kept as ticker, or beside a ticker field that differs from it."""
    records = []
    for key, quote in mapping.items():
        record = dict(quote) if isinstance(quote, dict) else {"value": quote}
        if "ticker" not in record:
            record = dict({"ticker": key}, **record)
        elif record["ticker"] != key:
            record = dict({"key": key}, **record)
        records.append(record)
    return records


CURRENCY = (("--currency",), dict(default=None, choices=["USD", "USDT", "EUR", "BTC"], help="Crypto only: the quote currency; the source's USD pairs when omitted."))


@leaf("market", "quotes", help="Current quotes for every futures, forex or crypto instrument Finviz lists.", args=[KIND, (("--timeframe",), dict(default="d", choices=["d", "w"], help="Timeframe of the change fields: d daily or w weekly.")), CURRENCY], collections={"quotes": Collection("the quote as published with its instrument key as ticker, extra source fields included; the sparkline point arrays only with --sparkline", local=[Selector(("--sparkline",), dict(action="store_true", help="Keep each instrument's intraday sparkline points, most of the response's size."), keep_sparklines)])})
def quotes(ctx, args, target):
    if args.currency and args.kind != "crypto":
        raise Failure("invalid_argument", "--currency applies to crypto quotes only.", "Drop --currency, or use market quotes crypto.")
    query = {"timeframe": args.timeframe, "c": args.currency}
    obs = ctx.observe("https://finviz.com/api/" + args.kind + "_all?" + urlencode({k: v for k, v in query.items() if v is not None}))
    source = obs.json()
    if not isinstance(source, dict):
        raise obs.fail("structure_changed", "The quotes API did not return a mapping.", "Read the saved raw response with read ID --raw.")
    obs.result["conditions"] = {"timeframe": condition(args.timeframe, "unverified", None)} | ({"currency": condition(args.currency, "unverified", None)} if args.currency else {})
    obs.result["target"], obs.result["collections"] = args.kind, {"quotes": keyed_records(source)}
    return obs.result


@leaf("market", "performance", help="Performance of every futures, forex or crypto instrument over each period from five minutes to a year.", args=[KIND, CURRENCY], collections={"instruments": Collection("{ticker, label, group, last, perf5minPct, perfHourPct, perfDayPct, perfWeekPct, perfMonthPct, perfMtdPct, perfQuarterPct, perfHalfYearPct, perfYtdPct, perfYearPct} as published; forex and crypto add the same periods in pips")})
def market_performance(ctx, args, target):
    if args.currency and args.kind != "crypto":
        raise Failure("invalid_argument", "--currency applies to crypto performance only.", "Drop --currency, or use market performance crypto.")
    obs = ctx.observe("https://finviz.com/api/" + args.kind + "/performance" + ("?" + urlencode({"c": args.currency}) if args.currency else ""))
    source = obs.json()
    rows = source.get("rows") if isinstance(source, dict) else None
    if not isinstance(rows, list):
        raise obs.fail("structure_changed", "The performance API has no rows.", "Read the saved raw response with read ID --raw.")
    if args.currency:
        stated = source.get("currency")
        obs.result["conditions"] = {"currency": condition(args.currency, ("confirmed" if stated == args.currency else "not_applied") if stated else "unverified", stated)}
    obs.result["target"], obs.result["collections"] = args.kind, {"instruments": rows}
    return obs.result


TYPES = {"sec": "Sector", "geo": "World", "sec_all": "SectorFull", "cap": "MarketCap", "etf": "ETF", "crypto": "CryptoUSD", "crypto_usdt": "CryptoUSDT", "crypto_eur": "CryptoEUR", "crypto_btc": "CryptoBTC", "futures": "Futures", "sec_dji": "Dow", "sec_rut": "Russell", "sec_ndx": "Nasdaq", "sec_comp": "NasdaqComposite", "themes": "Themes"}


def classified(performance, tree):
    """Performance records, joined to the tree's group path, description and size weight where the tree lists the ticker."""
    found = {}

    def walk(node, path):
        for child in node.get("children") or []:
            if child.get("children"):
                walk(child, path + [child.get("name")])
            else:
                found[child.get("name")] = {"groups": path, "description": child.get("description"), "weight": child.get("value")}

    if tree:
        walk(tree, [])
    return [dict({"ticker": ticker, "performance": value}, **found.get(ticker, {})) for ticker, value in performance.items()]


@leaf("market", "map", help="Market map performance per ticker, optionally joined to the map's classification tree with its size weights.", args=[(("--type",), dict(default="sec", choices=list(TYPES), help="Map universe: sec S&P 500 sectors, sec_all the full market, geo world, cap, etf, crypto variants, futures, sec_dji, sec_rut, sec_ndx and sec_comp index maps, themes.")), (("--period",), dict(default="d1", help="Performance period: d1, w1, w4, w13, w26, w52, ytd.")), (("--classification",), dict(action="store_true", help="Join each ticker to the map's group path, description and size weight; resolving the tree takes several more asset requests."))], collections={"tickers": Collection("{ticker, performance} per map tile; with --classification also groups (the path of group names from the top), description and weight, the tile's size weight rather than a market cap")}, context={"period, version": "as published by the performance API", "classification_source": "URL of the asset the tree came from, with --classification"})
def market_map(ctx, args, target):
    obs = ctx.observe("https://finviz.com/api/map_perf?" + urlencode({"t": args.type, "st": args.period}))
    perf = obs.json()
    nodes = perf.get("nodes") if isinstance(perf, dict) else None
    if not isinstance(nodes, dict):
        raise obs.fail("structure_changed", "The map API has no nodes.", "Read the saved raw response with read ID --raw.")
    obs.result["target"] = args.type
    obs.result["conditions"] = {"type": condition(args.type), "period": condition(args.period, ("confirmed" if perf.get("subtype") == args.period else "not_applied") if perf.get("subtype") else "unverified", perf.get("subtype"))}
    obs.result["context"] = {"period": perf.get("subtype"), "version": perf.get("version")}
    obs.result["collections"] = {"tickers": classified(nodes, None)}
    if not args.classification:
        return obs.result
    dependencies = []
    try:
        tree, source = classification(ctx, args.type, dependencies)
        obs.result["collections"] = {"tickers": classified(nodes, tree)}
        obs.result["context"]["classification_source"] = source
    except Failure as exc:
        exc.record()
        obs.result["status"], obs.result["error"] = "partial", exc.info()
        obs.result["warnings"] = ["The classification tree could not be resolved; performance values are complete."]
    obs.result["source"]["dependencies"] = dependencies
    return obs.result


def classification(ctx, map_type, dependencies):
    """Resolve the map's classification literal from the current page's own loader and runtime manifest; nothing is guessed or cached."""

    def asset(url):
        found = ctx.observe(url)
        dependencies.append(found.id)
        found.result["context"] = {"bytes": len(found.raw)}
        return found, found.text

    page_obs, html = asset("https://finviz.com/map?" + urlencode({"t": map_type}))
    assets = list(dict.fromkeys(urljoin("https://finviz.com", s["src"]) for s in BeautifulSoup(html, "html.parser").select("script[src]")))
    entry = next((i for i, a in enumerate(assets) if "/map.v" in a), None)
    runtime = next((a for a in assets if "/runtime.v" in a), None)
    if entry is None or runtime is None:
        raise page_obs.fail("asset_structure", "The map page no longer references a map entry or runtime script.", "Drop --classification; the performance values are unaffected.")
    enum = TYPES[map_type]
    chunk = None
    # 성진: 진입 파일과 그 앞의 숫자 번들 최대 10개만 검사한다; Finviz가 로더를 이 범위 밖으로 옮기면 넓힌다.
    for url in [assets[entry], *reversed([a for a in assets[:entry] if re.search(r"/\d+\.v", a)][-10:])]:
        loader_obs, loader = asset(url)
        candidates = []
        # 성진: 현재 로더의 중첩 중괄호 없는 switch만 해석한다; 분기가 블록문으로 바뀌면 구조 오류로 멈추고 파서를 확장한다.
        for body in re.findall(r"switch\s*\([^{}]*\)\s*\{([^{}]*)\}", loader):
            if not all(re.search(r"case\s+[\w$.]+\." + name + r":\s*return", body) for name in ("World", "SectorFull")):
                continue
            selector = r"default" if enum == "Sector" else r"case\s+[\w$.]+\." + enum
            candidates.extend(re.findall(selector + r":\s*return[^;{}]{0,150}?\.e\((\d+)\)", body))
        if len(candidates) > 1:
            raise loader_obs.fail("asset_structure", "Multiple loader branches for " + enum + ".", "Drop --classification; ambiguous map loaders are not guessed.")
        if candidates:
            chunk = candidates[0]
            break
    if chunk is None:
        raise page_obs.fail("asset_structure", "The loader has no case for " + enum + ".", "Drop --classification; no other map universe was substituted.")
    runtime_obs, manifest = asset(runtime)
    digest = None
    for m in re.finditer(r'"\.v1\."\s*\+\s*(\{[^{}]+\})', manifest):
        mapping = json5.loads(re.sub(r"([,{])\s*(\d+)\s*:", r'\1"\2":', m.group(1)), allow_duplicate_keys=False)
        digest = mapping.get(chunk, digest)
    if not isinstance(digest, str) or not re.fullmatch(r"[\w-]+", digest):
        raise runtime_obs.fail("asset_structure", "The runtime manifest has no hash for chunk " + chunk + ".", "Drop --classification; read the saved manifest with read ID --raw.")
    chunk_obs, payload = asset(runtime.rsplit("/", 1)[0] + "/" + chunk + ".v1." + digest + ".js")
    roots = []
    for m in re.finditer(r"\.exports\s*=\s*(\{)", payload):
        value, error, _ = json5.parse(payload, start=m.start(1), consume_trailing=False, allow_duplicate_keys=False)
        if error is None and isinstance(value, dict) and value.get("name") == "Root" and isinstance(value.get("children"), list):
            roots.append(value)
    if len(roots) != 1:
        raise chunk_obs.fail("asset_structure", "Expected one Root classification object, found " + str(len(roots)) + ".", "Drop --classification; ambiguous assets are not guessed.")
    return roots[0], chunk_obs.url


AXES = ["PB", "PC", "PE", "PEG", "PFCF", "PS", "averageVolume", "beta", "curRatio", "debtEq", "dividendYield", "employees", "eps5Years", "epsQoQ", "epsYoY", "epsYoY1", "estLTGrowth", "forwardPE", "gap", "grossMargin", "high52w", "income", "insiderOwn", "insiderTrans", "instOwn", "instTrans", "lastChange", "low52w", "ltdebtEq", "marketCap", "netMargin", "operMargin", "payoutRatio", "perf13w", "perf1w", "perf26w", "perf4w", "perf52w", "perfYtd", "quickRatio", "relativeVolume", "roa", "roe", "roi", "rsi", "sales", "sales5Years", "salesQoQ", "sector", "shortInterestRatio", "shortInterestShare", "sma20", "sma200", "sma50", "targetPrice", "ticker", "volatility1w", "volatility4w"]
AXIS_HELP = " axis field; schema market bubbles lists the accepted ones under choices."


@leaf("market", "bubbles", help="Bubble chart data: one record per stock with the chosen x, y, size and color fields.", args=[(("--x",), dict(default="sector", choices=AXES, metavar="FIELD", help="X" + AXIS_HELP)), (("--y",), dict(default="lastChange", choices=AXES, metavar="FIELD", help="Y" + AXIS_HELP)), (("--size",), dict(default="marketCap", choices=AXES, metavar="FIELD", help="Size" + AXIS_HELP)), (("--color",), dict(default="sector", choices=AXES, metavar="FIELD", help="Colour" + AXIS_HELP)), (("--index",), dict(default="dji", choices=["any", "sp500", "ndx", "dji", "rut"], help="Stock universe: dji 30 names, ndx 100, sp500 500, rut 2000, any every listed stock."))], collections={"stocks": Collection("{ticker, company, x, y, size, color, isETF} as published; size is the field chosen with --size, not necessarily market cap")})
def bubbles(ctx, args, target):
    obs = ctx.observe("https://finviz.com/api/bubbles?" + urlencode({"x": args.x, "y": args.y, "size": args.size, "color": args.color, "idx": args.index}))
    records = obs.json()
    if not isinstance(records, list):
        raise obs.fail("structure_changed", "The bubbles API did not return a list.", "Read the saved raw response with read ID --raw.")
    obs.result["conditions"] = {key: condition(getattr(args, key)) for key in ("x", "y", "size", "color", "index")}
    obs.result["target"], obs.result["collections"] = args.index, {"stocks": records}
    return obs.result
