"""Screener fields, enumerated values, named presets and runs, with every query value translated from the skill's scale to Yahoo's.

A caller writes a rate as a ratio (0.2 for 20%), as everywhere else in the skill. Yahoo's screener takes some rates in percentage points, and a ratio sent as-is is no error: it screens for a hundredth of the intended bound and returns a plausible list. So a rate field is translated only when its Yahoo scale was measured (scenarios/invest/measure_screen_scales.py); one that was not is refused before any request, unless --source-units says the whole query is already in Yahoo's own units.
"""
from collections.abc import KeysView
import copy
import json
import math

import yfinance as yf

from invest.receipts import Invalid
from invest.yahoo.conditions import condition
from invest.yahoo.datasets import Dataset
from invest.yahoo.info import CROSS_CURRENCY, INFO_UNITS
from invest.yahoo.units import RATIO, numeric

QUERY_TYPES = {"equity": yf.EquityQuery, "fund": yf.FundQuery, "etf": yf.ETFQuery}

# Yahoo's scale for each rate field, as measured: "percent" means 20 is 20%. A rate field missing here is unmeasured and refused without
# --source-units. From scenarios/invest/measure_screen_scales.py, whose evidence (both bands' totals, the counterpart symbols) is in
# scenarios/invest/screen-scales.json; a change to a field's scale fails the drift check in tests/invest/test_live.py.
SCALES = {
    "annualreportgrossexpenseratio": "percent", "annualreportnetexpenseratio": "percent", "annualreturnnavy1": "percent",
    "annualreturnnavy3": "percent", "annualreturnnavy5": "percent", "cashfromoperations1yrgrowth.lasttwelvemonths": "percent",
    "dilutedeps1yrgrowth.lasttwelvemonths": "percent", "dividendyield": "percent", "ebitda1yrgrowth.lasttwelvemonths": "percent",
    "ebitdamargin.lasttwelvemonths": "percent", "epsgrowth.lasttwelvemonths": "percent", "fiftytwowkpercentchange": "percent",
    "forward_dividend_yield": "percent", "grossprofitmargin.lasttwelvemonths": "percent", "leveredfreecashflow1yrgrowth.lasttwelvemonths": "percent",
    "ltdebtequity.lasttwelvemonths": "percent", "netincome1yrgrowth.lasttwelvemonths": "percent", "netincomemargin.lasttwelvemonths": "percent",
    "pctheldinsider": "percent", "pctheldinst": "percent", "percentchange": "percent", "quarterendtrailingreturnytd": "percent",
    "quarterlyrevenuegrowth.quarterly": "percent", "returnonassets.lasttwelvemonths": "percent", "returnonequity.lasttwelvemonths": "percent",
    "returnontotalcapital.lasttwelvemonths": "percent", "short_interest_percentage_change.value": "percent",
    "short_percentage_of_float.value": "percent", "short_percentage_of_shares_outstanding.value": "percent",
    "totaldebtequity.lasttwelvemonths": "percent", "totalrevenues1yrgrowth.lasttwelvemonths": "percent", "trailing_3m_return": "percent",
    "trailing_ytd_return": "percent", "turnoverratio": "percent",
}
# The quote field a returned row carries for a query field, where the two are the same measurement, so a row can be checked against the query.
RETURNED = {
    "percentchange": "regularMarketChangePercent", "fiftytwowkpercentchange": "fiftyTwoWeekChangePercent", "intradaymarketcap": "marketCap",
    "intradayprice": "regularMarketPrice", "dayvolume": "regularMarketVolume", "avgdailyvol3m": "averageDailyVolume3Month",
    "region": "region", "exchange": "exchange", "ticker": "symbol",
}
RATE_WORDS = ("growth", "margin", "percent", "pct", "yield", "return", "debtequity", "expenseratio", "turnoverratio", "short_percentage")
NOT_RATES = ("days_to_cover_short.value", "annualreturnnavy1categoryrank", "dividendpershare.lasttwelvemonths", "forward_dividend_per_share",
             "consecutive_years_of_dividend_growth_count")
TEXT_FIELDS = ("region", "exchange", "sector", "industry", "peer_group", "categoryname", "fundfamilyname", "primary_sector", "ticker",
               "morningstar_economic_moat", "morningstar_moat_trend", "morningstar_rating_change", "morningstar_stewardship", "morningstar_uncertainty")


def query_catalog(kind):
    cls = QUERY_TYPES[kind]
    return cls("EQ", ["exchange", "NAS"]) if kind == "fund" else cls("EQ", ["region", "us"])


def known_fields(kind):
    return {field for fields in query_catalog(kind).valid_fields.values() for field in fields}


