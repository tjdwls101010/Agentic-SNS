"""The size boundary, and what the CLI says when a result crosses it.

Two rules shape everything here. A recovery sentence is derived from the leaf's own `narrow` declaration, never from a
template, because a template once recommended --fields to a leaf whose payload --fields could not reach and the advice
failed one step later. And a window that the budget imposed is reported as `partial`, not `ok`: a caller who asked for
five years and received one screen has to know which of the two they are holding, or they will describe a window as
the whole answer.
"""

import re
import shlex

from encode import display, dump, is_empty, row_count
from envelope import EXIT_CODES, error_info
from selection import select

MIN_CHARS = 1000


def document(results, status, request):
    return {"status": status, "request": request, "results": results}


def overall(results):
    states = {r["status"] for r in results}
    if states <= {"error", "not_attempted"}:
        return "error"
    return next(iter(states)) if len(states) == 1 else "partial"


def shrink(envelope, item, args, size, max_chars):
    """Re-cut this result's rows to what the budget actually fits, measured from the size this document just reached.

    A constant row count would overflow again on a wide table and waste the budget on a narrow one; the observed
    expansion ratio is the only number that holds for both.
    """
    full = envelope.get("_full")
    shown = (envelope.get("coverage") or {}).get("shown") or row_count(envelope.get("data")) or 0
    if full is None or not shown or not item.sliceable:
        return False
    keep = max(1, int(shown * max_chars * 0.8 / size))
    if keep >= shown:
        keep = max(1, shown - 1)
    data, coverage = select(full, args, item, keep=keep)
    if row_count(data) == shown:
        return False
    envelope["data"], envelope["coverage"] = data, coverage
    envelope["status"] = "partial"
    notice = f"The budget narrowed this result to {coverage.get('shown')} of {coverage.get('received')} rows, so it answers a smaller range than was asked for; the whole observation is saved as id {envelope.get('id')} and read reaches the rest without a new request."
    warnings = [w for w in envelope.get("warnings", []) if not w.startswith("The budget narrowed")]
    envelope["warnings"] = warnings + [notice]
    # 성진: continuation을 축소 전 개수로 계산해 두면 예산이 창을 줄인 만큼의 행을 건너뛴다 — 따라가면 조용히 빠진다.
    # 그리고 잘린 결과는 나머지를 읽는 명령을 스스로 이름 붙여야 한다; id만 주고 명령을 말하지 않으면 회복을 읽는 쪽이 조립하게 된다.
    following = coverage.get("start", 0) + (coverage.get("shown") or 0)
    if envelope.get("id") and following < (coverage.get("received") or 0):
        envelope["continuation"] = {"start": following, "command": read_command(envelope["id"], item, args, coverage.get("shown"), following)}
    else:
        envelope.pop("continuation", None)
    return True


def quoted(args, names):
    parts = []
    for flag, value in names:
        if value:
            parts.append(f" {flag} {shlex.quote(str(value))}")
    return "".join(parts)


def read_command(ident, item, args, keep, start=0):
    """A recovery that reads a saved observation keeps the original selection and the store it was saved in.

    Dropping --store sends the reader to the default cache, where the observation the sentence names does not exist.
    """
    fields = ",".join(args.fields) if getattr(args, "fields", None) else None
    return f"read {ident}" + quoted(args, [("--store", getattr(args, "store", None)), ("--fields", fields)]) + f" --start {start} --limit {keep}"


def narrowings(item, args):
    """The leaf's narrowings minus the ones this call's own mode forbids.

    Some arguments are valid for a leaf but rejected for the way it was invoked — single-symbol calendar earnings
    takes no date range, and a non-quotes search takes no --type. Naming them in a recovery sends the reader into an
    invalid-argument error, so the leaf that rejects them also declares them here.
    """
    forbidden = set(item.forbidden(args)) if item.forbidden else set()
    return [n for n in item.narrow if n not in forbidden]


