"""--out for a data command or a read: the rows a file gets, the file published once, and the summary printed instead."""
import copy

from yfinance_skill import budget, export
from yfinance_skill.envelope import error_info, ordered, result
from yfinance_skill.selection import select, select_sides
from yfinance_skill.shape import is_empty, is_sided, is_table


def exported(encoded, args, item):
    """The rows a file gets: this observation's, projected only by an explicit --fields, cut only by an explicit --limit."""
    whole = copy.copy(item)
    whole.limit, whole.fields = None, ()  # the leaf's default window and projection are for the screen; a computation needs what arrived
    coverage = {}
    keyed = isinstance(encoded, dict) and not is_table(encoded) and not is_sided(encoded) and all(isinstance(v, dict) for v in encoded.values())
    if keyed:  # a mapping of records windows like the rows it becomes, and keeps its key through --fields
        encoded = [{"key": k, **{("source.key" if f == "key" else f): x for f, x in v.items()}} for k, v in encoded.items()]
        if getattr(args, "fields", None) and "key" not in args.fields:
            args = copy.copy(args)
            args.fields = ["key", *args.fields]
    if is_sided(encoded):
        data = select_sides(encoded, args, whole, coverage)
        sides = [v for v in coverage.values() if isinstance(v, dict) and "received" in v]
        coverage = {"received": sum(s["received"] for s in sides), "shown": sum(s.get("shown", 0) for s in sides)}
    else:
        data, coverage = select(encoded, args, whole, coverage)
    if is_empty(data):
        return ([], []), coverage  # nothing usable was selected; this target contributes no rows, as its empty status says
    return export.rows_of(data, keyed), coverage


def retry(ident, args, coverage):
    """The read that writes the same rows again: same store, same projection, same slice."""
    start = coverage.get("start", 0)
    if coverage.get("kept") == "newest":
        start = coverage["received"] - coverage["shown"]
    explicit = getattr(args, "limit", None)
    names = [("--store", getattr(args, "store", None)), ("--fields", ",".join(args.fields) if getattr(args, "fields", None) else None),
             ("--start", start or None), ("--limit", explicit)]
    return f"read {ident}" + budget.quoted(args, names) + " --out NEWPATH"


def write_out(results, pending, args):
    """Publish every target's rows as one file, then give each result the summary in place of its rows."""
    parts = [(results[i]["target"], rows) for i, (_, rows, _) in sorted(pending.items()) if rows[1]]
    columns, failure = None, None
    if parts:
        try:
            columns = export.publish(args.out, parts)
        except export.Unpublished as exc:
            failure = exc
    for i, (ident, (keys, records), coverage) in pending.items():
        envelope = results[i]
        envelope.pop("_full", None)  # the rows are in the file; the budget has nothing here to narrow
        if not records:
            continue
        if failure:
            fix = f"Choose a new path; the rows are saved, so {retry(ident, args, coverage)} writes them without a new request."
            results[i] = ordered(result(envelope["target"], error=error_info(failure.code, failure, fix), ident=ident))
            continue
        envelope["data"] = export.summary(args.out, columns, keys, records)
        envelope["coverage"] = coverage
