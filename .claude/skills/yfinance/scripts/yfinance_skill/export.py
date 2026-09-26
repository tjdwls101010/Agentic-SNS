"""--out: the rows an observation received, written as one long CSV for computation, and never half a file.

The screen is a window; a drawdown, a volatility or a correlation needs every row. The file holds the saved values with
every digit and timestamp as they arrived — the screen's trimming is for reading, not for arithmetic. Several targets
share one file under a `target` column, which is the shape a comparison pivots from.
"""
import csv
import io
import json
import os
from pathlib import Path
import tempfile

from yfinance_skill.shape import is_sided, is_table
from yfinance_skill.envelope import InputError

RESERVED = ("target", "side", "key", "value")


class Unpublished(Exception):
    """The file could not be published; `code` says whether the caller can fix it (invalid) or the disk failed (local_io)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def check_path(path):
    """Refused before any request is paid for. Publication checks again, since the file can appear in between."""
    target = Path(path)
    if target.exists():
        raise InputError(f"--out {path} already exists; choose a new path, since an existing file is never overwritten.")
    if not target.parent.is_dir():
        raise InputError(f"--out {path}: its directory does not exist; create it or choose another path.")


def cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def flatten(record, prefix="", depth=0):
    """The dotted paths --fields uses; deeper objects and lists are kept whole as JSON."""
    flat = {}
    for key, value in record.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and value and depth < 3:
            flat.update(flatten(value, name + ".", depth + 1))
        else:
            flat[name] = value
    return flat


def label(column):
    return " | ".join(map(str, column)) if isinstance(column, list) else str(column)


def claim(name, taken):
    """A name no other column of this row has: a clash becomes source.<name>, then source.<name>.2, never a lost value."""
    found, n = name, 1
    while found in taken:
        found = f"source.{name}" if n == 1 else f"source.{name}.{n}"
        n += 1
    taken.add(found)
    return found


def table_rows(table, fixed):
    names = table.get("index_names") or [None]
    index_columns = [n if n is not None else ("index" if len(names) == 1 else f"index_{i}") for i, n in enumerate(names)]
    for position, row in zip(table["index"], table["data"]):
        levels = position if len(index_columns) > 1 and isinstance(position, list) else [position]
        yield [*fixed.items(), *zip(index_columns, levels)], list(zip((label(c) for c in table["columns"]), row)), list(fixed) + index_columns


def shaped(data, keyed=False):
    """(identifying columns, [(identifying pairs, field pairs)]) for every shape that is rows; None for a single record."""
    if is_table(data) or is_sided(data):
        tables = [({}, data)] if is_table(data) else [({"side": side}, table) for side, table in data.items()]
        pairs, keys = [], []
        for fixed, table in tables:
            for ident, fields, keys in table_rows(table, fixed):
                pairs.append((ident, fields))
        return keys, pairs
    if keyed:
        return ["key"], [([("key", r.get("key"))], list(flatten({k: v for k, v in r.items() if k != "key"}).items())) for r in data]
    if isinstance(data, list) and all(isinstance(r, dict) for r in data):
        return [], [([], list(flatten(r).items())) for r in data]
    if isinstance(data, list):
        return [], [([("value", v)], []) for v in data]
    return None


def rows_of(data, keyed=False):
    """Rows whose every name is unique: a source field or index level that shares a name with `target`, a side, a
    key or another column is written as source.<name> rather than overwriting the value that identifies the row."""
    found = shaped(data, keyed)
    if found is None:
        raise InputError("--out writes rows; this result is a single record — read it on screen instead.")
    keys, pairs = found
    rows = []
    for ident, fields in pairs:
        taken = {"target"}
        rows.append(({claim(k, taken): v for k, v in ident}, {claim(k, taken): v for k, v in fields}))
    return keys, rows


def publish(path, parts):
    """Write every target's rows, then link the finished file into place.

    os.link fails when the destination exists, so a file that appeared after check_path keeps its bytes; replace would
    overwrite it. The temporary file is removed whatever happens, so no half-written CSV is ever left at either name.
    """
    columns = ["target"]
    lines = []
    for target, (keys, records) in parts:
        for fixed, rest in records:
            record = {"target": target, **fixed, **rest}
            for key in record:
                if key not in columns:
                    columns.append(key)
            lines.append(record)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, restval="", lineterminator="\n")
    writer.writeheader()
    writer.writerows({k: cell(v) for k, v in line.items()} for line in lines)
    destination = Path(path)
    handle, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".part", dir=destination.parent)  # ours alone
    temporary = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(buffer.getvalue())
        os.link(temporary, destination)
    except FileExistsError:
        raise Unpublished("invalid", f"--out {path} appeared before the file could be published and was left untouched.") from None
    except OSError as exc:
        raise Unpublished("local_io", f"--out {path} could not be written: {exc}") from None
    finally:
        temporary.unlink(missing_ok=True)
    return columns


def summary(path, columns, keys, records):
    """What the screen gets instead of the rows: where they went and which span they cover."""
    found = {"out": str(path), "rows": len(records), "columns": columns}
    if [k for k in keys if k != "side"] and records:
        found["first"], found["last"] = list(records[0][0].values())[-1], list(records[-1][0].values())[-1]
    return found
