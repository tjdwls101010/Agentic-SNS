"""Groups, market quotes and performance, the market map with its classification tree, and bubbles."""

import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
import json5

import markup
from finviz import condition, leaf
from transport import Failure

GROUP_VIEWS = {"overview": "110", "valuation": "120", "performance": "140", "financial": "160", "custom": "150"}
GROUP_ARG = (("--group",), dict(dest="group_key", default="sector", help="Group identifier from groups options: sector, industry, industry/<sector>, country, capitalization."))


def group_query(group):
    head, _, sub = group.partition("/")
    return {"g": head, "sg": sub or None}


def group_id(url):
    return markup.query_param(url, "g") + ("/" + markup.query_param(url, "sg") if markup.query_param(url, "sg") else "") if markup.query_param(url, "g") else None


@leaf("groups", "options", help="List the group identifiers and sort keys the groups pages accept.", output={"groups": "[{group, label}]; pass group to --group", "sorts": "[{key, label}]; pass key to --sort, prefix - for descending"})
def options(ctx, args, target):
    obs = ctx.observe("https://finviz.com/groups")
    controls = markup.selects(markup.soup(obs))
    if "groupSelect" not in controls:
        raise obs.fail("structure_changed", "The groups page has no group control.", "Read the saved raw page with read ID --raw.")
    obs.result["target"] = "groups"
    obs.result["data"] = {"groups": [{"group": group_id(o["value"]), "label": o["label"]} for o in controls["groupSelect"]], "sorts": [{"key": markup.query_param(o["value"], "o"), "label": o["label"]} for o in controls.get("orderSelect", []) if markup.query_param(o["value"], "o")]}
    return obs.result


@leaf("groups", "table", help="Group table for a view: overview, valuation, performance, financial or custom; rows keep source strings.", args=[GROUP_ARG, (("--view",), dict(default="overview", choices=list(GROUP_VIEWS), help="Table view.")), (("--sort",), dict(default=None, help="Sort key from groups options; write --sort=-marketcap for descending."))], output={"[]": "rows keyed by the table headers plus filter, the screener filter value that selects the group's stocks", "conditions": "group and sort as confirmed by the page controls"}, narrow=["--fields", "--filter", "--limit"])
def table(ctx, args, target):
    query = dict(group_query(args.group_key), v=GROUP_VIEWS[args.view], o=args.sort)
    obs = ctx.observe("https://finviz.com/groups?" + urlencode({k: v for k, v in query.items() if v is not None}))
    page = markup.soup(obs)
    node = page.select_one("table.groups_table")
    if node is None:
        raise obs.fail("structure_changed", "No groups table was found.", "Read the saved raw page with read ID --raw.")
    headers, rows = markup.table_records(node, obs.url)
    trs = [tr for tr in node.select("tr") if tr.find_all("td", recursive=False)]
    for row, tr in zip(rows, trs):
        link = next((a for a in tr.select("a[href]") if "screener" in a["href"]), None)
        row["filter"] = markup.query_param(urljoin(obs.url, link["href"]), "f") if link else None
    controls = markup.selects(page)
    chosen = [group_id(o["value"]) for o in controls.get("groupSelect", []) if o["selected"]]
    conditions = {"group": condition(args.group_key, ("confirmed" if args.group_key in chosen else "not_applied") if chosen else "unverified", max(chosen, key=len) if chosen else None)}
    if args.sort:
        conditions["sort"] = markup.sort_condition(args.sort, page, controls)
    obs.result["target"], obs.result["conditions"], obs.result["data"] = args.group_key, conditions, rows
    return obs.result


@leaf("groups", "performance", help="Performance of every group over all standard periods from Finviz's groups API.", args=[GROUP_ARG], output={"[]": "{ticker, label, screenerUrl, perfT, perfW, perfM, perfQ, perfH, perfY, perfYtd} per group; percentages as published"}, narrow=["--filter", "--fields", "--limit"])
def performance(ctx, args, target):
    obs = ctx.observe("https://finviz.com/api/groups_perf?" + urlencode({k: v for k, v in group_query(args.group_key).items() if v is not None}))
    records = obs.json()
    first = records[0].get("screenerUrl") if isinstance(records, list) and records and isinstance(records[0], dict) else None
    obs.result["conditions"] = {"group": condition(args.group_key, "unverified", {"first_screener_url": first} if first else None)}
    obs.result["target"], obs.result["data"] = args.group_key, records
    return obs.result


KIND = (("kind",), dict(choices=["futures", "forex", "crypto"], help="Market surface."))


@leaf("market", "quotes", help="Current quotes for every futures, forex or crypto instrument Finviz lists.", args=[KIND, (("--timeframe",), dict(default="d", help="Source timeframe for the change fields, e.g. d, w, m."))], output={"{}": "ticker -> quote as published, including extra source fields; --fields selects ticker keys, --filter matches keys or quote values, --limit counts instruments"}, keyed=True, narrow=["--filter", "--fields", "--limit"])
def quotes(ctx, args, target):
    obs = ctx.observe("https://finviz.com/api/" + args.kind + "_all?" + urlencode({"timeframe": args.timeframe}))
    source = obs.json()
    obs.result["conditions"] = {"timeframe": condition(args.timeframe, "unverified", None)}
    obs.result["target"], obs.result["data"] = args.kind, source
    return obs.result


@leaf("market", "performance", help="Period performance per instrument for futures, forex or crypto.", args=[KIND], output={"{}": "instrument -> performance value as published"}, narrow=["--fields"])
def market_performance(ctx, args, target):
    obs = ctx.observe("https://finviz.com/api/" + args.kind + "_perf")
    obs.result["target"], obs.result["data"] = args.kind, obs.json()
    return obs.result


