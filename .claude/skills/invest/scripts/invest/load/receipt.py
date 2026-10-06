"""Targets' observations turned into one long file and one receipt: rows under a target column, the receipt's inline copy, and its preview.

The file is for computation and keeps every value as received; only the inline copy is shaped for reading (seven significant digits for prices, a date without its midnight). Several targets share one file because a comparison pivots from that shape, so every name in it is made unique rather than letting a source column called "target" overwrite the one that identifies the row.
"""
import re

from invest import receipts, results as store

PREVIEW_ROWS = 3
MIDNIGHT = re.compile(r"^\d{4}-\d{2}-\d{2}T00:00:00(?:\.0+)?(?:Z|[+-]\d{2}:\d{2})?$")
COMPACT_AT = 12  # a units map longer than this names its most common unit once, as "*"


def claim(name, taken):
    """A name no other column has: a clash becomes source.<name>, then source.<name>.2, never a lost value."""
    found, n = name, 1
    while found in taken:
        found = f"source.{name}" if n == 1 else f"source.{name}.{n}"
        n += 1
    taken.add(found)
    return found


def renamed(columns):
    taken = {"target"}
    return [claim(c, taken) for c in columns]


def long_table(observed):
    """(columns, rows) for every target's rows: target first, then the union of the targets' columns in first-seen order."""
    columns, rows = ["target"], []
    for target, found in observed:
        names = renamed(found.columns)
        for name in names:
            if name not in columns:
                columns.append(name)
        position = {name: i for i, name in enumerate(names)}
        for row in found.rows:
            rows.append([target] + [row[position[c]] if c in position else None for c in columns[1:]])
    width = len(columns)
    return columns, [r + [None] * (width - len(r)) for r in rows]


# ---- the inline copy ------------------------------------------------------------------------------------------------------

def number(value, precise=False):
    """An integral float reads as an integer; a price keeps the seven significant digits Yahoo serves, never losing an integer digit."""
    if isinstance(value, bool) or not isinstance(value, float):
        return value
    if value.is_integer() and abs(value) < 2 ** 53:
        return int(value)
    if not precise:
        return value
    digits = max(7, len(str(int(abs(value)))))
    rounded = float(f"{value:.{digits}g}")
    return int(rounded) if rounded.is_integer() and abs(rounded) < 2 ** 53 else rounded


def shown_rows(found, fields):
    """The rows as the receipt shows them: projected to `fields` (with the identifying columns kept), dates shortened, prices to seven digits."""
    columns = found.columns
    if fields:
        keep = [c for c in columns if c in fields or c in found.keys]
    else:
        keep = list(columns)
    index = [columns.index(c) for c in keep]
    dated = {c for c in keep if found.units.get(c) in ("date", "datetime") and all(
        v is None or (isinstance(v, str) and MIDNIGHT.match(v)) for v in (r[columns.index(c)] for r in found.rows))}
    out = []
    for row in found.rows:
        entry = {}
        for c, i in zip(keep, index):
            value = row[i]
            entry[c] = value[:10] if c in dated and isinstance(value, str) else number(value, c in found.precise)
        out.append(entry)
    return out


def projected(value, fields):
    if isinstance(value, dict):
        return {k: v for k, v in value.items() if k in fields}
    if isinstance(value, list):
        return [projected(v, fields) for v in value]
    return value


def shown_records(found, fields):
    chosen = fields or found.fields
    return projected(found.records, chosen) if chosen else found.records


def preview(rows, shorten=None):
    """(first, last) rows of an inline copy that did not fit; a single record has none. `shorten` is a dataset's short form of one record."""
    if isinstance(rows, list) and rows:
        rows = [shorten(r) for r in rows] if shorten else rows
        return rows[:PREVIEW_ROWS], rows[-PREVIEW_ROWS:] if len(rows) > PREVIEW_ROWS else []
    return None


def compact(units):
    """{column: unit} with the most common unit named once as "*" when the map is long; receipt.json keeps every column."""
    if len(units) <= COMPACT_AT:
        return dict(units)
    counts = {}
    for unit in units.values():
        counts[unit] = counts.get(unit, 0) + 1
    common = max(counts, key=counts.get)
    if counts[common] < COMPACT_AT // 2:
        return dict(units)
    return {"*": common, **{c: u for c, u in units.items() if u != common}}


