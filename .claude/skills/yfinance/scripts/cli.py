# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["yfinance[repair]==1.7.0", "pandas", "numpy"]
#
# [tool.uv]
# exclude-newer = "2026-09-13T13:10:00Z"
# ///
"""Purpose-oriented Yahoo Finance CLI. Discover contracts with schema and --help."""
import argparse
import contextlib
import copy
from datetime import date
import re
import signal
import sys

import yfinance as yf

from yfinance_skill import budget, export, registry, store
import yfinance_skill.yahoo  # noqa: F401  registers every leaf
from yfinance_skill.shape import is_empty, is_sided, is_table
from yfinance_skill.yahoo.encode import encode
from yfinance_skill.envelope import InputError, error_info, now, ordered, result
from yfinance_skill.schema import schema_data
from yfinance_skill.selection import select, select_sides


EXIT_CODES = {"ok": 0, "invalid": 2, "local_io": 4, "rate_limited": 5, "upstream": 6, "empty": 7, "partial": 8, "too_large": 9}


def exit_code(status, codes):
    """A printed document's status as an exit code; a document with no usable result takes its most actionable error."""
    if status in ("ok", "partial", "empty", "too_large"):
        return EXIT_CODES[status]
    for code in ("rate_limited", "invalid", "local_io"):
        if code in codes:
            return EXIT_CODES[code]
    return EXIT_CODES["upstream"]


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class", argparse.RawTextHelpFormatter)
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise InputError(message)


def build_parser():
    parser = Parser(description="Query Yahoo Finance data by purpose. stdout: one JSON document; diagnostics: stderr. Discover with schema [GROUP [LEAF]].")
    registry.add_common(parser, False, root=True)
    parser.add_argument("--ttl-days", type=int, default=registry.GLOBAL_DEFAULTS["ttl_days"], help="Delete saved observations older than this many days. Retention only: an observation inside the window is not therefore current, and source_time is what says whether a value is fresh.")
    groups_parser = parser.add_subparsers(dest="group", required=True)

    schema = groups_parser.add_parser("schema", help="Discover inputs and output contracts offline")
    schema.add_argument("scope", nargs="*", help="GROUP or GROUP LEAF to describe; omit to list every group.")
    registry.add_common(schema, False)

    reader = groups_parser.add_parser("read", help="Read a saved observation in slices without a new request")
    reader.add_argument("id", help="Observation id from an earlier result.")
    reader.add_argument("--start", dest="row_start", type=int, default=0, help="Zero-based first row to return; each slice names the start of the next one.")
    registry.add_common(reader)
    reader._option_string_actions["--limit"].help = "Maximum rows, counted forward from --start in saved order; unlike the first call, read does not keep the newest end. The same slice goes to --out."
    reader.add_argument("--out", help=registry.OUT_HELP)
    reader.set_defaults(leaf="")

    members = {}
    for (group, name), item in registry.LEAVES.items():
        members.setdefault(group, {})[name] = item
    parsers = {}
    for group, items in members.items():
        gp = groups_parser.add_parser(group, help=registry.GROUPS[group])
        alone = list(items) == [""]  # a group whose only command is the group itself takes its arguments directly
        sub = None if alone else gp.add_subparsers(dest="leaf", required=True)
        for name, item in items.items():
            p = gp if alone else sub.add_parser(name, description=item.purpose, help=item.purpose)
            if alone:
                p.description = item.purpose
                p.set_defaults(leaf="")
            if item.epilog:
                p.epilog = item.epilog
            parsers[group, name] = p
            registry.add_common(p)
            if item.exportable:
                p.add_argument("--out", help=registry.OUT_HELP)
            for arg in item.args:
                arg.add(p)
    parsers["read"] = reader
    return parser, parsers


# ---- validation --------------------------------------------------------------------------------------------------