TYPES = {"sec": "Sector", "geo": "World", "sec_all": "SectorFull", "cap": "MarketCap", "etf": "ETF", "crypto": "CryptoUSD", "crypto_usdt": "CryptoUSDT", "crypto_eur": "CryptoEUR", "crypto_btc": "CryptoBTC", "futures": "Futures", "sec_dji": "Dow", "sec_rut": "Russell", "sec_ndx": "Nasdaq", "sec_ixic": "NasdaqComposite", "themes": "Themes"}


@leaf("market", "map", help="Market map performance per ticker plus the map's classification tree with its size weights.", args=[(("--type",), dict(default="sec", choices=list(TYPES), help="Map universe: sec S&P 500 sectors, sec_all full market, geo world, cap, etf, crypto, futures, index maps, themes.")), (("--period",), dict(default="d1", help="Performance period: d1, w1, w4, w13, w26, w52, ytd.")), (("--performance-only",), dict(action="store_true", help="Skip the classification tree and its asset requests."))], output={"period, version": "as published by the performance API", "performance": "ticker -> performance value", "classification": "nested {name, children} down to {name, description, value}; value is the map's size weight, not the current market cap", "classification_source": "URL of the asset the tree came from"}, narrow=["--performance-only", "--fields"])
def market_map(ctx, args, target):
    obs = ctx.observe("https://finviz.com/api/map_perf?" + urlencode({"t": args.type, "st": args.period}))
    perf = obs.json()
    obs.result["target"] = args.type
    obs.result["conditions"] = {"type": condition(args.type), "period": condition(args.period, ("confirmed" if perf.get("subtype") == args.period else "not_applied") if perf.get("subtype") else "unverified", perf.get("subtype"))}
    obs.result["data"] = {"period": perf.get("subtype"), "version": perf.get("version"), "performance": perf.get("nodes"), "classification": None, "classification_source": None}
    if args.performance_only:
        return obs.result
    dependencies = []
    try:
        tree, source = classification(ctx, args.type, dependencies)
        obs.result["data"].update(classification=tree, classification_source=source)
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
        found.result["data"] = {"bytes": len(found.raw)}
        return found, found.text

    page_obs, html = asset("https://finviz.com/map?" + urlencode({"t": map_type}))
    assets = list(dict.fromkeys(urljoin("https://finviz.com", s["src"]) for s in BeautifulSoup(html, "html.parser").select("script[src]")))
    entry = next((i for i, a in enumerate(assets) if "/map.v" in a), None)
    runtime = next((a for a in assets if "/runtime.v" in a), None)
    if entry is None or runtime is None:
        raise page_obs.fail("asset_structure", "The map page no longer references a map entry or runtime script.", "Use --performance-only; the classification tree is unavailable until the loader is understood again.")
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
            raise loader_obs.fail("asset_structure", "Multiple loader branches for " + enum + ".", "Use --performance-only; ambiguous map loaders are not guessed.")
        if candidates:
            chunk = candidates[0]
            break
    if chunk is None:
        raise page_obs.fail("asset_structure", "The loader has no case for " + enum + ".", "Use --performance-only; no other map universe was substituted.")
    runtime_obs, manifest = asset(runtime)
    digest = None
    for m in re.finditer(r'"\.v1\."\s*\+\s*(\{[^{}]+\})', manifest):
        mapping = json5.loads(re.sub(r"([,{])\s*(\d+)\s*:", r'\1"\2":', m.group(1)), allow_duplicate_keys=False)
        digest = mapping.get(chunk, digest)
    if not isinstance(digest, str) or not re.fullmatch(r"[\w-]+", digest):
        raise runtime_obs.fail("asset_structure", "The runtime manifest has no hash for chunk " + chunk + ".", "Use --performance-only; read the saved manifest with read ID --raw.")
    chunk_obs, payload = asset(runtime.rsplit("/", 1)[0] + "/" + chunk + ".v1." + digest + ".js")
    roots = []
    for m in re.finditer(r"\.exports\s*=\s*(\{)", payload):
        value, error, _ = json5.parse(payload, start=m.start(1), consume_trailing=False, allow_duplicate_keys=False)
        if error is None and isinstance(value, dict) and value.get("name") == "Root" and isinstance(value.get("children"), list):
            roots.append(value)
    if len(roots) != 1:
        raise chunk_obs.fail("asset_structure", "Expected one Root classification object, found " + str(len(roots)) + ".", "Use --performance-only; ambiguous assets are not guessed.")
    return roots[0], chunk_obs.url


@leaf("market", "bubbles", help="Bubble chart data: one record per stock with the chosen x, y, size and color fields.", args=[(("--x",), dict(default="sector", help="X field.")), (("--y",), dict(default="lastChange", help="Y field.")), (("--size",), dict(default="marketCap", help="Size field.")), (("--color",), dict(default="sector", help="Color field.")), (("--index",), dict(default="sp500", help="Stock universe, e.g. sp500."))], output={"[]": "{ticker, company, x, y, size, color, isETF} as published"}, narrow=["--filter", "--fields", "--limit"])
def bubbles(ctx, args, target):
    obs = ctx.observe("https://finviz.com/api/bubbles?" + urlencode({"x": args.x, "y": args.y, "size": args.size, "color": args.color, "idx": args.index}))
    obs.result["conditions"] = {key: condition(getattr(args, key)) for key in ("x", "y", "size", "color", "index")}
    obs.result["target"], obs.result["data"] = args.index, obs.json()
    return obs.result
