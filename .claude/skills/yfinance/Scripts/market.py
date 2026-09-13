"""Instrument discovery, screeners, market domains and event calendars."""
from collections.abc import KeysView

import yfinance as yf

from output import InputError

LOOKUP = {"all": "get_all", "stock": "get_stock", "mutualfund": "get_mutualfund", "etf": "get_etf", "index": "get_index", "future": "get_future", "currency": "get_currency", "cryptocurrency": "get_cryptocurrency"}


def fetch(args, context, warnings):
    if args.group == "search":
        context["coverage"] = "first_page_only"
        if args.dataset == "quotes":
            return getattr(yf.Lookup(args.query, timeout=args.timeout), LOOKUP[args.type])(count=args.limit)
        search = yf.Search(args.query, max_results=0, news_count=args.limit if args.dataset == "news" else 0, lists_count=args.limit if args.dataset == "lists" else 0, include_research=args.dataset == "research", include_nav_links=args.dataset == "nav", timeout=args.timeout)
        return getattr(search, args.dataset)
    if args.group == "screen":
        return screen(args, context)
    if args.group == "calendar" and getattr(args, "symbol", None):
        return earnings(args, context)
    if args.group == "calendar":
        return calendar(args, context, warnings)
    if args.group == "market" and args.leaf in {"sector", "industry", "sectors"}:
        return domain(args, context)
    if args.group == "market":
        context.update(region=args.region, scope="Yahoo native market response")
        if args.leaf == "status" and args.region != "US":
            warnings.append("Yahoo markettime may ignore non-US regions; yfinance returns empty on detected mismatch.")
        return getattr(yf.Market(args.region, timeout=args.timeout), args.leaf)
    raise InputError("Unsupported data purpose")


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
    if args.preset and args.preset not in yf.PREDEFINED_SCREENER_QUERIES:
        raise InputError("Unknown --preset; use screen presets --filter TEXT")
    if args.sort and args.sort not in {field for fields in catalog.valid_fields.values() for field in fields} and args.sort != "ticker":
        raise InputError("Unknown --sort field; use screen fields --filter TEXT")
    response = yf.screen(query, offset=args.offset, size=args.limit, count=args.limit, sortField=args.sort, sortAsc=args.ascending)
    if not isinstance(response, dict):
        raise ValueError("Malformed screen response: expected a result object")
    context["upstream"] = {key: value for key, value in response.items() if key != "quotes"}
    data = response.get("quotes", [])
    displayed = min(len(data), args.limit)
    total = response.get("total")
    if displayed and (len(data) > displayed or (isinstance(total, int) and args.offset + displayed < total) or (total is None and displayed == args.limit)):
        context["next_offset"] = args.offset + displayed
        context["pagination"] = "Remote offset; later queries may observe a changed snapshot."
    return data



def earnings(args, context):
    batch = 25 if args.limit <= 25 else 50 if args.limit <= 50 else 100
    context.update(native_batch_size=batch, date_meaning="Earnings Date as reported, with native timezone", scope="single_symbol", remaining=None, pagination="Remote offset is a candidate, not proof that more rows exist; upstream may discard undated rows and results can change between requests.")
    data = yf.Ticker(args.symbol).get_earnings_dates(limit=args.limit, offset=args.offset)
    if data is not None and data.index.hasnans:
        raise ValueError("Upstream earnings date/value alignment is unreliable after missing dates were parsed; use market earnings with a bounded date window instead.")
    count = 0 if data is None else len(data)
    displayed = min(count, args.limit)
    if displayed:
        context["next_offset"] = args.offset + displayed
    return data


CALENDARS = {"earnings": "get_earnings_calendar", "economic": "get_economic_events_calendar", "ipo": "get_ipo_info_calendar", "splits": "get_splits_calendar"}


def calendar(args, context, warnings):
    native = yf.Calendars(start=args.start, end=args.end)
    kwargs = {"limit": args.limit, "offset": args.offset}
    if args.leaf == "earnings":
        kwargs["filter_most_active"] = args.most_active
    data = getattr(native, CALENDARS[args.leaf])(**kwargs)
    context.update(scope="US" if args.leaf == "earnings" else "Native calendar universe; inspect country/exchange fields", date_field="startdatetime", start_boundary="native_inclusive", end_boundary="native_inclusive", pagination="Remote offset; the snapshot may change between requests.")
    if args.leaf == "ipo":
        context.update(date_field=["startdatetime", "filingdate", "amendeddate"], date_meaning="Any listing, filing or amendment date matches", start_boundary="native_gtelt_unverified", end_boundary="native_gtelt_unverified")
    elif args.leaf == "splits":
        context["date_meaning"] = "Payable On"
    elif args.leaf == "economic":
        context["date_meaning"] = "Event Time"
    else:
        context["date_meaning"] = "Event Start Date"
    if args.leaf != "splits":
        warnings.append("yfinance Calendars converts zero to NaN/null in numeric estimate/actual/surprise or IPO price/share columns; the zero/missing distinction is already lost upstream of this CLI.")
    displayed = min(len(data), args.limit)
    if displayed and len(data) >= args.limit:
        context["next_offset"] = args.offset + displayed
    return data


SECTORS = ["basic-materials", "communication-services", "consumer-cyclical", "consumer-defensive", "energy", "financial-services", "healthcare", "industrials", "real-estate", "technology", "utilities"]
DOMAIN_DATA = {"overview": "overview", "top-companies": "top_companies", "research-reports": "research_reports", "industries": "industries", "top-etfs": "top_etfs", "top-funds": "top_mutual_funds", "top-performing": "top_performing_companies", "top-growth": "top_growth_companies"}


def domain(args, context):
    if args.leaf == "sectors":
        context["coverage"] = "Known Yahoo sector keys; not a live universe enumeration"
        return [key for key in SECTORS if args.filter.lower() in key]
    entity = (yf.Sector if args.leaf == "sector" else yf.Industry)(args.key, region=args.region)
    context.update(key=args.key, region=args.region, currency=None, units="Native values; market weights are not rescaled.")
    return getattr(entity, DOMAIN_DATA[args.dataset])