def validate(args, item):
    targets = []
    for dest in item.positionals():
        value = getattr(args, dest, None)
        targets.extend(value if isinstance(value, list) else [value] if value is not None else [])
    if any(not target.strip() for target in targets):
        raise InputError("Target symbols, search text and domain keys must not be empty")
    if args.timeout <= 0:
        raise InputError("--timeout must be positive")
    minimums = dict({"limit": 1}, **item.minimums())
    for name, minimum in minimums.items():
        if getattr(args, name, None) is not None and getattr(args, name) < minimum:
            raise InputError(f"--{name} must be >= {minimum}")
    if getattr(args, "offset", 0) < 0:
        raise InputError("--offset must be nonnegative")
    if getattr(args, "row_start", 0) < 0:
        raise InputError("--start must be nonnegative")
    for name in ("start", "end", "date"):
        value = getattr(args, name, None)
        if isinstance(value, str):
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                raise InputError(f"--{name} expects YYYY-MM-DD") from None
    start, end = getattr(args, "start", None), getattr(args, "end", None)
    if isinstance(start, str) and isinstance(end, str) and (start > end or (item.end_exclusive and start == end)):
        raise InputError("Invalid date range; a price --end is exclusive so it must be after --start, and a calendar --end is inclusive so it may equal --start")
    if hasattr(args, "period"):
        if args.period and (start or end):
            raise InputError("--period cannot be combined with --start or --end")
        if args.period and not re.fullmatch(r"([1-9][0-9]*(d|wk|mo|y)|ytd|max)", args.period):
            raise InputError("--period expects a positive range such as 5d, 1mo, 1y, ytd or max")
    if getattr(args, "out", None):
        if args.list_fields:
            raise InputError("--list-fields names columns and --out writes rows; use one of them.")
        export.check_path(args.out)
    if item.check:
        item.check(args)
    if item.defaults:
        item.defaults(args)
    if args.fields and any(not f for f in args.fields):
        raise InputError("--fields requires nonempty comma-separated field names")


class DeadlineExpired(BaseException):
    """Bypass upstream broad Exception handlers so a CLI deadline stays bounded."""


def timed_out(signum, frame):
    raise DeadlineExpired("Target exceeded --timeout; narrow the request or raise --timeout")


# ---- execution ---------------------------------------------------------------------------------------------------


def observe(target, args, item, saved):
    """One target: fetch, note what the response itself confirms, and hand back the encoded value before selection."""
    context, warnings = {}, []
    if getattr(args, "from_id", None):
        record = saved.load(args.from_id)
        if record.get("target") != target:
            raise InputError(f"Observation {args.from_id} holds {record.get('target')}, not {target}; pass the id returned for this symbol or drop --from.")
        sharing = {leaf.path for leaf in registry.LEAVES.values() if leaf.shares_info}
        if record.get("command") not in sharing:
            raise InputError(f"Observation {args.from_id} came from {record.get('command')}, which does not hold this command's fields; drop --from to request it.")
        return record["data"], record.get("context") or {}, list(record.get("warnings") or []), record.get("conditions") or {}, record.get("observed_at"), record.get("source_time"), args.from_id

    data = item.fetch(yf.Ticker(target) if item.ticker else target, args, context, warnings)
    encoded = encode(data)
    conditions = item.conditions(encoded, args, context) if item.conditions else {}
    when = context.pop("source_time", None) or (item.source_time(encoded) if item.source_time else None)
    return encoded, context, warnings, conditions, now(), when, None