def is_rate(field):
    return field not in NOT_RATES and any(word in field for word in RATE_WORDS)


def field_entry(field, category):
    """One query field: the unit a caller writes its values in, Yahoo's own scale, and whether that scale was measured."""
    if is_rate(field):
        scale = SCALES.get(field)
        entry = {"input_unit": RATIO, "yahoo_unit": scale or "unknown", "status": "measured" if scale else "unmeasured"}
    elif field in TEXT_FIELDS:
        entry = {"input_unit": "text", "yahoo_unit": "text", "status": "not_a_rate"}
    else:
        entry = {"input_unit": "as Yahoo reports it (amount, price, count or multiple)", "yahoo_unit": "same", "status": "not_a_rate"}
    return {"field": field, "category": category, **entry, "returned_as": RETURNED.get(field)}


def fields(target, args, context):
    term = (args.filter or "").lower()
    return [field_entry(field, category) for category, names in query_catalog(args.type).valid_fields.items() for field in sorted(names)
            if (not args.field or args.field == field) and term in (category + field).lower()]


def filtered(value, term):
    """Keep the matching branches of a catalog, so a large enumeration can be narrowed."""
    if not term:
        return value
    term = term.lower()
    if isinstance(value, dict):
        found = {}
        for key, child in value.items():
            match = child if term in str(key).lower() else filtered(child, term)
            if match not in (None, [], {}):
                found[key] = match
        return found
    if isinstance(value, (list, tuple, set, KeysView)):
        return [item for item in value if term in str(item).lower()]
    return value if term in str(value).lower() else None


def values(target, args, context):
    found = query_catalog(args.type).valid_values
    if args.field:
        if args.field not in known_fields(args.type):
            raise Invalid(f"Unknown query field {args.field}", fix=f"List the fields with `screen fields --type {args.type}`.")
        found = {args.field: found.get(args.field, "no enumerated restriction: any finite number or string")}
    return filtered(found, args.filter or "")


# ---- translation between the skill's scale and Yahoo's ----------------------------------------------------------------

def leaves(node):
    if node["operator"].upper() in ("AND", "OR"):
        for child in node["operands"]:
            yield from leaves(child)
    else:
        yield node


def translate(node, direction, refuse=True):
    """A copy of a query with each measured rate field's numbers moved between scales: `to_yahoo` multiplies percent-scale values by 100, `to_input` divides."""
    found = copy.deepcopy(node)
    for leaf in leaves(found):
        field = leaf["operands"][0]
        if not is_rate(field):
            continue
        scale = SCALES.get(field)
        if scale is None:
            if refuse:
                raise Invalid(f"{field} is a rate whose Yahoo scale has not been measured, so a ratio cannot be translated for it",
                              fix="Send the whole query in Yahoo's own scale with --source-units, or use a measured field (screen fields lists each field's status).")
            continue
        if scale == "percent":
            factor = 100 if direction == "to_yahoo" else 0.01
            leaf["operands"] = [field] + [round(v * factor, 12) if numeric(v) else v for v in leaf["operands"][1:]]
    return found


def parse(text):
    """The --query JSON checked for shape and value types, before any field or scale is looked at."""
    def check(node, path="$", depth=0):
        if depth > 32:
            raise Invalid(f"{path}: query nesting exceeds 32 levels")
        if not isinstance(node, dict) or set(node) != {"operator", "operands"}:
            raise Invalid(f"{path}: expected exactly the keys operator and operands")
        op, operands = node["operator"], node["operands"]
        if not isinstance(op, str) or not isinstance(operands, list):
            raise Invalid(f"{path}: operator must be a string and operands an array")
        if op.upper() in ("AND", "OR"):
            for i, item in enumerate(operands):
                check(item, f"{path}.operands[{i}]", depth + 1)
            return
        if not operands or not isinstance(operands[0], str):
            raise Invalid(f"{path}.operands[0]: expected a field name")
        for i, value in enumerate(operands[1:], 1):
            if isinstance(value, bool) or not isinstance(value, (str, int, float)) or (isinstance(value, float) and not math.isfinite(value)):
                raise Invalid(f"{path}.operands[{i}]: expected a string or a finite number, not a boolean, null, NaN or Infinity")
        if op.upper() == "BTWN" and len(operands) == 3 and all(numeric(v) for v in operands[1:]) and operands[1] > operands[2]:
            raise Invalid(f"{path}.operands: BTWN lower bound exceeds upper bound")

    try:
        node = json.loads(text)
    except json.JSONDecodeError as exc:
        raise Invalid(f"--query at line {exc.lineno}, column {exc.colno}: {exc.msg}", fix="Fix the JSON quoting or punctuation.") from None
    except RecursionError:
        raise Invalid("--query is nested too deeply") from None
    check(node)
    return node


