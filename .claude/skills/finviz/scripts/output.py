"""Result envelopes, local selection (--fields/--filter/--limit), size limits, statuses and exit codes."""

import json
import sys

from transport import Failure, now

INPUT_CODES = {"export_exists", "missing_curl", "redirect_limit"}
DIAGNOSTIC_DATA = {"array_alignment"}  # the refused payload is the diagnosis here: the arrays that did not line up
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
    "source": "url, requested_url, http_status and redirects; response headers stay in the store: read ID --pointer /source/headers",
    "conditions": "only the parameters you chose: {requested, status: confirmed|not_applied|unverified, evidence}; HTTP 200 alone never confirms a condition",
    "coverage": "received = items extracted from this response, shown = items after local selection, source_total = provider claim; exhaustive is false because remote lists change between pages",
    "continuation": "arguments that fetch the next page of the same query; absent when none was found, which does not prove completeness",
    "sort_keys": "column label -> the sort key --sort accepts for it, read from this page's own header links; write -key for descending. Columns the source does not sort are absent",
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


def searchable(record):
    """The text --filter matches: a record's own values and scalar lists, not the objects nested inside it."""
    if isinstance(record, dict):
        parts = []
        for value in record.values():
            if isinstance(value, list):
                parts += [str(v) for v in value if not isinstance(v, (list, dict))]
            elif not isinstance(value, dict):
                parts.append(str(value))
        return " ".join(parts).lower()
    return json.dumps(record, ensure_ascii=False).lower()


def select_records(records, args, leaf):
    """Apply --filter, --fields and --limit to a record list; returns the kept records and the count before selection."""
    total = len(records)
    fields = [f.strip() for f in args.fields.split(",")] if args.fields else None
    if args.filter:
        term = args.filter.lower()
        records = [r for r in records if term in searchable(r)]
    if fields and records and all(isinstance(r, dict) for r in records):
        known = list(dict.fromkeys(k for r in records for k in r))
        missing = [f for f in fields if f not in known]
        if missing:
            raise Failure("invalid_fields", "Unknown fields " + ", ".join(missing) + ".", "Available fields: " + ", ".join(known) + ".")
        keep = fields + (["observation_id"] if "observation_id" in known and "observation_id" not in fields else [])
        records = [{f: r.get(f) for f in keep} for r in records]
    limit = leaf.default_limit if args.limit is None else args.limit
    if limit is not None:
        records = records[-limit:] if leaf.recent and limit else records[:limit]
    return records, total


def project(value, fields, key):
    """--fields inside one mapping value; a value that is not a record has no fields to keep."""
    if not isinstance(value, dict):
        raise Failure("invalid_fields", "The entry " + key + " is not a record, so it has no fields.", "Select entries with --keys, or drop --fields.")
    missing = [f for f in fields if f not in value]
    if missing:
        raise Failure("invalid_fields", "Unknown fields " + ", ".join(missing) + " in " + key + ".", "Available fields: " + ", ".join(value) + ".")
    return {f: value[f] for f in fields}


