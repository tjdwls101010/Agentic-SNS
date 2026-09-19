"""Result envelopes, local selection (--fields/--filter/--limit), size limits, statuses and exit codes."""

import json
import re
import sys

from transport import Failure, now

INPUT_CODES = {"export_exists", "missing_curl", "redirect_limit"}
SMALLEST_DOCUMENT = 200  # measured: the shortest JSON document that still carries a code, a message and how to recover is ~155 characters
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
    "source": "url, requested_url, http_status and redirects, each with the id of the response it returned; response headers stay in the store: read ID --pointer /source/headers",
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


def with_records(data, leaf, records):
    return dict(data, **{leaf.records: records}) if leaf.records else records


def select_records(records, args, leaf, data=None):
    """Apply --filter, the leaf's own default range and then --fields and --limit; returns the kept records and the count before any of it.

    The order matters: a default range that ran first would make --filter search the window instead of the response,
    and a question about a record outside it would come back empty from a result that holds it.
    """
    total = len(records)
    fields = [f.strip() for f in args.fields.split(",")] if args.fields else None
    if args.filter:
        term = args.filter.lower()
        records = [r for r in records if term in searchable(r)]
    if leaf.window is not None:
        windowed = leaf.window(with_records(data if data is not None else records, leaf, records), args)
        records = records_at(windowed, leaf.records) if leaf.records else windowed
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


def across_sections(items, keep, field):
    """Keep `keep` records without losing a section: which list a record came from is part of what it means, and the sections are concatenated, not interleaved."""
    if keep is None or len(items) <= keep:
        return items
    sections = {}
    for position, item in enumerate(items):
        sections.setdefault(item.get(field), []).append(position)
    chosen, depth = set(), 0
    while len(chosen) < keep and any(len(positions) > depth for positions in sections.values()):
        for positions in sections.values():
            if depth < len(positions) and len(chosen) < keep:
                chosen.add(positions[depth])
        depth += 1
    return [item for position, item in enumerate(items) if position in chosen]


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
        records, total = select_records(records, args, leaf, data)
        result["data"] = with_records(data, leaf, records)
        coverage = result["coverage"] = result.get("coverage") or {}
        coverage.setdefault("received", total)
        coverage["shown"] = len(records)
        coverage.setdefault("exhaustive", False)
    elif (leaf.keyed or leaf.records) and isinstance(records, dict):
        if leaf.window is not None:
            data = result["data"] = leaf.window(data, args)
            records = records_at(data, leaf.records)
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
    elif isinstance(data, dict) and (fields or getattr(args, "keys", None)):
        chosen = [k.strip() for k in args.keys.split(",")] if getattr(args, "keys", None) else list(data)
        unknown = [k for k in chosen if k not in data]
        if unknown:
            raise Failure("invalid_keys", "Unknown keys " + ", ".join(unknown) + ".", "Available keys: " + ", ".join(list(data)[:60]) + ("..." if len(data) > 60 else "") + ".")
        kept = {k: data[k] for k in chosen}
        if fields:
            missing = [f for f in fields if f not in kept]
            if missing and all(isinstance(v, dict) for v in kept.values()) and kept:
                kept = {k: project(v, fields, k) for k, v in kept.items()}  # a mapping of records: the fields are inside each one
            elif missing:
                raise Failure("invalid_fields", "Unknown fields " + ", ".join(missing) + ".", "Available fields: " + ", ".join(kept) + ".")
            else:
                kept = {f: kept[f] for f in fields}
        result["data"] = kept
    return result


def settle_empty(result, leaf):
    """Decide emptiness from what the source gave, before the observation is stored and before any selection narrows it.

    Doing it only after selection left the store saying "ok" for a response that carried nothing, so a later read of
    that observation reported success. A result the model filtered to nothing is a different thing and stays a
    property of the printed result, not of the observation.
    """
    if result.get("status") != "ok" or result.get("data") is None:
        return result  # a response nothing was extracted from, such as a redirect hop, is not an empty extraction
    records = records_at(result.get("data"), leaf.records)
    if is_empty(result.get("data")) or (leaf.records and isinstance(records, (list, dict)) and not records):
        result["status"] = "empty"
    return result


def finalize(result, args, leaf, request):
    """Strip store-only material, apply selection, and settle the status of one result."""
    result = dict(result)
    result["request"] = {k: v for k, v in request.items() if v is not None}
    if result.get("source"):
        result["source"] = {k: v for k, v in result["source"].items() if k != "headers" and v not in (None, [], False)}
    if result["status"] != "error":
        try:
            if leaf.window and not result.get("selection_applied") and not isinstance(records_at(result.get("data"), leaf.records), list):
                result["data"] = leaf.window(result["data"], args)  # no record list to order against: open's sections, a mapping's fields
            if not result.pop("selection_applied", False):
                select(result, args, leaf)
        except Failure as exc:
            result["status"], result["error"] = "error", exc.info()
        else:
            records = records_at(result.get("data"), leaf.records)
            if (is_empty(result.get("data")) or (leaf.records and isinstance(records, (list, dict)) and not records)) and result["status"] not in ("partial", "empty"):
                result["status"] = "empty"
            if result["status"] == "empty":
                result.setdefault("warnings", []).append("The source returned no usable items; this is not proof that the data does not exist.")
    if result["status"] == "error" and result.get("error", {}).get("code") not in DIAGNOSTIC_DATA:
        # 성진: 오류 결과가 만들지 못했다고 말한 페이로드를 실으면 그 문서가 예산을 넘어 진단이 too_large에 가려진다. array_alignment만 원본 배열을 진단용으로 남긴다.
        result.pop("data", None)
    ordered = ["target", "request", "id", "observed_at", "source", "conditions", "coverage", "continuation", "sort_keys", "selection", "status", "data", "warnings", "error"]
    return {k: result[k] for k in ordered if k in result and result[k] not in (None, {}, [])} | ({"data": result.get("data")} if result["status"] != "error" else {})


