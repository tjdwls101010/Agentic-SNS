"""read: a saved observation, sliced again without a new request."""
from yfinance_skill import budget, export, store, yahoo
from yfinance_skill.envelope import InputError, ordered, result
from yfinance_skill.querying.out import exported, write_out
from yfinance_skill.selection import select, select_sides
from yfinance_skill.shape import is_sided


def read(args, saved, commands):
    """Re-read a saved observation through the same selector that printed it the first time.

    Reusing the leaf's own selector rather than a generic JSON pointer is why a slice of a table keeps its column
    names: a pointer into the encoded rows would hand back an unlabelled array. The record names its command by path
    ("prices history"), which is how an observation saved by an earlier version finds today's declaration.
    """
    record = saved.load(args.id)
    command = commands.get(record["command"])
    if command is None:
        raise InputError(f"Observation {args.id} came from {record['command']}, which this version no longer offers.")
    item = yahoo.bind(command)
    coverage = {}
    if is_sided(record["data"]) and not args.list_fields:
        data = select_sides(record["data"], args, item, coverage)
    else:
        data, coverage = select(record["data"], args, item, coverage)
    warnings = list(record.get("warnings") or [])
    age = store.age_seconds(record.get("observed_at"))
    if record.get("status") == "empty":
        warnings.append("The original observation returned nothing usable; reading it again does not change that.")
    if is_sided(record["data"]):
        sides = [v for v in coverage.values() if isinstance(v, dict) and "received" in v]
        coverage = dict(coverage, received=sum(s["received"] for s in sides), shown=sum(s.get("shown", 0) for s in sides)) if sides else coverage
    shown, received, start = coverage.get("shown"), coverage.get("received"), coverage.get("start", 0)
    extra = {}
    if shown is not None and received is not None and start + shown < received:
        following = start + shown
        extra["continuation"] = {"start": following, "command": budget.read_command(args.id, item, args, shown, following)}
    envelope = result(record["target"], data, record.get("context"), warnings, status=record.get("status") if record.get("status") == "empty" else None,
                      conditions=record.get("conditions"), coverage=coverage, ident=args.id,
                      observed_at=record.get("observed_at"), source_time=record.get("source_time"), extra=extra)
    envelope["stored_age_seconds"] = age
    envelope["_full"] = record["data"]
    results = [ordered(envelope)]
    if getattr(args, "out", None):
        if args.list_fields:
            raise InputError("--list-fields names columns and --out writes rows; use one of them.")
        export.check_path(args.out)
        write_out(results, {0: (args.id, *exported(record["data"], args, item))}, args)
        results[0].pop("continuation", None)
    return budget.emit(results, args, item, {"read": args.id})