def select(result, args, leaf):
    """Apply selection to the leaf's record list (or --fields to a dict's keys) and record shown counts."""
    data = result.get("data")
    records = records_at(data, leaf.records)
    fields = [f.strip() for f in args.fields.split(",")] if args.fields else None
    if isinstance(records, list):
        records, total = select_records(records, args, leaf)
        if leaf.records is None:
            result["data"] = records
        else:
            result["data"] = dict(data, **{leaf.records: records})
        coverage = result["coverage"] = result.get("coverage") or {}
        coverage.setdefault("received", total)
        coverage["shown"] = len(records)
        coverage.setdefault("exhaustive", False)
    elif (leaf.keyed or leaf.records) and isinstance(records, dict):
        keys = [k.strip() for k in args.keys.split(",")] if getattr(args, "keys", None) else list(records)
        missing = [k for k in keys if k not in records]
        if missing:
            raise Failure("invalid_keys", "Unknown keys " + ", ".join(missing) + ".", "Available keys: " + ", ".join(list(records)[:60]) + ("..." if len(records) > 60 else "") + ".")
        if args.filter:
            keys = [k for k in keys if args.filter.lower() in k.lower() or args.filter.lower() in searchable(records[k])]
        limit = leaf.default_limit if args.limit is None else args.limit
        selected = {k: records[k] for k in keys[:limit]}
        if fields:
            selected = {k: project(value, fields, k) for k, value in selected.items()}
        result["data"] = dict(data, **{leaf.records: selected}) if leaf.records else selected
        result["coverage"] = dict(result.get("coverage") or {}, received=len(records), shown=len(selected), exhaustive=False)
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
            if not result.pop("selection_applied", False):
                select(result, args, leaf)
        except Failure as exc:
            result["status"], result["error"] = "error", exc.info()
        else:
            records = records_at(result.get("data"), leaf.records)
            if (is_empty(result.get("data")) or (leaf.records and isinstance(records, (list, dict)) and not records)) and result["status"] != "partial":
                result["status"] = "empty"
                result.setdefault("warnings", []).append("The source returned no usable items; this is not proof that the data does not exist.")
    if result["status"] == "error" and result.get("error", {}).get("code") not in DIAGNOSTIC_DATA:
        # 성진: 오류 결과가 만들지 못했다고 말한 페이로드를 실으면 그 문서가 예산을 넘어 진단이 too_large에 가려진다. array_alignment만 원본 배열을 진단용으로 남긴다.
        result.pop("data", None)
    ordered = ["target", "request", "id", "observed_at", "source", "conditions", "coverage", "continuation", "sort_keys", "selection", "status", "data", "warnings", "error"]
    return {k: result[k] for k in ordered if k in result and result[k] not in (None, {}, [])} | ({"data": result.get("data")} if result["status"] != "error" else {})


def too_large_fix(results, leaf, size, max_chars):
    raw = next((r["selection"] for r in results if isinstance(r.get("selection"), dict) and r["selection"].get("pointer") == "/raw"), None)
    if raw and raw.get("shown"):
        # 성진: 창 크기는 이 문서가 실제로 보인 팽창비(JSON 이스케이프 포함)에서 계산한다; 원자료 문자 수를 그대로 쓰면 다시 넘는다.
        window = max(int(raw["shown"] * max_chars * 0.9 / size), 1)
        return "Result needs " + str(size) + " characters; limit is " + str(max_chars) + ". The raw text is " + str(raw["received"]) + " characters: read it in windows with --chars " + str(raw["start"]) + "-" + str(raw["start"] + window) + " and follow the continuation each window names."
    narrow = ", ".join(leaf.narrow) if leaf.narrow else "--fields or --limit"
    ids = [r["id"] for r in results if r.get("id")]
    pointer = "/data" + ("/" + leaf.records if leaf.records else "")
    shown = next((r["coverage"]["shown"] for r in results if isinstance(r.get("coverage"), dict) and r["coverage"].get("shown")), None)
    # 성진: 절 이름만 주면 그중 하나가 혼자 예산을 넘는 경우 다시 실패한다; 크기를 함께 줘야 모델이 맞는 절을 한 번에 고른다.
    sections = next((r["data"] for r in results if isinstance(r.get("data"), dict) and not leaf.records and not leaf.keyed), None)
    # 성진: 한 슬라이스에 몇 개가 들어가는지는 이 문서가 실제로 낸 크기에서 계산한다; 상수 20은 스무 개가 넘친 경우에 회복이 아니다.
    fits = max(1, int(shown * max_chars * 0.8 / size)) if shown else 20
    if len(results) > 1:
        # 성진: 목표가 여럿이면 첫 id만 주는 회복은 비교를 한 종목으로 바꾼다; 전부 이름 붙이고 목표를 줄이는 길도 함께 말한다.
        saved = " Each target was saved separately: " + ", ".join(str(r.get("target")) + " " + r["id"] for r in results if r.get("id")) + "; read one with read ID --pointer " + pointer + ", or ask for fewer targets in one call."
    else:
        if sections:  # a section-shaped result is not narrowed by counting its sections: point at the biggest one and size the slice from it
            widest = max(sections, key=lambda k: len(json.dumps(sections[k], ensure_ascii=False)))
            inside, span = sections[widest], len(json.dumps(sections[widest], ensure_ascii=False, separators=(",", ":")))
            pointer, fits = pointer + "/" + widest, max(1, int(len(inside) * max_chars * 0.8 / span)) if isinstance(inside, (list, dict)) and inside else fits
        saved = " The response is saved: read " + ids[0] + " --pointer " + pointer + " --start 0 --limit " + str(fits) + " reads it in slices without a new request" + (", and one entry may still be too large, in which case read it with --raw --chars" if fits == 1 else "") + "." if ids else ""
    named = " Sections --fields can keep, with their sizes: " + ", ".join(k + " " + str(len(json.dumps(v, ensure_ascii=False, separators=(",", ":")))) for k, v in list(sections.items())[:25]) + "." if sections else ""
    return "Result needs " + str(size) + " characters; limit is " + str(max_chars) + ". Narrow with " + narrow + "." + named + saved + " Or rerun with --max-chars " + str(size) + "."


