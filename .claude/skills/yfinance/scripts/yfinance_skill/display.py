"""What the screen prints: the stdout copy of an encoded value. The saved observation and --out keep it as encoded."""
import json
import re

from yfinance_skill.shape import is_sided, is_table

STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T")
MIDNIGHT = re.compile(r"^\d{4}-\d{2}-\d{2}T00:00:00(?:\.0+)?(Z|[+-]\d{2}:\d{2})?$")


def number(value, precise=False):
    """A float prints as the information the source had, never as the arithmetic that carried it here.

    An integral float is an integer. A field whose source precision is established (`precise`) prints to seven
    significant digits — Yahoo serves prices as float32, and an adjusted price is that float32 times a ratio — but
    never loses an integer digit. Every other float keeps every digit: its precision is not known, so none is dropped.
    """
    if isinstance(value, bool) or not isinstance(value, float):
        return value
    if value.is_integer() and abs(value) < 2 ** 53:
        return int(value)
    if not precise:
        return value
    digits = max(7, len(str(int(abs(value)))))
    rounded = float(f"{value:.{digits}g}")
    return int(rounded) if rounded.is_integer() and abs(rounded) < 2 ** 53 else rounded


def dated(values, zoned):
    """Every stamp on this axis is a midnight, and dropping the offset loses nothing because the zone is stated."""
    stamps = [v for v in values if isinstance(v, str) and STAMP.match(v)]
    if not stamps:
        return False
    for stamp in stamps:
        found = MIDNIGHT.match(stamp)
        if not found or (found[1] and not zoned):
            return False
    return True


def day(value):
    return value[:10] if isinstance(value, str) and STAMP.match(value) else value


def deep(value):
    if isinstance(value, dict):
        return {k: deep(v) for k, v in value.items()}
    if isinstance(value, list):
        return [deep(v) for v in value]
    return number(value)


def display_table(table, full, precise, zoned):
    """Date-only is judged on the whole observation's axis, so a window cannot print a date its neighbours print as a time."""
    full = full if is_table(full) else table
    out = dict(table)
    if dated(full["index"], zoned):
        out["index"] = [day(v) for v in table["index"]]
    position = {str(c): i for i, c in enumerate(full["columns"])}  # by position: a column may itself be named "index"
    whole = {name: [row[i] for row in full["data"]] for name, i in position.items()}
    shortened = {str(c) for c in table["columns"] if dated(whole.get(str(c), []), zoned)}
    exact = {str(c) for c in table["columns"]} & set(precise)
    out["data"] = [[day(v) if str(c) in shortened else number(v, str(c) in exact) for c, v in zip(table["columns"], row)] for row in table["data"]]
    out["columns"] = deep(table["columns"])
    for axis in ("index_names", "column_names"):
        if all(name is None for name in table.get(axis) or []):
            out.pop(axis, None)
    return out


def display(data, full=None, precise=(), zoned=False):
    """The screen's copy of an encoded value. Only stdout goes through here; the saved observation stays as encoded."""
    if is_table(data):
        return display_table(data, full, precise, zoned)
    if is_sided(data):
        return {side: display_table(table, (full or {}).get(side), precise, zoned) for side, table in data.items()}
    return deep(data)


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
