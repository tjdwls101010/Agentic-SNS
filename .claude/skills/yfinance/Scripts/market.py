"""Instrument discovery, screeners, market domains and event calendars."""
from collections.abc import KeysView
from datetime import date, timedelta

import yfinance as yf

import leaves
import output
from output import InputError

LOOKUP = {"all": "get_all", "stock": "get_stock", "mutualfund": "get_mutualfund", "etf": "get_etf", "index": "get_index", "future": "get_future", "currency": "get_currency", "cryptocurrency": "get_cryptocurrency"}

# 성진: Sector·Industry의 region은 yf.MarketRegion(US/GB/ASIA/EUROPE/…)이 아니라 ISO 3166-1 alpha-2다 — 다른 이름공간이라
# MarketRegion을 choices로 쓰면 실제로 동작하는 KR·JP·DE가 거절된다. 아래 목록은 실측이다: 각 코드로 top-companies를
# 부르고 US와 같은 종목이 오면 조용한 대체로 판정했다. ZZ·XX·UK·EU와 NL·CH·IE·ZA 등은 전부 그 대체에 걸렸다.
DOMAIN_REGIONS = ["US", "AR", "AU", "BR", "CA", "CN", "DE", "DK", "ES", "FI", "FR", "GB", "GR", "HK", "IL", "IN", "IT", "JP", "KR", "MY", "NO", "PT", "QA", "RU", "SE", "SG", "TH", "TR", "TW"]


def count(args):
    return leaves.effective_limit(args, leaves.get(args.group, args.leaf)) or 10


def fetch(args, context, warnings):
    if args.group == "search":
        context["coverage_scope"] = "first_page_only"
        if args.dataset == "quotes":
            return getattr(yf.Lookup(args.query, timeout=args.timeout), LOOKUP[args.type])(count=count(args))
        asked = count(args)
        search = yf.Search(args.query, max_results=0, news_count=asked if args.dataset == "news" else 0, lists_count=asked if args.dataset == "lists" else 0, include_research=args.dataset == "research", include_nav_links=False, timeout=args.timeout)
        return getattr(search, args.dataset)
    if args.group == "screen":
        return screen(args, context)
    if args.group == "calendar" and getattr(args, "symbol", None):
        return earnings(args, context)
    if args.group == "calendar":
        return calendar(args, context, warnings)
    if args.group == "market" and args.leaf in {"sector", "industry", "sectors"}:
        return domain(args, context)
    return getattr(yf.Market(args.region, timeout=args.timeout), args.leaf)


QUERY_TYPES = {"equity": yf.EquityQuery, "fund": yf.FundQuery, "etf": yf.ETFQuery}


def query_catalog(kind):
    cls = QUERY_TYPES[kind]
    return cls("EQ", ["exchange", "NAS"]) if kind == "fund" else cls("EQ", ["region", "us"])


def parse_query(text, kind):
    import json
    import math

    def build(node, path="$", depth=0):
        if depth > 32:
            raise InputError(f"{path}: query nesting exceeds 32 levels")
        if not isinstance(node, dict) or set(node) != {"operator", "operands"}:
            raise InputError(f"{path}: expected exactly operator and operands keys")
        op, operands = node["operator"], node["operands"]
        if not isinstance(op, str) or not isinstance(operands, list):
            raise InputError(f"{path}: operator must be a string; operands must be an array")
        op = op.upper()
        if op in {"AND", "OR"}:
            operands = [build(item, f"{path}.operands[{i}]", depth + 1) for i, item in enumerate(operands)]
        else:
            if not operands or not isinstance(operands[0], str):
                raise InputError(f"{path}.operands[0]: expected field name string")
            for i, value in enumerate(operands[1:], 1):
                if isinstance(value, bool) or not isinstance(value, (str, int, float)) or (isinstance(value, float) and not math.isfinite(value)):
                    raise InputError(f"{path}.operands[{i}]: expected string or finite number, not bool/null/NaN/Infinity")
            if op == "BTWN" and len(operands) == 3 and all(isinstance(v, (int, float)) for v in operands[1:]) and operands[1] > operands[2]:
                raise InputError(f"{path}.operands: BTWN lower bound exceeds upper bound")
        try:
            return QUERY_TYPES[kind](op, operands)
        except (ValueError, TypeError) as exc:
            raise InputError(f"{path}.operands: {exc}; see schema screen run and screen fields/values --type {kind}") from None

    try:
        node = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InputError(f"$ at line {exc.lineno}, column {exc.colno}: {exc.msg}; fix JSON quoting or punctuation") from None
    except RecursionError:
        raise InputError("$: query JSON is too deeply nested") from None
    return build(node)


def filtered(value, term):
    """Keep matching catalog branches while allowing large enumerations to be narrowed."""
    if not term:
        return value
    term = term.lower()
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            match = child if term in str(key).lower() else filtered(child, term)
            if match is not None and match != [] and match != {}:
                result[key] = match
        return result
    if isinstance(value, (list, tuple, set, KeysView)):
        return [item for item in value if term in str(item).lower()]
    return value if term in str(value).lower() else None