def too_large_fix(results, item, size, max_chars, args, needed=None):
    """One sentence that names a narrowing this leaf actually has, and a saved id that reaches the rest.

    `size` is what the document being refused measured, which sizes the slice; `needed` is what the whole result would
    take, which is the budget the sentence promises.
    """
    needed = size if needed is None else needed
    head = f"Result needs {needed} characters; limit is {max_chars}. "
    saved = [(r.get("target"), r.get("id")) for r in results if r.get("id")]
    shown = next((r["coverage"]["shown"] for r in results if isinstance(r.get("coverage"), dict) and r["coverage"].get("shown")), None)
    keep = max(1, int(shown * max_chars * 0.7 / size)) if shown else None
    if getattr(args, "list_fields", False):
        # 성진: 필드 목록을 요청한 호출에 --fields를 권하면 존재하지 않는 축을 가리킨다; 이 출력을 줄이는 것은 --filter다.
        return head + f"Narrow the field listing with --filter TEXT, or ask for fewer targets. Or rerun with --max-chars {needed}."
    named = narrowings(item, args)
    narrow = ", ".join(named) if named else None

    if len(saved) > 1:
        # 성진: 다종목에서 첫 id만 주면 비교 요청이 단일 종목 질문으로 바뀐다; 전부 이름 붙이고 목표를 줄이는 길도 함께 준다.
        listed = "; ".join(f"{t} {i}" for t, i in saved)
        # 성진: 목표만 보존하고 투영을 빠뜨리면 회복이 기본 필드집합으로 돌아가 다른 값을 성공적으로 낸다 — 질문이 바뀐 것은 같다.
        kept = quoted(args, [("--fields", ",".join(args.fields) if getattr(args, "fields", None) else None)])
        each = f" Each target was observed and saved separately: {listed}. Read one with read ID{kept}" + (f" --limit {keep}" if keep else "") + f", ask for fewer targets in one call, or rerun with --max-chars {needed}."
        return head + (f"Narrow with {narrow}." if narrow else "Ask for fewer targets.") + each
    if saved and keep is not None:
        if keep >= (shown or 0):
            # 성진: 한 행이 이미 예산보다 크면 더 작은 --limit을 권하는 회복은 같은 실패를 반복한다 — 무한루프가 아니라
            # 거짓 주장이다. 줄일 축이 남아 있으면 그것을, 없으면 통과할 크기를 말한다.
            axis = f"Narrow with {narrow}, which reduces this leaf by something other than rows. " if narrow and item.sliceable else ""
            return head + f"A single entry is already larger than the budget, so fewer rows cannot fit it. {axis}Or rerun with --max-chars {needed}; the whole response is saved as {saved[0][1]}."
        return head + (f"Narrow with {narrow}. " if narrow else "") + f"The whole response is saved: {read_command(saved[0][1], item, args, keep)} reads it in slices without a new request, and each slice names the next. Or rerun with --max-chars {needed}."
    if narrow:
        return head + f"Narrow with {narrow}, or rerun with --max-chars {needed}."
    return head + f"Rerun with --max-chars {needed}."


def schema_fix(size, max_chars, scoped, filtered=False):
    head = f"Result needs {size} characters; limit is {max_chars}. "
    if scoped:
        return head + f"Narrow with --filter TEXT, or rerun with --max-chars {size}."
    if filtered:
        # 성진: 이미 --filter를 준 호출에 --filter를 권하면 방금 한 일을 다시 하라는 말이 된다.
        return head + f"Use a narrower --filter, or scope it with schema GROUP LEAF. Or rerun with --max-chars {size}."
    return head + "Scope it with schema GROUP or schema GROUP LEAF, or add --filter TEXT."


def too_large_document(results, error, max_chars, request):
    """The replacement for an oversized document is itself checked against the budget.

    Dropping the recovery sentence to fit would keep the boundary and lose the only thing that makes the failure
    survivable, so the ladder sheds targets and then fields, and keeps the id and the size that would pass to the end.
    """
    rest = error_info(error["code"], error["message"], "Recover with the fix on the first result; this target's own response is saved under the id here.")
    rows = [{"target": r.get("target"), "id": r.get("id"), "status": "error", "error": error if i == 0 else rest} for i, r in enumerate(results)]
    trimmed = [row if i == 0 else {k: v for k, v in row.items() if k != "error"} for i, row in enumerate(rows)]
    dropped = dict(rows[0], error=error_info(error["code"], error["message"], error["fix"] + f" {len(results) - 1} further targets were saved but do not fit this document; ask for them in smaller groups."))
    for attempt in (rows, trimmed, [dropped] if len(results) > 1 else [rows[0]]):
        text = dump(document(attempt, "error", request))
        if attempt and len(text) <= max_chars:
            return text
    size = re.search(r"--max-chars (\d+)", error["fix"])
    # 성진: 가장 짧은 형태에도 복구에 필요한 셋은 남긴다 — 통과할 크기, 저장된 목표가 몇 개인지, 그것들이 여기 없다는 사실.
    advice = (f"Rerun with --max-chars {size[1]}" if size else "Raise --max-chars") + (f"; all {len(results)} targets were saved and none of their ids fit this document, so rerun at that size or ask for fewer targets." if len(results) > 1 else ".")
    smallest = [{k: v for k, v in {"id": results[0].get("id"), "status": "error",
                                   "error": error_info(error["code"], error["message"], advice)}.items() if v is not None}]
    for attempt in ([rows[0]], smallest):
        text = dump(document(attempt, "error", None))
        if len(text) <= max_chars:
            return text
    return text  # below this a document cannot both parse and say what went wrong


