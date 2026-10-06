"""The receipt every command prints: its failure codes and exit codes, the document's status, and how it is cut to fit --max-chars.

The receipt is the cheap signal in front of a file the caller pays to read, so what changes the meaning of a result (status, warnings, the path to the full receipt) is never cut, and the costly detail goes first.
"""
import copy
import json


class Failure(Exception):
    """A target, or the whole call, failed for the reason `code` names; `fix` says what to do instead."""

    code = "upstream"

    def __init__(self, message, fix=None, code=None):
        super().__init__(message)
        self.fix = fix
        if code:
            self.code = code


class Invalid(Failure):
    """An argument the caller has to change, refused before anything is paid for."""

    code = "invalid"


class LocalIO(Failure):
    """A local file could not be written or read: a fault in this machine's path, not in the request."""

    code = "local_io"


# Every exit code a command can end with, in the order --help prints them.
EXIT_CODES = {
    "ok": (0, "every target returned data"),
    "invalid": (2, "an argument was refused before any request; nothing was saved"),
    "local_io": (4, "the result could not be saved under the skill's data folder"),
    "rate_limited": (5, "Yahoo limited requests and no target returned data; the rest were not attempted"),
    "upstream": (6, "every target failed at the source (not_found, no_data, not_applicable, source_constraint, upstream)"),
    "empty": (7, "every target answered with nothing usable, which does not prove the data does not exist"),
    "partial": (8, "some targets returned data and others are empty, failed or not attempted"),
}
# A document with no usable target exits with its most actionable failure; every other code exits as upstream.
PRIORITY = ("rate_limited", "invalid", "local_io")
STATUSES = ("ok", "empty", "error", "not_attempted")
# Every error code a target can carry; the receipt that cannot be cut is sized with the longest.
ERROR_CODES = ("not_found", "no_data", "not_applicable", "source_constraint", "rate_limited", "upstream", "invalid", "local_io", "not_attempted", "unsupported")

DOCUMENT_ORDER = ("status", "command", "receipt_path", "file", "units", "warnings", "notes", "results", "trimmed", "projected", "over_budget")
TARGET_ORDER = ("target", "status", "rows", "warnings", "observed_at", "as_of", "currency", "financial_currency", "coverage", "conditions",
                "data", "first", "last", "error")
# Cut first when the receipt does not fit: the inline rows, then their preview, then explanations, then the units map, then the
# per-target detail. Status, warnings, targets and receipt_path stay; receipt.json keeps everything that was cut.
DETAIL = ("observed_at", "as_of", "currency", "financial_currency", "coverage", "conditions")


FIXES = {"invalid": "Correct the argument; `COMMAND --help` states each argument, its choices and its default.",
         "upstream": "Retry later; if it fails again, confirm the symbol with `search` and the arguments with `COMMAND --help`."}


def failure(code, message, fix):
    return {"code": code, "message": str(message), "fix": fix or FIXES.get(code, FIXES["upstream"])}


def document_status(statuses):
    """The document's status from its targets' statuses."""
    if statuses and all(s == "ok" for s in statuses):
        return "ok"
    if "ok" in statuses:
        return "partial"
    if statuses and all(s == "empty" for s in statuses):
        return "empty"
    return "error"


def exit_code(document):
    status = document["status"]
    if status in ("ok", "partial", "empty"):
        return EXIT_CODES[status][0]
    codes = [(r.get("error") or {}).get("code") for r in document.get("results", [])]
    if codes and all(c == "unsupported" for c in codes):
        return EXIT_CODES["empty"][0]
    for code in PRIORITY:
        if code in codes:
            return EXIT_CODES[code][0]
    return EXIT_CODES["upstream"][0]


def ordered(mapping, order):
    return {k: mapping[k] for k in order if k in mapping} | {k: v for k, v in mapping.items() if k not in order}


def size(document):
    return len(dump(document))


def dump(document):
    return json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def codes(warnings):
    """Warning codes from {code, text} entries or bare codes."""
    return [w["code"] if isinstance(w, dict) else w for w in warnings or []]


def minimal(document):
    """The part no budget removes: the status, the path to the full receipt, every warning code and each target's status."""
    found = {"status": document["status"], "command": document.get("command")}
    if document.get("receipt_path"):
        found["receipt_path"] = document["receipt_path"]
    found["warnings"] = codes(document.get("warnings"))
    found["results"] = [ordered({"target": r.get("target"), "status": r.get("status"), "warnings": codes(r.get("warnings")),
                                 **({"error": {"code": r["error"]["code"]}} if r.get("error") else {})}, TARGET_ORDER)
                        for r in document.get("results", [])]
    found["trimmed"] = True
    return found


def reductions(document, preview):
    """Each step cuts more than the last; `preview(i)` is the i-th target's (first, last) rows, or None."""
    def no_data(doc):
        for i, r in enumerate(doc["results"]):
            if "data" in r:
                r.pop("data")
                ends = preview(i)
                if ends:
                    r["first"], r["last"] = ends
        return doc

    def no_preview(doc):
        for r in doc["results"]:
            r.pop("first", None)
            r.pop("last", None)
        return doc

    def no_notes(doc):
        doc.pop("notes", None)
        return doc

    def no_units(doc):
        doc.pop("units", None)
        return doc

    def no_detail(doc):
        for r in doc["results"]:
            for key in DETAIL:
                r.pop(key, None)
            if r.get("error"):
                r["error"] = {"code": r["error"]["code"]}
        doc["warnings"] = codes(doc.get("warnings"))
        return doc

    return [no_data, no_preview, no_notes, no_units, no_detail]


def fit(document, max_chars, preview=lambda i: None):
    """The document as printed: whole if it fits, else cut step by step, else the minimal receipt, marked over_budget when even that does not fit.

    Keeping every warning code is worth more than the limit: a receipt that fits by dropping "last bar provisional" answers a different question.
    """
    if size(document) <= max_chars:
        return document
    current = copy.deepcopy(document)
    for step in reductions(document, preview):
        current = step(current)
        current["trimmed"] = True
        current = ordered(current, DOCUMENT_ORDER)
        if size(current) <= max_chars:
            return current
    found = minimal(document)
    if size(found) > max_chars:
        found["over_budget"] = True
    return ordered(found, DOCUMENT_ORDER)


def precheck(command, targets, warning_codes, receipt_path, max_chars):
    """Refuse before any request a --max-chars too small for the receipt that cannot be cut: every warning this command can raise, for every target."""
    longest = max(ERROR_CODES, key=len)
    sample = {"status": "partial", "command": command, "receipt_path": receipt_path, "warnings": list(warning_codes),
              "results": [{"target": t, "status": "not_attempted", "warnings": list(warning_codes), "error": {"code": longest}} for t in targets],
              "trimmed": True}
    needed = size(sample)
    if needed > max_chars:
        raise Invalid(f"--max-chars {max_chars} is smaller than the shortest receipt this call can print ({needed} characters)",
                      fix=f"Raise --max-chars to at least {needed}, or ask for fewer targets.")


def invalid(command, exc):
    """The document for a call refused before anything ran: nothing was saved, so it names no receipt."""
    fix = getattr(exc, "fix", None) or "Correct the argument; `COMMAND --help` states each argument, its choices and its default."
    return {"status": "error", "command": command,
            "results": [{"target": "arguments", "status": "error", "error": failure("invalid", exc, fix)}]}
