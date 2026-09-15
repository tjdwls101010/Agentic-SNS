"""Lossless table encoding and the CLI result contract."""
from collections.abc import KeysView
import datetime as dt
import json
import math

import numpy as np
import pandas as pd


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


def is_empty(data):
    if isinstance(data, (pd.DataFrame, pd.Series)):
        return data.empty or bool(data.isna().all(axis=None))
    if isinstance(data, dict):
        return not data or all(is_empty(value) for value in data.values())
    if isinstance(data, (list, tuple)):
        return not data or all(is_empty(value) for value in data)
    return data is None or data is pd.NA or data is pd.NaT or isinstance(data, (float, np.floating)) and not math.isfinite(data)


def result(target, data=None, context=None, warnings=None, error=None, status=None):
    if status is None:
        empty = is_empty(data)
        status = "error" if error else "empty" if empty else "ok"
    notices = list(warnings or [])
    if status == "empty":
        notices.append("An empty upstream return does not prove that the data does not exist.")
    return {"target": target, "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(), "status": status, "data": encode(data), "context": encode(context or {}), "warnings": notices, "error": error}


def error_info(code, message, fix):
    return {"code": code, "message": str(message), "fix": fix}


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def emit(results, max_chars=20000, request=None):
    """One request applies to every result, so it is stated once at the document level."""
    states = {r["status"] for r in results}
    status = "error" if states <= {"error", "not_attempted"} else next(iter(states)) if len(states) == 1 else "partial"
    text = dump({"status": status, "request": request, "results": results})
    if len(text) > max_chars:
        data_chars = sum(len(dump(r["data"])) for r in results)
        if len(results) > 1 and data_chars * 2 < len(text):
            fix = f"{len(results)} targets need {len(text)} characters but their data is only {data_chars}; per-target context dominates. Rerun with --max-chars {len(text)} or split the targets into smaller batches; narrowing --fields or --limit cannot recover this much."
        else:
            fix = f"Narrow --fields (discover with --list-fields --filter TEXT), --limit, --periods or --start/--end; scope schema to GROUP LEAF or use --filter TEXT; alternatively rerun with --max-chars {len(text)}."
        print(dump({"status": "error", "request": request, "results": [result("output", error=error_info("too_large", f"Result requires {len(text)} characters; limit is {max_chars}.", fix))]}))
        return 9
    print(text)
    if status == "ok":
        return 0
    if status == "partial":
        return 8
    if status == "empty":
        return 7
    codes = {r["error"]["code"] for r in results if r["error"]}
    return 5 if "rate_limited" in codes else 2 if "invalid" in codes else 6


def select(data, args, context):
    if isinstance(data, pd.Series):
        data = data.to_frame()
    if isinstance(data, pd.DataFrame):
        fields = list(data.columns)
    elif isinstance(data, dict):
        fields = list(data)
    elif isinstance(data, list) and all(isinstance(row, dict) for row in data):
        fields = list(dict.fromkeys(key for row in data for key in row))
    else:
        fields = []
    if getattr(args, "list_fields", False):
        term = getattr(args, "filter", "").lower()
        return [str(f) for f in fields if term in str(f).lower()]
    requested = getattr(args, "fields", None)
    if requested and not fields and is_empty(data):
        context["unverified_fields"] = requested
        return data
    if requested:
        by_name = {str(field): field for field in fields}
        missing = [f for f in requested if f not in by_name]
        if missing:
            raise InputError(f"Unknown fields {missing}; use this command with --list-fields --filter TEXT.")
        requested = [by_name[field] for field in requested]
        if isinstance(data, pd.DataFrame):
            data = data.loc[:, requested]
        elif isinstance(data, dict):
            data = {f: data[f] for f in requested}
        elif isinstance(data, list):
            data = [{f: row.get(f) for f in requested} for row in data]
    limit = getattr(args, "limit", None)
    if isinstance(data, (pd.DataFrame, list, tuple)) and limit is not None:
        context["returned_before_selection"] = len(data)
        data = data.iloc[:limit] if isinstance(data, pd.DataFrame) else data[:limit]
        context["returned"] = len(data)
        context["output_limit"] = limit
    return data