def build(node, kind):
    """The library's query object, which checks fields and operand counts."""
    op = node["operator"].upper()
    operands = [build(child, kind) for child in node["operands"]] if op in ("AND", "OR") else node["operands"]
    try:
        return QUERY_TYPES[kind](op, operands)
    except (ValueError, TypeError) as exc:
        raise Invalid(f"--query: {exc}", fix=f"`screen fields --type {kind}` lists the fields and `screen values --type {kind}` the enumerated values.") from None


def presets(target, args, context):
    """Each preset with the query it runs, shown on the skill's scale so it can be passed to --query as written."""
    found = []
    for name, spec in yf.PREDEFINED_SCREENER_QUERIES.items():
        if not isinstance(spec["query"], QUERY_TYPES[args.type]) or (args.filter or "").lower() not in name.lower():
            continue
        raw = spec["query"].to_dict()
        unmeasured = sorted({leaf["operands"][0] for leaf in leaves(raw) if is_rate(leaf["operands"][0]) and leaf["operands"][0] not in SCALES})
        entry = {"name": name, "query": raw if unmeasured else translate(raw, "to_input"), "sortField": spec["sortField"], "sortType": spec["sortType"]}
        if unmeasured:
            entry["source_units"] = True
            entry["unmeasured"] = unmeasured
        found.append(entry)
    context.note("A preset's query is shown on the skill's scale (rates as ratios), so it can be passed to screen run --query as written; "
                 "one marked source_units carries an unmeasured rate and is shown in Yahoo's units, for --source-units.")
    return found


# ---- checking the returned rows against the query ----------------------------------------------------------------------

def truth(leaf, row):
    """True, False or None (unknown) for one condition on one returned row, on the skill's scale."""
    field, operands = leaf["operands"][0], leaf["operands"][1:]
    column = RETURNED.get(field)
    if column is None or row.get(column) is None:
        return None
    value, op = row[column], leaf["operator"].upper()
    if isinstance(value, str) or any(isinstance(v, str) for v in operands):
        value, operands = str(value).lower(), [str(v).lower() for v in operands]
        if op == "EQ":
            return value == operands[0]
        if op == "IS-IN":
            return value in operands
        return None
    if not numeric(value) or not all(numeric(v) for v in operands):
        return None
    if op == "EQ":
        return math.isclose(value, operands[0], rel_tol=1e-9)
    if op == "IS-IN":
        return any(math.isclose(value, v, rel_tol=1e-9) for v in operands)
    if op == "BTWN":
        return operands[0] <= value <= operands[1]
    return {"GT": value > operands[0], "LT": value < operands[0], "GTE": value >= operands[0], "LTE": value <= operands[0]}.get(op)


def evaluate(node, row):
    """Three-valued logic: AND is false if any part is false, OR true if any part is true, and unknown otherwise when a part is unknown."""
    op = node["operator"].upper()
    if op not in ("AND", "OR"):
        return truth(node, row)
    parts = [evaluate(child, row) for child in node["operands"]]
    if op == "AND":
        return False if False in parts else None if None in parts else True
    return True if True in parts else None if None in parts else False


def query_condition(node, rows, sent_in_source_units):
    """Whether the returned rows satisfy the query, row by row. Confirmed means the sample satisfies it, not that Yahoo applied it to every match."""
    unchecked = sorted({leaf["operands"][0] for leaf in leaves(node) if leaf["operands"][0] not in RETURNED})
    if sent_in_source_units:
        return condition(node, "unverified", {"reason": "the query was sent in Yahoo's own units (--source-units), so rows cannot be compared on the skill's scale",
                                              "unchecked_fields": unchecked})
    results = [evaluate(node, row) for row in rows]
    counts = {"rows_true": results.count(True), "rows_false": results.count(False), "rows_unknown": results.count(None), "unchecked_fields": unchecked}
    if not rows:
        status = "unverified"
    elif counts["rows_false"]:
        status = "not_applied"
    elif counts["rows_unknown"]:
        status = "unverified"
    else:
        status = "confirmed"
    return condition(node, status, counts)


def monotonic(rows, column, ascending):
    values = [r.get(column) for r in rows if r.get(column) is not None]
    if not (all(numeric(v) for v in values) or all(isinstance(v, str) for v in values)):
        return None
    if len(values) < 2:
        return None
    ordered = all(a <= b for a, b in zip(values, values[1:])) if ascending else all(a >= b for a, b in zip(values, values[1:]))
    return condition({"sort": column, "ascending": ascending}, "confirmed" if ordered else "not_applied",
                     {"first": values[0], "last": values[-1], "rows": len(values)})