def emit(results, args, item, request=None, scoped=False):
    """Print one document, narrowing an oversized window before refusing and refusing before truncating silently."""
    max_chars = getattr(args, "max_chars", 20000)
    text = dump(document([strip(r, item) for r in results], overall(results), request))
    if len(text) <= max_chars:
        print(text)
        return code(results, overall(results))
    # 성진: fix가 이름 붙이는 --max-chars는 축소 전 문서가 필요로 한 크기다. 축소 후 크기를 실으면 그 값으로 다시 돌려도
    # 같은 결과가 다시 넘친다 — "이름 붙인 크기가 통과하는 크기"라는 계약이 바로 그 자리에서 깨진다.
    needed = len(text)

    if item is not None:
        # 성진: 한 번의 축소는 봉투 고정비 때문에 자주 모자란다; 매번 방금 측정한 크기에서 다시 계산하면 몇 번 안에 수렴하고,
        # 수렴하지 않으면(한 행이 예산보다 크면) 아래 too_large가 그 사실을 이름 붙여 말한다.
        for _ in range(5):
            if not any(shrink(envelope, item, args, len(text), max_chars) for envelope in results
                       if envelope["status"] in ("ok", "partial") and not is_empty(envelope.get("data"))):
                break
            status = overall(results)
            text = dump(document([strip(r, item) for r in results], status, request))
            if len(text) <= max_chars:
                print(text)
                return code(results, status)

    clean = [strip(r, item) for r in results]
    fix = schema_fix(needed, max_chars, scoped, bool(getattr(args, "filter", ""))) if item is None else too_large_fix(clean, item, len(text), max_chars, args, needed)
    error = error_info("too_large", f"Result requires {needed} characters; limit is {max_chars}.", fix)
    print(too_large_document(clean, error, max_chars, request))
    return EXIT_CODES["too_large"]


def strip(envelope, item=None):
    """The printed copy: private keys dropped, and the data shown at the precision the source had."""
    shown = {k: v for k, v in envelope.items() if not k.startswith("_")}
    if item is not None and shown.get("data") is not None:
        zoned = bool((shown.get("context") or {}).get("timezone"))
        shown["data"] = display(shown["data"], envelope.get("_full"), item.precise, zoned)
    return shown


def code(results, status):
    if status in ("ok", "partial", "empty"):
        return EXIT_CODES[status]
    codes = {r["error"]["code"] for r in results if r.get("error")}
    if "rate_limited" in codes:
        return EXIT_CODES["rate_limited"]
    if "invalid" in codes:
        return EXIT_CODES["invalid"]
    if "local_io" in codes:
        return EXIT_CODES["local_io"]
    return EXIT_CODES["upstream"]


# ---- upstream failures -------------------------------------------------------------------------------------------

CONSTRAINTS = (
    (re.compile(r"[Oo]nly (\d+) days? worth of (\S+) granularity"), "days"),
    (re.compile(r"must be within the last (\d+) days"), "days"),
)


def upstream_fix(message, item, args):
    """When the source's own refusal carries the constraint, that constraint is the prescription.

    Every upstream failure used to receive the same sentence about verifying the symbol, so a message that said
    plainly how many days were allowed was answered with advice to doubt the ticker.
    """
    text = str(message)
    for pattern, kind in CONSTRAINTS:
        found = pattern.search(text)
        if found and kind == "days":
            days = int(found.group(1))
            interval = getattr(args, "interval", None)
            asked = getattr(args, "period", None) or f"{getattr(args, 'start', '')}..{getattr(args, 'end', '')}"
            return (f"The source allows {days} days per request at this granularity, and {asked} is longer. "
                    f"Retry with --period {days}d, or give --start and --end inside the last {days} days"
                    + (f"; a longer range needs a coarser --interval than {interval} (1h and 1d have no such limit)." if interval else "."))
    if "No data found" in text or "may be delisted" in text or "symbol may be delisted" in text:
        return "The source has no data for this symbol and dataset. Confirm the symbol with search, which reports the exchange and instrument type, or choose a dataset this instrument type reports."
    return f"Retry later, or confirm the symbol and dataset with search and schema {item.path if item else ''}".rstrip() + "; use --timeout SECONDS if the target timed out."
