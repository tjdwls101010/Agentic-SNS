"""One target's result envelope, the statuses and exit codes it can carry, and the conditions it can claim."""
import datetime as dt

from encode import column, is_empty

EXIT_CODES = {"ok": 0, "invalid": 2, "local_io": 4, "rate_limited": 5, "upstream": 6, "empty": 7, "partial": 8, "too_large": 9}
STATUSES = {
    "ok": "usable data within this leaf's own default window",
    "empty": "the source answered with nothing usable; not proof the data does not exist",
    "partial": "usable data with a stated gap: a budget-narrowed window, or a mix of succeeded and failed targets",
    "error": "no usable result; error.code and error.fix say what to do",
}


class InputError(ValueError):
    pass


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