def check_run(args):
    """The query's JSON, fields, operand counts and scales, and the sort field, all judged without the network."""
    if args.preset:
        return
    node = parse(args.query)
    build(node, args.type)
    if not args.source_units:
        build(translate(node, "to_yahoo"), args.type)
    if args.sort and args.sort != "ticker" and args.sort not in known_fields(args.type):
        raise Invalid(f"Unknown --sort field {args.sort}", fix=f"`screen fields --type {args.type}` lists the fields.")


def run(target, args, context):
    if args.preset:
        spec = yf.PREDEFINED_SCREENER_QUERIES[args.preset]
        kind = next(k for k, cls in QUERY_TYPES.items() if isinstance(spec["query"], cls))
        sort, ascending = args.sort or spec["sortField"], (spec["sortType"].lower() == "asc") if args.ascending is None else args.ascending
        sent = spec["query"].to_dict()
        source_units = True
        shown = {"preset": args.preset, "query": sent}
        query = args.preset
    else:
        kind = args.type
        node = parse(args.query)
        build(node, kind)  # fields and operand counts are checked as written, before any scale is looked at
        source_units = args.source_units
        sent = node if source_units else translate(node, "to_yahoo")
        query = build(sent, kind)
        sort, ascending = args.sort or "ticker", bool(args.ascending)
        shown = {"query": node}
        if source_units:
            context.warn("source_units", "The query was sent in Yahoo's own units as written (--source-units), not translated from ratios.")
    if args.sort and args.sort != "ticker" and args.sort not in known_fields(kind):
        raise Invalid(f"Unknown --sort field {args.sort}", fix=f"`screen fields --type {kind}` lists the fields.")
    context.receipt.update(sent_query=sent, sort=sort, ascending=ascending, type=kind)
    response = yf.screen(query, offset=args.offset, size=args.limit, count=args.limit, sortField=sort, sortAsc=ascending)
    if not isinstance(response, dict):
        raise ValueError("Malformed screen response: expected an object")
    rows = response.get("quotes") or []
    total = response.get("total")
    context.coverage.update(requested=args.limit, offset=args.offset, total=total)
    if rows and ((isinstance(total, int) and args.offset + len(rows) < total) or (total is None and len(rows) >= args.limit)):
        context.coverage["next_offset"] = args.offset + len(rows)  # without a total, a full page may or may not be the last
    if rows:
        context.warn("pages_move", "Rows can move between pages, and total is Yahoo's own claim.")
    normalised = [{k: (v / 100 if INFO_UNITS.get(k) and INFO_UNITS[k].convert == "percent" and numeric(v) else v) for k, v in r.items()} for r in rows]
    if args.preset:
        context.conditions["query"] = condition(shown, "unverified", {"reason": "a preset's query is Yahoo's, sent in its own units"})
    else:
        context.conditions["query"] = query_condition(node, normalised, source_units)
        if context.conditions["query"]["status"] == "confirmed":
            context.warn("sample_only", "Confirmed means the returned rows satisfy the query; it is not evidence that Yahoo applied it to every match.")
    if "count" in response:
        count = response.get("count")
        context.conditions["limit"] = condition(args.limit, "confirmed" if isinstance(count, int) and count <= args.limit and len(rows) <= args.limit else "not_applied",
                                                {"source_count": count, "rows": len(rows)})
    if "start" in response:
        context.conditions["offset"] = condition(args.offset, "confirmed" if response.get("start") == args.offset else "not_applied", {"source_start": response.get("start")})
    column = RETURNED.get(sort)
    if column:
        context.conditions["sort"] = monotonic(normalised, column, ascending) or condition({"sort": sort}, "unverified", {"reason": "too few rows carry the sort field"})
    else:
        context.conditions["sort"] = condition({"sort": sort, "ascending": ascending}, "unverified", {"reason": "no returned field carries the sort field"})
    return rows


DATASETS = {
    "screen.presets": Dataset(presets, form="records", ticker=False, coverage="Yahoo's predefined screens for --type",
                              notes=("A preset's name is not its condition (small_cap_gainers has no gain condition); read its query.",)),
    "screen.fields": Dataset(fields, form="rows", ticker=False, keys=("field",), coverage="every query field yfinance accepts for --type"),
    "screen.values": Dataset(values, form="records", ticker=False, coverage="the enumerated values query fields accept for --type"),
    "screen.run": Dataset(
        run, form="rows", ticker=False, counted=True, units=INFO_UNITS, keys=("symbol",), row_currency="currency", check=check_run, cross_currency=CROSS_CURRENCY,
        coverage="the rows matching the query, in the sort order, for this page: not a census of the market",
        possible=("source_units", "sample_only", "pages_move")),
}