def too_large_document(results, error, max_chars):
    """The replacement for an oversized result is itself bounded: one recovery sentence for the call, and every target still addressable by its saved id."""
    rest = error_info(error["code"], error["message"], "Recover with the fix on the first result; this target's own response is saved under the id here.")
    rows = [{"target": r.get("target"), "id": r.get("id"), "status": "error", "error": error if index == 0 else rest} for index, r in enumerate(results)]
    trimmed = [row if index == 0 else {k: v for k, v in row.items() if k != "error"} for index, row in enumerate(rows)]
    dropped = dict(rows[0], error=error_info(error["code"], error["message"], error["fix"] + " " + str(len(results) - 1) + " further targets were saved but do not fit this document; ask for them in smaller groups."))
    # 성진: 예산은 목표마다 반복되는 문장을 묶는 데 쓰고, 회복 문장 자체는 마지막까지 버리지 않는다 — 그것을 버리면 경계는 지켜도 복구가 불가능해진다.
    for attempt in (rows, trimmed, [dropped] if len(results) > 1 else []):
        text = json.dumps({"status": "error", "results": attempt}, ensure_ascii=False, separators=(",", ":"))
        if attempt and len(text) <= max_chars:
            return text
    return json.dumps({"status": "error", "results": [rows[0]] if len(results) == 1 else [dropped]}, ensure_ascii=False, separators=(",", ":"))


def emit(results, args, leaf):
    statuses = {r["status"] for r in results}
    status = "error" if statuses == {"error"} else next(iter(statuses)) if len(statuses) == 1 else "partial"
    doc = {"status": status, "results": results}
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    if len(text) > args.max_chars:
        error = error_info("too_large", "Output exceeds --max-chars.", too_large_fix(results, leaf, len(text), args.max_chars))
        print(too_large_document(results, error, args.max_chars))
        return EXIT_CODES["too_large"]
    print(text)
    if status in ("ok", "empty", "partial"):
        return EXIT_CODES[status]
    codes = {r["error"]["code"] for r in results if r.get("error")}
    if codes & {"access_restricted"}:
        return EXIT_CODES["access_restricted"]
    if any(c.startswith(("invalid", "unknown", "unsupported")) or c in INPUT_CODES for c in codes):
        return EXIT_CODES["invalid"]
    return EXIT_CODES["upstream"]


def diagnostic(message):
    print(message, file=sys.stderr)