def screen(args, context):
    catalog = query_catalog(args.type)
    if args.leaf == "presets":
        return [{"name": name, "query": spec["query"].to_dict(), "sortField": spec["sortField"], "sortType": spec["sortType"]} for name, spec in yf.PREDEFINED_SCREENER_QUERIES.items() if isinstance(spec["query"], QUERY_TYPES[args.type]) and args.filter.lower() in name.lower()]
    if args.leaf == "fields":
        return [{"category": category, "field": field} for category, fields in catalog.valid_fields.items() for field in sorted(fields) if (not args.field or args.field == field) and args.filter.lower() in (category + field).lower()]
    if args.leaf == "values":
        values = catalog.valid_values
        if args.field:
            if args.field not in {field for fields in catalog.valid_fields.values() for field in fields}:
                raise InputError(f"Unknown query field {args.field}; use screen fields --type {args.type}")
            values = {args.field: values.get(args.field, "No enumerated restriction; use an appropriate finite numeric value or string.")}
        return filtered(values, args.filter)
    query = args.preset or parse_query(args.query, args.type)
    if args.sort and args.sort not in {field for fields in catalog.valid_fields.values() for field in fields} and args.sort != "ticker":
        raise InputError("Unknown --sort field; use screen fields --filter TEXT")
    size = count(args)
    response = yf.screen(query, offset=args.offset, size=size, count=size, sortField=args.sort, sortAsc=args.ascending)
    if not isinstance(response, dict):
        raise ValueError("Malformed screen response: expected a result object")
    context["upstream"] = {key: value for key, value in response.items() if key != "quotes"}
    if args.preset:
        context["preset_query"] = yf.PREDEFINED_SCREENER_QUERIES[args.preset]["query"].to_dict()
    data = response.get("quotes", [])
    displayed = min(len(data), size)
    total = response.get("total")
    if displayed and (len(data) > displayed or (isinstance(total, int) and args.offset + displayed < total) or (total is None and displayed == size)):
        context["next_offset"] = args.offset + displayed
    return data


def screen_conditions(encoded, args, context):
    """Judge the paging and sort from what the response itself reported, not from what was sent."""
    found, upstream = {}, context.get("upstream") or {}
    if "start" in upstream:
        applied = upstream.get("start") == args.offset
        found["offset"] = output.condition(args.offset, "confirmed" if applied else "not_applied", {"upstream_start": upstream.get("start")})
    if "count" in upstream:
        size = count(args)
        found["limit"] = output.condition(size, "confirmed" if upstream.get("count") <= size else "not_applied", {"upstream_count": upstream.get("count"), "total": upstream.get("total")})
    if args.sort:
        judged = output.monotonic(encoded, args.sort, bool(args.ascending))
        found["sort"] = judged or output.condition({"sort": args.sort, "ascending": bool(args.ascending)}, "unverified", {"reason": "the sort field is not among the returned fields, so the ordering cannot be checked here"})
    return found


def earnings(args, context):
    asked = count(args)
    batch = 25 if asked <= 25 else 50 if asked <= 50 else 100
    context.update(native_batch_size=batch, scope="single_symbol")
    context["upstream_requested"] = asked
    data = yf.Ticker(args.symbol).get_earnings_dates(limit=asked, offset=args.offset)
    if data is not None and data.index.hasnans:
        raise ValueError("Upstream earnings date/value alignment is unreliable after missing dates were parsed; use market earnings with a bounded date window instead.")
    displayed = min(0 if data is None else len(data), asked)
    if displayed:
        context["next_offset"] = args.offset + displayed
    return data


CALENDARS = {"earnings": "get_earnings_calendar", "economic": "get_economic_events_calendar", "ipo": "get_ipo_info_calendar", "splits": "get_splits_calendar"}
DATE_FIELDS = {"earnings": "Event Start Date", "economic": "Event Time", "ipo": "Date", "splits": "Payable On"}


def calendar(args, context, warnings):
    """--start and --end are inclusive here.

    Yahoo's own range excludes the end date, so a caller asking for one day received nothing while the CLI declared
    the boundary inclusive and the validator explicitly allowed start == end. Sending the following day makes the
    declaration true; the conditions field then checks it against the rows that came back.
    """
    native_end = (date.fromisoformat(args.end) + timedelta(days=1)).isoformat()
    native = yf.Calendars(start=args.start, end=native_end)
    asked = count(args)
    context["upstream_requested"] = asked
    kwargs = {"limit": asked, "offset": args.offset}
    if args.leaf == "earnings":
        kwargs["filter_most_active"] = args.most_active
    data = getattr(native, CALENDARS[args.leaf])(**kwargs)
    context.update(scope="US" if args.leaf == "earnings" else "native calendar universe; each row names its own region or exchange")
    if args.leaf != "splits":
        warnings.append("yfinance converts zero to null in the numeric estimate, actual, surprise and price columns; the zero/missing distinction is already lost upstream of this CLI.")
    displayed = min(len(data), asked)
    if displayed and len(data) >= asked:
        context["next_offset"] = args.offset + displayed
    return data


def calendar_conditions(encoded, args):
    if args.leaf == "ipo":
        return {"dates": output.condition({"start": args.start, "end": args.end}, "unverified",
                                          {"reason": "a row matches on any of three date fields, so a returned row's Date can lie outside the requested range"})}
    found = output.within_dates(encoded, DATE_FIELDS[args.leaf], args.start, args.end)
    return {"dates": found} if found else {}


SECTORS = ["basic-materials", "communication-services", "consumer-cyclical", "consumer-defensive", "energy", "financial-services", "healthcare", "industrials", "real-estate", "technology", "utilities"]
DOMAIN_DATA = {"overview": "overview", "top-companies": "top_companies", "research-reports": "research_reports", "industries": "industries", "top-etfs": "top_etfs", "top-funds": "top_mutual_funds", "top-performing": "top_performing_companies", "top-growth": "top_growth_companies"}


def domain(args, context):
    if args.leaf == "sectors":
        return [key for key in SECTORS if args.filter.lower() in key]
    entity = (yf.Sector if args.leaf == "sector" else yf.Industry)(args.key, region=args.region)
    if args.region != "US":
        context["region_note"] = "Outside the United States this dataset returns null names, so rows are identified by symbol alone."
    return getattr(entity, DOMAIN_DATA[args.dataset])