def raw_fix(selection, size, max_chars):
    # 성진: 창 크기는 이 문서가 실제로 보인 팽창비(JSON 이스케이프 포함)에서 계산한다; 원자료 문자 수를 그대로 쓰면 다시 넘는다.
    window = max(int((selection.get("shown") or 1) * max_chars * 0.9 / size), 1)
    start = selection.get("start", 0)
    return "Result needs " + str(size) + " characters; limit is " + str(max_chars) + ". The raw text is " + str(selection.get("received")) + " characters: read it in windows with --chars " + str(start) + "-" + str(start + window) + " and follow the continuation each window names."


def too_large_fix(results, leaf, size, max_chars, args=None):
    raw = next((r["selection"] for r in results if isinstance(r.get("selection"), dict) and r["selection"].get("pointer") == "/raw"), None)
    if raw and raw.get("shown"):
        return raw_fix(raw, size, max_chars)
    narrow = ", ".join(leaf.narrow) if leaf.narrow else "--fields or --limit"
    ids = [r["id"] for r in results if r.get("id")]
    pointer = "/data" + ("/" + leaf.records if leaf.records else "")
    if leaf.path == "read":
        # 성진: read의 회복은 지금 읽던 그 포인터의 더 작은 조각이다; 다른 포인터를 권하면 다른 값을 성공적으로 돌려준다.
        selection = next((r["selection"] for r in results if isinstance(r.get("selection"), dict)), {})
        here = selection.get("pointer") or "/data"
        if here == "/raw":
            return raw_fix(selection, size, max_chars)
        shown = selection.get("shown") or 1
        smaller = max(1, int(shown * max_chars * 0.8 / size))
        head = "Result needs " + str(size) + " characters; limit is " + str(max_chars) + ". "
        if smaller >= shown:
            # 성진: 더 줄일 수 없는데 같은 --limit을 다시 권하면 회복이 제자리를 돈다; 한 항목이 예산보다 큰 경우의 길은 원자료 창이다.
            return head + "One entry at " + here + " is already larger than the budget, so read the response text in windows with read " + str(getattr(args, "id", "")) + " --raw --chars 0-" + str(max(1, int(max_chars * 0.8))) + ", or rerun with --max-chars " + str(size) + "."
        kept = ("".join(" --filter " + repr(args.filter) if args.filter else "") + ("".join(" --keys " + args.keys) if getattr(args, "keys", None) else "") + ("".join(" --fields " + args.fields) if args.fields else ""))
        return head + "Read a smaller slice of the same selection: read " + str(getattr(args, "id", "")) + " --pointer " + here + kept + " --start " + str(selection.get("start", 0)) + " --limit " + str(smaller) + ". Or rerun with --max-chars " + str(size) + "."
    if getattr(args, "from_id", None):
        # 성진: --from은 남의 관측을 읽은 것이라 그 id에는 이 절이 없다; 그 id로 읽으라고 하면 다른 절이 성공적으로 나온다.
        return "Result needs " + str(size) + " characters; limit is " + str(max_chars) + ". Narrow with " + narrow + ", or rerun without --from so this section is observed and saved under its own id. Or rerun with --max-chars " + str(size) + "."
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
            inside = sections[widest]
            pointer = pointer + "/" + widest
            if isinstance(inside, dict):
                # a nested object slices by its own top-level keys, which for a tree is just its name: descend to the list inside it
                nested = next((k for k, v in inside.items() if isinstance(v, list) and v), None)
                if nested:
                    pointer, inside = pointer + "/" + nested, inside[nested]
            span = len(json.dumps(inside, ensure_ascii=False, separators=(",", ":")))
            fits = max(1, int(len(inside) * max_chars * 0.8 / span)) if isinstance(inside, (list, dict)) and inside else fits
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
    # 성진: 가장 짧은 형태에도 복구에 필요한 둘은 남긴다 — 저장된 id와 통과할 수 있는 크기.
    size = re.search(r"--max-chars (\d+)", error["fix"])
    ident = results[0].get("id")
    advice = "Rerun with --max-chars " + size[1] + "." if size else "Raise --max-chars."
    smallest = [{k: v for k, v in {"id": ident, "status": "error", "error": error_info(error["code"], error["message"], advice)}.items() if v is not None}]
    for attempt in ([rows[0]] if len(results) == 1 else [dropped], smallest):
        text = json.dumps({"status": "error", "results": attempt}, ensure_ascii=False, separators=(",", ":"))
        if len(text) <= max_chars:
            return text
    return text  # below this a document cannot both parse and say what went wrong


def emit(results, args, leaf):
    statuses = {r["status"] for r in results}
    status = "error" if statuses == {"error"} else next(iter(statuses)) if len(statuses) == 1 else "partial"
    doc = {"status": status, "results": results}
    text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    if len(text) > args.max_chars:
        error = error_info("too_large", "Output exceeds --max-chars.", too_large_fix(results, leaf, len(text), args.max_chars, args))
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