# ---- the receipt ------------------------------------------------------------------------------------------------------------

def target_entry(target, status, found, observed, fields):
    entry = {"target": target, "status": status}
    if status == "not_attempted":
        entry["error"] = receipts.failure("not_attempted", "Not attempted: Yahoo rate-limited an earlier target", "Wait, then retry with fewer targets.")
        return entry, {}
    if status == "error":
        entry.update(observed_at=observed, warnings=[], error=receipts.failure(found.code, found, found.fix))
        return entry, {}
    entry.update(rows=found.count, warnings=list(found.warnings), observed_at=observed)
    if found.as_of:
        entry["as_of"] = found.as_of
    if found.currency:
        entry["currency"] = found.currency
    if found.financial_currency:
        entry["financial_currency"] = found.financial_currency
    if found.coverage:
        entry["coverage"] = found.coverage
    if found.conditions:
        entry["conditions"] = found.conditions
    if status == "ok":
        entry["data"] = shown_rows(found, fields) if found.format == "csv" else shown_records(found, fields)
    return entry, found.receipt


def assemble(args, outcomes, ident):
    """(document, full receipt, table, records, previews). The document is what prints before any cut; the full receipt is receipt.json; previews[i] is the i-th target's (first, last) rows for a receipt that cannot carry its data."""
    fields = list(args.fields or [])
    results, extras, observed = [], [], []
    warnings, notes, units, statuses = {}, [], {}, {}
    projection = bool(fields)
    for target, status, found, when in outcomes:
        entry, extra = target_entry(target, status, found, when, fields)
        results.append(entry)
        extras.append(extra)
        if status in ("ok", "empty"):
            for code, text in found.warnings.items():
                warnings.setdefault(code, text)
            notes += [n for n in found.notes if n not in notes]
            units.update(found.units)
            statuses.update(found.statuses)
            if status == "ok":
                observed.append((target, found))
                projection = projection or (found.format == "json" and bool(found.fields))
    table = records = None
    file = None
    if observed and observed[0][1].format == "csv":
        table = long_table(observed)
        units = {"target": "text", **{c: units.get(c.removeprefix("source."), "text") for c in table[0][1:]}}
        file = {"path": None, "format": "csv", "rows": len(table[1]), "columns": len(table[0])}
    elif observed:
        records = [{"target": t, "data": f.records} for t, f in observed]
        file = {"path": None, "format": "json", "rows": sum(f.count or 0 for _, f in observed), "columns": None}
    if file:
        file["path"] = store.paths(ident)["csv" if file["format"] == "csv" else "json"]
    if projection:
        notes.append("Inline data shows a selection of fields (--fields, or a default for a wide record); the file holds every field.")
    shown_units = units
    if fields and file and file["format"] == "json":
        shown_units = {k: v for k, v in units.items() if k in fields}
    elif not fields and observed and observed[0][1].format == "json" and observed[0][1].fields:
        shown_units = {k: v for k, v in units.items() if k in observed[0][1].fields}
    document = {"status": receipts.document_status([r["status"] for r in results]), "command": args.command, "file": file,
                "units": compact(shown_units), "warnings": [{"code": c, "text": t} for c, t in warnings.items()], "notes": notes,
                "results": [receipts.ordered(r, receipts.TARGET_ORDER) for r in results], "trimmed": False, "projected": projection}
    full = {"command": args.command, "id": ident, "status": document["status"], "request": request(args), "file": file,
            "columns": table[0] if table else None, "units": units, "unit_status": statuses,
            "warnings": [{"code": c, "text": t} for c, t in warnings.items()], "notes": notes,
            "results": [receipts.ordered({k: v for k, v in r.items() if k != "data"} | ({"source": x} if x else {}), receipts.TARGET_ORDER)
                        for r, x in zip(results, extras)]}
    previews = [preview(r.get("data"), found.preview if status == "ok" else None) for r, (_, status, found, _) in zip(results, outcomes)]
    return document, full, table, records, previews


def request(args):
    """The arguments in force, as receipt.json records them."""
    return {k: v for k, v in vars(args).items() if k not in ("command", "targets", "handler") and not callable(v)}
