"""Screener fields, enumerated values, named presets and runs."""
from collections.abc import KeysView
import json
import math

import yfinance as yf

from yfinance_skill.envelope import InputError, condition, monotonic
from yfinance_skill.yahoo.datasets import COUNT, CURRENCY, MULTIPLE, PERCENT, Dataset, asked

QUERY_TYPES = {"equity": yf.EquityQuery, "fund": yf.FundQuery, "etf": yf.ETFQuery}


def query_catalog(kind):
    cls = QUERY_TYPES[kind]
    return cls("EQ", ["exchange", "NAS"]) if kind == "fund" else cls("EQ", ["region", "us"])


def known_fields(catalog):
    return {field for fields in catalog.valid_fields.values() for field in fields}


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


def presets(target, args, context, warnings):
    return [{"name": name, "query": spec["query"].to_dict(), "sortField": spec["sortField"], "sortType": spec["sortType"]} for name, spec in yf.PREDEFINED_SCREENER_QUERIES.items() if isinstance(spec["query"], QUERY_TYPES[args.type]) and args.filter.lower() in name.lower()]


def fields(target, args, context, warnings):
    catalog = query_catalog(args.type)
    return [{"category": category, "field": field} for category, names in catalog.valid_fields.items() for field in sorted(names) if (not args.field or args.field == field) and args.filter.lower() in (category + field).lower()]


def values(target, args, context, warnings):
    catalog = query_catalog(args.type)
    found = catalog.valid_values
    if args.field:
        if args.field not in known_fields(catalog):
            raise InputError(f"Unknown query field {args.field}; use screen fields --type {args.type}")
        found = {args.field: found.get(args.field, "No enumerated restriction; use an appropriate finite numeric value or string.")}
    return filtered(found, args.filter)


def parse_query(text, kind):
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


def preset_defaults(args):
    """A preset fixes its own universe and sort."""
    if args.preset:
        if args.preset not in yf.PREDEFINED_SCREENER_QUERIES:
            raise InputError("Unknown --preset; use screen presets --filter TEXT")
        preset = yf.PREDEFINED_SCREENER_QUERIES[args.preset]
        args.type = next(kind for kind, cls in QUERY_TYPES.items() if isinstance(preset["query"], cls))
        args.sort = args.sort or preset["sortField"]
        if args.ascending is None:
            args.ascending = preset["sortType"].lower() == "asc"


def screen_conditions(encoded, args, context):
    """Judge the paging and sort from what the response itself reported, not from what was sent."""
    found, upstream = {}, context.get("upstream") or {}
    if "start" in upstream:
        applied = upstream.get("start") == args.offset
        found["offset"] = condition(args.offset, "confirmed" if applied else "not_applied", {"upstream_start": upstream.get("start")})
    if "count" in upstream:
        size = asked(args, DATASETS["screen.run"])
        found["limit"] = condition(size, "confirmed" if upstream.get("count") <= size else "not_applied", {"upstream_count": upstream.get("count"), "total": upstream.get("total")})
    if args.sort:
        judged = monotonic(encoded, args.sort, bool(args.ascending))
        found["sort"] = judged or condition({"sort": args.sort, "ascending": bool(args.ascending)}, "unverified", {"reason": "the sort field is not among the returned fields, so the ordering cannot be checked here"})
    return found


SCREEN_FIELDS = ("symbol", "shortName", "regularMarketPrice", "regularMarketChangePercent", "regularMarketVolume",
                 "marketCap", "trailingPE", "fiftyTwoWeekChangePercent", "averageAnalystRating", "fullExchangeName")


def run(target, args, context, warnings):
    catalog = query_catalog(args.type)
    query = args.preset or parse_query(args.query, args.type)
    if args.sort and args.sort not in known_fields(catalog) and args.sort != "ticker":
        raise InputError("Unknown --sort field; use screen fields --filter TEXT")
    size = asked(args, DATASETS["screen.run"]) or 10
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


DATASETS = {
    "screen.presets": Dataset(
        presets,
        interpretation={"name_is_not_the_condition": "Each entry carries the query it runs. Describe a preset's results by that query, not by its name: small_cap_gainers, for one, screens for small capitalisation sorted by volume and has no gain condition."}),
    "screen.fields": Dataset(fields),
    "screen.values": Dataset(values),
    "screen.run": Dataset(
        run, rows=25, fields=SCREEN_FIELDS, conditions=screen_conditions, prepare=preset_defaults,
        units={"regularMarketChangePercent": PERCENT, "fiftyTwoWeekChangePercent": PERCENT, "marketCap": CURRENCY,
               "trailingPE": MULTIPLE, "regularMarketVolume": COUNT},
        interpretation={"query_scale": "A growth threshold in the query is in percentage points, while the same measurement in a quote is a ratio: BTWN quarterlyrevenuegrowth.quarterly 20 30 selects companies whose quote revenueGrowth is 0.2-0.3, and 0.20 0.30 selects companies growing a fifth of a percent. Neither call fails, so an output ratio reused as a bound screens for something a hundredfold smaller and still returns a plausible list.",
                        "matches_not_a_census": "These are the rows matching the query, ordered by the sort field. They are not a verified census of a market, and total is the provider's own claim.",
                        "paging": "--offset continues a query rather than reading an immutable snapshot; rows can move between pages.",
                        "default_fields": "Each row carries far more fields than the default projection; --fields reaches them and --list-fields names them."}),
}
