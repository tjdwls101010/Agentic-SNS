"""A data command, answered: each target fetched, saved before anything is selected from it, then selected and printed."""
import contextlib
import signal
import sys

from yfinance_skill import budget, export, store, yahoo
from yfinance_skill.envelope import InputError, LocalFailure, error_info, now, ordered, result
from yfinance_skill.leaf import Leaf
from yfinance_skill.querying.out import exported, write_out
from yfinance_skill.selection import select, select_sides
from yfinance_skill.shape import is_empty, is_sided, row_count


def open_store(args):
    """Every command opens the store and applies retention before anything else runs."""
    saved = store.Store()
    saved.prune(args.ttl_days)
    return saved


def prepare(command, args):
    """Turn the parsed arguments into the ones in force: the file is refused before any request is paid for, then the
    command's own checks, its argument defaults, and what the dataset itself fixes for this call (a preset's sort)."""
    if getattr(args, "out", None):
        check_out(args, len(getattr(args, "symbols", None) or [None]))
    if command.check:
        command.check(args)
    if command.defaults:
        command.defaults(args)
    dataset = yahoo.dataset(command.dataset)
    if dataset.prepare:
        dataset.prepare(args)


LOCAL_FIX = "Make the store directory the message names (the skill's data/observations, or $YF_STORE) and the --out directory writable, or choose another --out path."


def check_out(args, targets):
    """Refused before any request: a file that exists, a directory that does not, or a path so long that even the
    smallest receipt for it would not fit --max-chars, which would leave a written file no document could report."""
    export.check_path(args.out)
    if not budget.receipt_fits(args.out, targets, args.max_chars):
        raise InputError(f"The receipt for this --out path ({len(str(args.out))} characters) does not fit --max-chars {args.max_chars}; use a shorter path or raise --max-chars.")


class DeadlineExpired(BaseException):
    """Bypass upstream broad Exception handlers so a CLI deadline stays bounded."""


def timed_out(signum, frame):
    raise DeadlineExpired("Target exceeded --timeout; narrow the request or raise --timeout")


def observe(target, args, item, saved, commands):
    """One target: fetch, note what the response itself confirms, and hand back the encoded value before selection."""
    context, warnings = {}, []
    if getattr(args, "from_id", None):
        record = saved.load(args.from_id)
        if record.get("target") != target:
            raise InputError(f"Observation {args.from_id} holds {record.get('target')}, not {target}; pass the id returned for this symbol or drop --from.")
        sharing = {path for path, command in commands.items() if yahoo.dataset(command.dataset).shares_info}
        if record.get("command") not in sharing:
            raise InputError(f"Observation {args.from_id} came from {record.get('command')}, which does not hold this command's fields; drop --from to request it.")
        return record["data"], record.get("context") or {}, list(record.get("warnings") or []), record.get("conditions") or {}, record.get("observed_at"), record.get("source_time"), args.from_id, record.get("requested")

    explicit = getattr(args, "limit", None)
    rows = explicit if explicit is not None else item.command.rows  # a source sent a count is asked for the window this call shows
    encoded = yahoo.fetch(item.command.dataset, target, args, context, warnings, rows)
    conditions = item.conditions(encoded, args, context) if item.conditions else {}
    when = context.pop("source_time", None) or (item.source_time(encoded) if item.source_time else None)
    requested, received = context.pop("requested", None), row_count(encoded)
    if item.dataset.shortfall and requested and received and received < requested:  # nothing at all is the empty status's to explain
        warnings.append(item.dataset.shortfall.format(received=received, requested=requested))
    return encoded, context, warnings, conditions, now(), when, None, requested


