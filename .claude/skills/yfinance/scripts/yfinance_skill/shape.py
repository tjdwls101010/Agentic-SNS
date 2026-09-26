"""The skill's own representation of a value, and the shape predicates every path shares.

Selection runs on the *encoded* value rather than on pandas objects. That is what lets `read` reuse it unchanged: a
saved observation is encoded JSON, so re-reading it is the same code that printed it the first time, and a slice of a
stored table cannot disagree with the original about what a row was.
"""
import math

TABLE_KEYS = {"index", "columns", "data", "index_names", "column_names"}


def is_table(value):
    return isinstance(value, dict) and TABLE_KEYS <= set(value)


def is_sided(value):
    """An option chain is two independently limited tables under one result, not a mapping whose keys are fields.

    Treated as a mapping, a limit found no rows to cut and --fields was checked against the side names, so `read` both
    returned everything and refused a column name the first call had accepted.
    """
    return isinstance(value, dict) and bool(value) and not is_table(value) and all(is_table(v) for v in value.values())


def is_empty(data):
    if is_table(data):
        return not data["data"] or all(cell is None for row in data["data"] for cell in row)
    if isinstance(data, dict):
        return not data or all(is_empty(value) for value in data.values())
    if isinstance(data, (list, tuple)):
        return not data or all(is_empty(value) for value in data)
    return data is None or (isinstance(data, float) and not math.isfinite(data))


def row_count(data):
    if is_table(data):
        return len(data["data"])
    if isinstance(data, list):
        return len(data)
    return None


def column(data, name):
    if not is_table(data):
        return []
    if name == "index":
        return list(data["index"])
    by_name = {str(c): i for i, c in enumerate(data["columns"])}
    return [row[by_name[name]] for row in data["data"]] if name in by_name else []
