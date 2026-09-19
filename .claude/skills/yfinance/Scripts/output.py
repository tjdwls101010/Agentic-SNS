"""Lossless encoding, and the selection every path shares.

Selection runs on the *encoded* value rather than on pandas objects. That is what lets `read` reuse this function
unchanged: a saved observation is encoded JSON, so re-reading it is the same code that printed it the first time, and a
slice of a stored table cannot disagree with the original about what a row was.
"""
from collections.abc import KeysView
import datetime as dt
import json
import math

import numpy as np
import pandas as pd

TABLE_KEYS = {"index", "columns", "data", "index_names", "column_names"}


class InputError(ValueError):
    pass


def encode(value):
    if isinstance(value, pd.DataFrame):
        return {"index": encode(value.index.tolist()), "columns": encode(value.columns.tolist()), "data": [[encode(v) for v in row] for row in value.itertuples(index=False, name=None)], "index_names": encode(value.index.names), "column_names": encode(value.columns.names)}
    if isinstance(value, pd.Series):
        return encode(value.to_frame())
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.datetime64):
        return None if np.isnat(value) else pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        return encode(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.tzinfo):
        return str(value)
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset, KeysView)):
        return [encode(v) for v in sorted(value, key=str)]
    if isinstance(value, (list, tuple, np.ndarray)):
        return [encode(v) for v in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported output type: {type(value).__name__}")


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


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


# ---- field paths -------------------------------------------------------------------------------------------------


def dig(record, path):
    """Resolve a dotted field path. company news nests its article under content, so the only projection that reaches
    a title is content.title; a flat --fields could name nothing that actually reduced the payload."""
    value = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None, False
        value = value[part]
    return value, True


def paths_of(record, prefix="", depth=0):
    """Every dotted path a record offers: the nested objects as well as the scalars inside them.

    Listing only the leaves made a whole sub-object unselectable, so --fields content.thumbnail was refused as unknown
    while content.thumbnail.originalUrl was accepted — a reader cannot tell from the value which one a name is.
    """
    found = []
    for key, value in record.items():
        here = f"{prefix}{key}"
        found.append(here)
        if isinstance(value, dict) and value and depth < 3:
            found.extend(paths_of(value, here + ".", depth + 1))
    return found


def available_fields(data):
    if is_table(data):
        return [str(c) for c in data["columns"]]
    if isinstance(data, list) and data and all(isinstance(r, dict) for r in data):
        return list(dict.fromkeys(p for r in data for p in paths_of(r)))
    if isinstance(data, dict):
        return list(dict.fromkeys(paths_of(data)))
    return []


# ---- selection ---------------------------------------------------------------------------------------------------


def row_count(data):
    if is_table(data):
        return len(data["data"])
    if isinstance(data, list):
        return len(data)
    return None


def take_rows(data, keep, recent):
    """Keep `keep` rows from the end when the source publishes oldest first, otherwise from the start.

    The direction is the leaf's, never a global rule: a series printed oldest first loses its newest rows to a prefix
    cut, and one printed newest first loses its newest rows to a suffix cut. Both failures are silent.
    """
    if keep is None or row_count(data) is None or row_count(data) <= keep:
        return data, None
    side = "newest" if recent else "first"
    if is_table(data):
        rows = data["data"][-keep:] if recent else data["data"][:keep]
        index = data["index"][-keep:] if recent else data["index"][:keep]
        return dict(data, data=rows, index=index), side
    return (data[-keep:] if recent else data[:keep]), side


def project(data, fields):
    """Keep the named fields. Missing names are an error rather than a silent empty column."""
    if is_table(data):
        by_name = {str(c): i for i, c in enumerate(data["columns"])}
        missing = [f for f in fields if f not in by_name]
        if missing:
            raise InputError(f"Unknown fields {missing}; list this command's fields with --list-fields --filter TEXT.")
        keep = [by_name[f] for f in fields]
        return dict(data, columns=[data["columns"][i] for i in keep], data=[[row[i] for i in keep] for row in data["data"]])
    if isinstance(data, list) and data and all(isinstance(r, dict) for r in data):
        missing = [f for f in fields if not any(dig(r, f)[1] for r in data)]
        if missing:
            raise InputError(f"Unknown fields {missing}; list this command's fields with --list-fields --filter TEXT.")
        return [{f: dig(r, f)[0] for f in fields} for r in data]
    if isinstance(data, dict):
        resolved = {f: dig(data, f) for f in fields}
        missing = [f for f, (_, found) in resolved.items() if not found]
        if missing:
            raise InputError(f"Unknown fields {missing}; list this command's fields with --list-fields --filter TEXT.")
        return {f: value for f, (value, _) in resolved.items()}
    raise InputError("This result has no named fields to select; narrow it with --limit instead.")


def select(data, args, item, coverage=None, keep=None):
    """Apply --list-fields, the field projection and the row window, recording what was left out.

    `keep` overrides the row count so the budget can narrow an already-selected result without re-deciding the
    projection or the direction.
    """
    coverage = {} if coverage is None else coverage
    if getattr(args, "list_fields", False):
        term = (getattr(args, "filter", "") or "").lower()
        return [f for f in available_fields(data) if term in f.lower()], coverage
    received = row_count(data)
    if received is not None:
        coverage.setdefault("received", received)
    start = getattr(args, "row_start", 0) or 0
    if start and received is not None:
        if start >= received:
            raise InputError(f"--start {start} is past the {received} rows this observation holds; its last row is at {received - 1}.")
        data = dict(data, data=data["data"][start:], index=data["index"][start:]) if is_table(data) else data[start:]
        coverage["start"] = start

    requested = getattr(args, "fields", None)
    fields = requested or (list(item.fields) if item and item.fields else None)
    if fields:
        # 성진: 값이 전부 결측이어도 열 이름은 있다. 비었다고 투영을 건너뛰면 --fields가 조용히 무시되고
        # 요청하지 않은 열이 함께 돌아온다 — 선택이 적용됐다고 읽을 근거는 그대로 둔 채.
        offered = available_fields(data)
        if offered:
            if not requested:
                fields = [f for f in fields if f in offered]  # a default projection describes the common shape, not this target's exact one
            if fields:
                data = project(data, fields)
                coverage["fields"] = {"received": len(offered), "shown": len(fields), "source": "requested" if requested else "leaf_default"}
        elif requested:
            coverage["unverified_fields"] = requested  # nothing came back at all, so the names could not be checked against a real shape

    explicit = getattr(args, "limit", None)
    limit = keep if keep is not None else explicit if explicit is not None else (item.limit if item else None)
    # 성진: read는 관측을 앞에서부터 걸어 나가므로 창이 앞으로 간다. recent를 여기서도 적용하면 --start를 올려도 매번
    # 같은 꼬리가 나오고, 호출 수만 늘어난 채 앞쪽 행에는 영원히 닿지 못한다 — 합계만 보면 완독한 것처럼 보인다.
    paging = hasattr(args, "row_start")
    data, side = take_rows(data, limit, bool(item and item.recent) and not paging)
    if side:
        coverage["kept"] = "window" if paging else side
        coverage["truncated_by"] = "budget" if keep is not None else "explicit_limit" if explicit is not None else "leaf_default"
    shown = row_count(data)
    if shown is not None:
        coverage["shown"] = shown
        coverage["exhaustive"] = shown == coverage.get("received")
    return data, coverage


# ---- conditions --------------------------------------------------------------------------------------------------


def condition(requested, status="unverified", evidence=None):
    """What a condition actually did to this response. A 200 with rows is not evidence that a filter was applied."""
    return {"requested": requested, "status": status, "evidence": evidence}


def column(data, name):
    if not is_table(data):
        return []
    if name == "index":
        return list(data["index"])
    by_name = {str(c): i for i, c in enumerate(data["columns"])}
    return [row[by_name[name]] for row in data["data"]] if name in by_name else []


def within_dates(data, field, start, end):
    """Confirm a date range from the rows themselves: every row inside it confirms, any row outside contradicts."""
    values = [str(v)[:10] for v in column(data, field) if v is not None]
    if not values:
        return None
    outside = [v for v in values if (start and v < start) or (end and v > end)]
    return condition({"start": start, "end": end}, "not_applied" if outside else "confirmed",
                     {"field": field, "rows": len(values), "range": [min(values), max(values)], "outside": outside[:3]})


def monotonic(data, field, ascending):
    values = [v for v in column(data, field) if isinstance(v, (int, float))]
    if len(values) < 2:
        return None
    ordered = all(a <= b for a, b in zip(values, values[1:])) if ascending else all(a >= b for a, b in zip(values, values[1:]))
    return condition({"sort": field, "ascending": ascending}, "confirmed" if ordered else "not_applied",
                     {"field": field, "first": values[0], "last": values[-1], "rows": len(values)})


# ---- result envelope ---------------------------------------------------------------------------------------------

ORDER = ("target", "id", "observed_at", "source_time", "stored_age_seconds", "status", "context", "conditions", "coverage", "continuation", "data", "warnings", "error")


def as_time(value):
    """The source's own timestamp, in the same ISO form as every other time in the envelope.

    Yahoo supplies it as a Unix epoch in some payloads; printing that next to an ISO observed_at invites the reader to
    treat the two as incomparable, which is the opposite of the point of carrying both.
    """
    if isinstance(value, (int, float)) and value > 0:
        return dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat()
    return value


def result(target, data=None, context=None, warnings=None, error=None, status=None, conditions=None, coverage=None, ident=None, observed_at=None, source_time=None, extra=None):
    """One target's answer. Only observations go in: an argument echoed back as though it were a measurement is a
    claim the CLI cannot support, and the request is already stated once at the document level."""
    if status is None:
        status = "error" if error else "empty" if is_empty(data) else "ok"
    notices = list(warnings or [])
    if status == "empty":
        notices.append("An empty upstream return does not prove that the data does not exist.")
    envelope = {"target": target, "id": ident, "observed_at": observed_at or now(), "source_time": as_time(source_time),
                "status": status, "context": {k: v for k, v in (context or {}).items() if k != "rate_limited"},
                "conditions": conditions or {}, "coverage": coverage or {},
                "data": data, "warnings": notices, "error": error}
    envelope.update(extra or {})
    return {k: v for k, v in envelope.items() if k in ("data", "status", "target") or v not in (None, {}, [])} | ({"data": data} if status != "error" else {})


def error_info(code, message, fix):
    return {"code": code, "message": str(message), "fix": fix}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def ordered(envelope):
    return {k: envelope[k] for k in ORDER if k in envelope} | {k: v for k, v in envelope.items() if k not in ORDER}