def upstream_fix(exc, item, args):
    """When the source's own refusal carries the constraint, that constraint is the prescription.

    Every upstream failure used to receive the same sentence about verifying the symbol, so a message that said
    plainly how many days were allowed was answered with advice to doubt the ticker.
    """
    if isinstance(exc, yahoo.SourceConstraint):
        days, interval = exc.days, getattr(args, "interval", None)
        asked = getattr(args, "period", None) or f"{getattr(args, 'start', '')}..{getattr(args, 'end', '')}"
        coarser = f"; beyond that, a coarser --interval than {interval} (schema prices history lists the limits known)." if interval else "."
        if exc.kind == "span":
            return (f"The source serves at most {days} days of this granularity per request, and {asked} is longer. "
                    f"Retry with --period {days}d or a --start/--end span of at most {days} days" + coarser)
        return (f"The source serves this granularity only for the last {days} days, and {asked} reaches further back. "
                f"Retry with --period {days}d or a --start inside the last {days} days" + coarser)
    if isinstance(exc, yahoo.NoData):
        return "The source has no data for this symbol and dataset. Confirm the symbol with search, which reports the exchange and instrument type, or choose a dataset this instrument type reports."
    return f"Retry later, or confirm the symbol and dataset with search and schema {item.path}".rstrip() + "; use --timeout SECONDS if the target timed out."


def asked_for(coverage, requested):
    """Coverage with the count the source was asked for in front, where the source was asked for one."""
    return {"requested": requested, **coverage} if requested is not None else coverage


def run(args, item, saved, request, commands):
    results, stopped, pending = [], False, {}
    plural = list(getattr(args, "symbols", [])) or [getattr(args, "symbol", None) or getattr(args, "query", None) or getattr(args, "key", None) or args.group]
    for position, target in enumerate(plural):
        if stopped:
            results.append(result(target, status="not_attempted", error=error_info("not_attempted", "Stopped after rate limiting", "Retry later with fewer targets.")))
            continue
        ident = None  # set once the response is saved, so a failure after that still names the handle to it
        try:
            signal.signal(signal.SIGALRM, timed_out)
            signal.alarm(args.timeout)
            with contextlib.redirect_stdout(sys.stderr):
                encoded, context, warnings, conditions, observed_at, when, reused, requested = observe(target, args, item, saved, commands)
                stopped = context.get("rate_limited", False)  # met while observing; a later failure on this target does not lift it
                ident = reused or saved.save(store.record(item, target, request, encoded, context, warnings, "empty" if is_empty(encoded) else "ok", conditions, observed_at, when, requested))
                if getattr(args, "out", None):
                    rows, covered = exported(encoded, args, item)
                    pending[position] = (ident, rows, asked_for(covered, requested))
                coverage = {}
                if is_sided(encoded) and not args.list_fields:
                    data = select_sides(encoded, args, item, coverage)
                else:
                    data, coverage = select(encoded, args, item, coverage)
                coverage = asked_for(coverage, requested)
            envelope = result(target, data, context, warnings, conditions=conditions, coverage=coverage, ident=ident, observed_at=observed_at, source_time=when)
            envelope["_full"] = encoded
            results.append(ordered(envelope))
        except (Exception, DeadlineExpired) as exc:
            code = ("invalid" if isinstance(exc, InputError) else "local_io" if isinstance(exc, LocalFailure)
                    else "rate_limited" if isinstance(exc, yahoo.RateLimited) else "upstream")
            stopped = stopped or code == "rate_limited"
            fix = (f"Correct the arguments; schema {item.path} reports this command's choices and defaults." if code == "invalid"
                   else LOCAL_FIX if code == "local_io"
                   else "Retry later with fewer targets; remaining targets were not attempted." if code == "rate_limited"
                   else upstream_fix(exc, item, args))
            results.append(ordered(result(target, error=error_info(code, exc, fix), ident=ident)))
        finally:
            signal.alarm(0)
    if getattr(args, "out", None):
        write_out(results, pending, args)
    return results


def answer(args, command, commands, saved, request, shown):
    """Run a data command and print its document; `request` is saved with each observation, `shown` is what prints."""
    item = Leaf(command, yahoo.dataset(command.dataset))
    return budget.emit(run(args, item, saved, request, commands), args, item, shown)
