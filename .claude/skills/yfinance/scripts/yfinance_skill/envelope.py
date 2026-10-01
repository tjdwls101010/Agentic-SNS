"""One target's result envelope, the statuses it can carry, and the conditions it can claim."""
import datetime as dt

from yfinance_skill.shape import column, is_empty

STATUSES = {
    "ok": "usable data in the default window (exit 0)",
    "empty": "nothing usable came back (exit 7)",
    "partial": "usable data with a stated gap (exit 8)",
    "error": "no usable result; error.code names which exit code below, and error.fix says what to do",
    "not_attempted": "not asked, because the source rate-limited an earlier target",
}


class InputError(ValueError):
    """An argument the caller has to change; `fix`, when given, says how in place of the general advice."""

    def __init__(self, message, fix=None):
        super().__init__(message)
        self.fix = fix


class LocalFailure(Exception):
    """The store or an --out file could not be read or written: a fault in a local path, not in the request."""


# ---- conditions --------------------------------------------------------------------------------------------------


def condition(requested, status="unverified", evidence=None):
    """What a condition actually did to this response. A 200 with rows is not evidence that a filter was applied."""
    return {"requested": requested, "status": status, "evidence": evidence}


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

# 성진: 싼 신호(상태·범위·경고)를 비싼 상세(data) 앞에 둔다 — 잘린 출력이나 앞부분만 읽는 쪽도 경고는 본다.
ORDER = ("target", "id", "observed_at", "source_time", "stored_age_seconds", "status", "context", "conditions", "coverage", "continuation", "warnings", "data", "error")

# What each envelope key means, in ORDER; a command's --help prints it.
ENVELOPE = {
    "target": "the symbol, query or key this result answers",
    "id": "saved observation id; the response is saved before anything is selected, so `read ID` reaches what did not fit",
    "observed_at": "when this CLI received the response",
    "source_time": "the time the source put on the data, where it gives one; after a close it can be hours before observed_at",
    "stored_age_seconds": "read only: seconds since the observation was saved, not a sign its values are current",
    "status": "see statuses",
    "context": "what the source said besides the rows: currency, timezone, the chosen expiration, next_offset for the next source page (a new request)",
    "conditions": "the arguments this response carries evidence for: {requested, status: confirmed|not_applied|unverified, evidence}; a successful call is not evidence a condition was applied",
    "coverage": "requested: rows asked of the source, only where a count is sent; fewer received is not proof there are no more. received: rows the response holds. start: where a read began. shown: rows printed or written. kept: which end a limit kept (window for read). truncated_by: leaf_default (status ok), explicit_limit, or budget (status partial). fields: how many offered fields were kept. A chain reports each side under its name; received and shown total them",
    "continuation": "the read command for the next slice of this saved observation (no new request); restart: true with shown [a, b] means the newest rows [a, b) were shown and reading starts over at row 0",
    "warnings": "limits on how this data can be used",
    "data": "the selected value; a table is {index, columns, data, index_names, column_names}; with --out, {out, rows, columns, first, last}",
    "error": "{code, message, fix}",
}


def result(target, data=None, context=None, warnings=None, error=None, status=None, conditions=None, coverage=None, ident=None, observed_at=None, source_time=None, extra=None):
    """One target's answer. Only observations go in: an argument echoed back as though it were a measurement is a
    claim the CLI cannot support, and the request is already stated once at the document level."""
    if status is None:
        status = "error" if error else "empty" if is_empty(data) else "ok"
    notices = list(warnings or [])
    if status == "empty":
        notices.append("An empty upstream return does not prove that the data does not exist.")
    envelope = {"target": target, "id": ident, "observed_at": observed_at or now(), "source_time": source_time,
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