def run(args, item, saved, request):
    results, stopped, pending = [], False, {}
    plural = list(getattr(args, "symbols", [])) or [getattr(args, "symbol", None) or getattr(args, "query", None) or getattr(args, "key", None) or args.group]
    for position, target in enumerate(plural):
        if stopped:
            results.append(result(target, status="not_attempted", error=error_info("not_attempted", "Stopped after rate limiting", "Retry later with fewer targets.")))
            continue
        try:
            signal.signal(signal.SIGALRM, timed_out)
            signal.alarm(args.timeout)
            with contextlib.redirect_stdout(sys.stderr):
                encoded, context, warnings, conditions, observed_at, when, reused = observe(target, args, item, saved)
                ident = reused or saved.save(store.record(item, target, request, encoded, context, warnings, "empty" if is_empty(encoded) else "ok", conditions, observed_at, when))
                if getattr(args, "out", None):
                    pending[position] = (ident, *exported(encoded, args, item))
                coverage = {}
                if is_sided(encoded) and not args.list_fields:
                    data = select_sides(encoded, args, item, coverage)
                else:
                    data, coverage = select(encoded, args, item, coverage)
            envelope = result(target, data, context, warnings, conditions=conditions, coverage=coverage, ident=ident, observed_at=observed_at, source_time=when)
            envelope["_full"] = encoded
            results.append(ordered(envelope))
            stopped = context.get("rate_limited", False)
        except (Exception, DeadlineExpired) as exc:
            code = "invalid" if isinstance(exc, InputError) else "rate_limited" if "429" in str(exc) or "RateLimit" in type(exc).__name__ else "upstream"
            stopped = code == "rate_limited"
            fix = (f"Correct the arguments; schema {item.path} reports this command's choices and defaults." if code == "invalid"
                   else "Retry later with fewer targets; remaining targets were not attempted." if code == "rate_limited"
                   else budget.upstream_fix(exc, item, args))
            results.append(ordered(result(target, error=error_info(code, exc, fix))))
        finally:
            signal.alarm(0)
    if getattr(args, "out", None):
        write_out(results, pending, args)
    return results


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


def read(args, saved):
    """Re-read a saved observation through the same selector that printed it the first time.

    Reusing the leaf's own selector rather than a generic JSON pointer is why a slice of a table keeps its column
    names: a pointer into the encoded rows would hand back an unlabelled array.
    """
    record = saved.load(args.id)
    item = registry.by_path(record["command"])
    if item is None:
        raise InputError(f"Observation {args.id} came from {record['command']}, which this version no longer offers.")
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
    return results, item


def chosen(request, given, parser):
    """The printed request: what the caller chose and what a default filled in, not every parser default echoed back.

    The saved observation keeps the whole request, since reproducing it needs every value.
    """
    defaults = {a.dest: registry.GLOBAL_DEFAULTS.get(a.dest) if a.default == argparse.SUPPRESS else a.default for a in parser._actions}
    return {k: v for k, v in request.items() if k not in ("group", "leaf") and (v != given.get(k) or v != defaults.get(k, v))}


def main():
    args = None
    try:
        parser, parsers = build_parser()
        args = parser.parse_args()
        if args.max_chars < budget.MIN_CHARS:
            raise InputError(f"--max-chars must be >= {budget.MIN_CHARS} so recovery instructions remain readable")
        saved = store.Store(args.store)
        saved.prune(args.ttl_days)
        if args.group == "schema":
            return exit_code(*budget.emit([ordered(result("schema", schema_data(args, parsers, parser, EXIT_CODES)))], args, None, {"scope": args.scope}, scoped=bool(args.scope)))
        if args.group == "read":
            results, item = read(args, saved)
            return exit_code(*budget.emit(results, args, item, {"read": args.id}))
        item = registry.get(args.group, args.leaf)
        given = dict(vars(args))
        validate(args, item)
        yf.config.debug.hide_exceptions = False
        request = {k: v for k, v in vars(args).items() if k not in ("symbols", "store", "ttl_days", "max_chars", "list_fields")}
        return exit_code(*budget.emit(run(args, item, saved, request), args, item, chosen(request, given, parsers[args.group, args.leaf])))
    except InputError as exc:
        fix = "Use --help for this command's arguments, or schema GROUP LEAF for its defaults, units and limits."
        results = [ordered(result("request", error=error_info("invalid", exc, fix)))]
        # 성진: 잘못된 --max-chars 자체가 입력 오류일 때 그 값으로 오류 문서를 재면 too_large가 invalid를 가린다 —
        # 무엇이 틀렸는지 말하는 문서는 틀린 예산의 적용 대상이 아니다.
        reporting = argparse.Namespace(max_chars=max(getattr(args, "max_chars", 0) or 0, registry.GLOBAL_DEFAULTS["max_chars"]))
        return exit_code(*budget.emit(results, reporting, None, None))


if __name__ == "__main__":
    raise SystemExit(main())
