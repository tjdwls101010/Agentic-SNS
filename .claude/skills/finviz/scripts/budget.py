"""Fitting a document to --max-chars: the largest window that fits, too_large only when not one record does, and error documents that stay inside the budget themselves."""

import re

from contract import EXIT_CODES
from selection import continuation, dumps, read_command, render

INPUT_CODES = {"export_exists", "missing_curl", "redirect_limit"}


def document(views, cap):
    results = [render(v, cap) for v in views]
    doc = {"status": overall(results), "results": results}
    found = continuation(views, cap)
    if found:
        doc["continuation"] = found[0] if len(found) == 1 else found
    return doc


def overall(results):
    statuses = [r["status"] for r in results]
    if all(s == "error" for s in statuses):
        return "error"
    if any(s in ("error", "partial") for s in statuses):
        return "partial"
    if all(s == "empty" for s in statuses):
        return "empty"
    return "ok"


def fit(views, max_chars):
    """The text to print: every requested record if it fits, else the largest equal count per collection that does, else a bounded too_large document."""
    upper = max((v.upper for v in views), default=0)
    text = dumps(document(views, upper))
    if len(text) <= max_chars:
        return text
    # 성진: 모든 목표·절에 같은 상한 하나를 이진 탐색한다. 한 절의 첫 레코드가 혼자 넘치면 다른 절도 0이 되어 too_large가 된다; 절마다 따로 상한을 찾을 필요가 실측되면 절별 탐색으로 바꾼다.
    low, high = 0, upper - 1  # upper itself did not fit
    best = None
    while low <= high:
        middle = (low + high) // 2
        candidate = dumps(document(views, middle))
        if len(candidate) <= max_chars:
            best, low = candidate, middle + 1
        else:
            high = middle - 1
    if best is not None and low - 1 > 0:
        return best
    base = len(dumps(document(views, 0)))
    return bounded([render(v, 0) if v.result.get("status") == "error" else too_large(v, len(text), max_chars, base) for v in views], max_chars)


def too_large(view, size, max_chars, base):
    """The recovery when not one record fits: project fewer fields of the same selection, or read the raw response, which windows itself."""
    result = {"target": view.result.get("target"), "id": view.result.get("id"), "status": "error"}
    ident = view.result.get("id")
    head = "The result needs " + str(size) + " characters even at its smallest; --max-chars is " + str(max_chars) + "."
    section = next((name for name, p in view.picked.items() if p.records), None)
    if ident and section and view.picked[section].records and isinstance(view.picked[section].records[0], dict):
        record = view.picked[section].records[0]
        smallest, room = [], max_chars - base - 300  # 300: the continuation line and separators a shown record brings
        for field in sorted(record, key=lambda f: len(dumps({f: record[f]}))) if isinstance(record, dict) else []:
            if len(dumps({f: record[f] for f in smallest + [field]})) > room:
                break
            smallest.append(field)
        sel = view.sel.__class__(**dict(vars(view.sel), fields=",".join(smallest), start=0, limit=None)) if smallest else view.sel
        projected = read_command([ident], view.item, sel, section, view.picked[section].start, view.picked[section].bound, view.ops)
        fix = ("One " + section + " record alone does not fit. Project it: " + projected + " (fields: " + ", ".join(list(record)[:40]) + "), or read the raw response in windows: read " + ident + " --raw.") if smallest else ("One " + section + " record alone does not fit, and no field of it fits either. Read the raw response in windows: read " + ident + " --raw.")
    elif ident:
        fix = "The context alone does not fit. Read the raw response in windows: read " + ident + " --raw."
    else:
        fix = "Raise --max-chars; this result has no saved observation to read in parts."
    result["error"] = {"code": "too_large", "message": head, "fix": fix}
    return result


def bounded(results, max_chars):
    """The replacement document obeys the budget it reports on: repeated sentences are dropped first, the first fix and the saved ids last."""
    rest = [dict({k: v for k, v in r.items() if k != "error"}) for r in results[1:]]
    ladder = [results, results[:1] + rest, results[:1]]
    for attempt in ladder:
        text = dumps({"status": "error", "results": attempt})
        if len(text) <= max_chars:
            return text
    first = results[0]
    ident = first.get("id")
    shorter = dict(first, error=dict(first["error"], message=first["error"]["message"][:80]))
    smallest = {k: v for k, v in {"id": ident, "status": "error", "error": {"code": first["error"]["code"], "message": "Over --max-chars.", "fix": ("read " + ident + " --raw") if ident else "Raise --max-chars."}}.items() if v is not None}
    for attempt in ([shorter], [smallest]):
        text = dumps({"status": "error", "results": attempt})
        if len(text) <= max_chars:
            return text
    return text  # below this a document cannot both parse and say what went wrong


def exit_code(text):
    status = re.search(r'^\{"status":"(\w+)"', text)
    status = status[1] if status else "error"
    if status in ("ok", "empty", "partial"):
        return EXIT_CODES[status]
    codes = set(re.findall(r'"code":"(\w+)"', text))
    if "too_large" in codes:
        return EXIT_CODES["too_large"]
    if "access_restricted" in codes:
        return EXIT_CODES["access_restricted"]
    if any(c.startswith(("invalid", "unknown", "unsupported")) or c in INPUT_CODES for c in codes):
        return EXIT_CODES["invalid"]
    return EXIT_CODES["upstream"]
