"""Result envelopes, local selection (--fields/--filter/--limit), size limits, statuses and exit codes."""

import json
import sys

from transport import Failure, now

EXIT_CODES = {"ok": 0, "invalid": 2, "access_restricted": 5, "upstream": 6, "empty": 7, "partial": 8, "too_large": 9}
STATUSES = {
    "ok": "usable data was extracted",
    "empty": "the source answered but returned no usable items; not proof that the data does not exist",
    "partial": "usable data with a recorded gap, or a mix of successful and failed targets",
    "error": "no usable requested result; error.code and error.fix say what to do",
}
ENVELOPE = {
    "target": "the ticker, query or identifier this result answers",
    "request": "the arguments the command actually used, after defaults",
    "id": "saved observation ID for read/inspect; every fetched response is saved even when extraction fails",
    "observed_at": "UTC time this CLI received the response; not a market or reporting time",
    "source": "url, requested_url, http_status and redirects; response headers stay in the store (read ID --raw)",
    "conditions": "only the parameters you chose: {requested, status: confirmed|not_applied|unverified, evidence}; HTTP 200 alone never confirms a condition",
    "coverage": "received = items extracted from this response, shown = items after local selection, source_total = provider claim; exhaustive is false because remote lists change between pages",
    "continuation": "arguments that fetch the next page of the same query; absent when none was found, which does not prove completeness",
    "data": "the command's documented shape; source strings keep their units and signs, JSON API values are native, missing values are null",
    "warnings": "limitations that affect how the data can be used",
    "error": "{code, message, fix}",
}


def error_info(code, message, fix):
    return {"code": code, "message": str(message), "fix": fix}


def plain(target, data=None):
    return {"target": target, "id": None, "observed_at": now(), "status": "ok", "data": data}


def is_empty(data):
    if isinstance(data, dict):
        return not data or all(is_empty(v) for v in data.values())
    if isinstance(data, list):
        return not data
    return data is None or data == ""


def records_at(data, location):
    if location is None:
        return data
    return data.get(location) if isinstance(data, dict) else None


def select(result, args, leaf):
    """Apply --filter, --fields and --limit to the leaf's record list (or to a dict's keys) and record shown counts."""
    data = result.get("data")
    records = records_at(data, leaf.records)
    fields = [f.strip() for f in args.fields.split(",")] if args.fields else None
    if isinstance(records, list):
        total = len(records)
        if args.filter:
            term = args.filter.lower()
            records = [r for r in records if term in json.dumps(r, ensure_ascii=False).lower()]
        if fields and records and all(isinstance(r, dict) for r in records):
            known = list(dict.fromkeys(k for r in records for k in r))
            missing = [f for f in fields if f not in known]
            if missing:
                raise Failure("invalid_fields", "Unknown fields " + ", ".join(missing) + ".", "Available fields: " + ", ".join(known) + ".")
            records = [{f: r.get(f) for f in fields} for r in records]
        if args.limit is not None:
            records = records[: args.limit]
        if leaf.records is None:
            result["data"] = records
        else:
            result["data"] = dict(data, **{leaf.records: records})
        coverage = result["coverage"] = result.get("coverage") or {}
        coverage.setdefault("received", total)
        coverage["shown"] = len(records)
        coverage.setdefault("exhaustive", False)
    elif isinstance(data, dict) and fields:
        missing = [f for f in fields if f not in data]
        if missing:
            raise Failure("invalid_fields", "Unknown fields " + ", ".join(missing) + ".", "Available fields: " + ", ".join(data) + ".")
        result["data"] = {f: data[f] for f in fields}
    return result


def finalize(result, args, leaf, request):
    """Strip store-only material, apply selection, and settle the status of one result."""
    result = dict(result)
    result["request"] = {k: v for k, v in request.items() if v is not None}
    if result.get("source"):
        result["source"] = {k: v for k, v in result["source"].items() if k != "headers" and v not in (None, [], False)}
    if result["status"] != "error":
        try:
            select(result, args, leaf)
        except Failure as exc:
            result["status"], result["error"] = "error", exc.info()
        else:
            if is_empty(result.get("data")):
                result["status"] = "empty"
                result.setdefault("warnings", []).append("The source returned no usable items; this is not proof that the data does not exist.")
    ordered = ["target", "request", "id", "observed_at", "source", "conditions", "coverage", "continuation", "selection", "status", "data", "warnings", "error"]
    return {k: result[k] for k in ordered if k in result and result[k] not in (None, {}, [])} | ({"data": result.get("data")} if result["status"] != "error" else {})


def too_large_fix(results, leaf, size, max_chars):
    narrow = ", ".join(leaf.narrow) if leaf.narrow else "--fields or --limit"
    ids = [r["id"] for r in results if r.get("id")]
    saved = " The response is saved: read " + ids[0] + " --pointer /data --start 0 --limit 20 reads it in slices without a new request." if ids else ""
    return "Result needs " + str(size) + " characters; limit is " + str(max_chars) + ". Narrow with " + narrow + "." + saved + " Or rerun with --max-chars " + str(size) + "."


def emit(results, args, leaf):
    statuses = {r["status"] for r in results}
    status = "error" if statuses == {"error"} else next(iter(statuses)) if len(statuses) == 1 else "partial"
    doc = {"status": status, "results": results}
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    if len(text) > args.max_chars:
        error = error_info("too_large", "Output exceeds --max-chars.", too_large_fix(results, leaf, len(text), args.max_chars))
        doc = {"status": "error", "results": [{"target": r.get("target"), "id": r.get("id"), "status": "error", "error": error} for r in results]}
        print(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
        return EXIT_CODES["too_large"]
    print(text)
    if status in ("ok", "empty", "partial"):
        return EXIT_CODES[status]
    codes = {r["error"]["code"] for r in results if r.get("error")}
    if codes & {"access_restricted"}:
        return EXIT_CODES["access_restricted"]
    if any(c.startswith("invalid") or c in ("unknown_id", "unsupported_url", "unsupported_route") for c in codes):
        return EXIT_CODES["invalid"]
    return EXIT_CODES["upstream"]


def diagnostic(message):
    print(message, file=sys.stderr)
