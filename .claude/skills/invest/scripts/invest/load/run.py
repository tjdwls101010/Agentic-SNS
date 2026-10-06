"""The target loop: each target fetched under its own deadline, a rate limit stopping the rest, then one file and one receipt for all of them."""
import contextlib
import datetime as dt
import signal
import sys

from invest import receipts, results, yahoo
from invest.load.receipt import assemble


class DeadlineExpired(BaseException):
    """A BaseException, so the library's broad `except Exception` cannot swallow the caller's --timeout."""


def expired(signum, frame):
    raise DeadlineExpired()


def kinds():
    """{command: [kind, ...]} for every Yahoo command; [] for a command without kinds."""
    return yahoo.kinds()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def observe(key, target, args):
    """(status, Observation or Failure, observed_at, stop) for one target, inside its deadline.

    The deadline is SIGALRM: a Unix, main-thread contract that interrupts Python code between bytecodes, not a native call blocked inside a socket read.
    """
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(args.timeout)
    try:
        with contextlib.redirect_stdout(sys.stderr):  # yfinance prints; stdout carries only the receipt
            found = yahoo.fetch(key, target, args)
        signal.alarm(0)
        observed = found.observed_at.isoformat() if found.observed_at else now()
        return ("empty" if found.empty else "ok"), found, observed, found.rate_limited
    except DeadlineExpired:
        failure = receipts.Failure(f"No answer within --timeout {args.timeout} seconds", "Raise --timeout, or ask for a shorter range or fewer targets.")
        return "error", failure, now(), False
    except receipts.Failure as exc:
        return "error", exc, now(), exc.code == "rate_limited"
    finally:
        signal.alarm(0)


def run(key, args):
    """(document to print, exit code) for one Yahoo command over `args.targets`."""
    yahoo.check(key, args)
    ident = results.new_id()
    receipt_path = results.paths(ident)["receipt"]
    receipts.precheck(args.command, args.targets, yahoo.warning_codes(key), receipt_path, args.max_chars)
    results.prune(args.ttl_days)
    outcomes, stopped = [], False
    for target in args.targets:
        if stopped:
            outcomes.append((target, "not_attempted", None, None))
            continue
        status, found, observed, stop = observe(key, target, args)
        outcomes.append((target, status, found, observed))
        stopped = stop
    document, full, table, records, previews = assemble(args, outcomes, ident)
    if table is None and records is None:
        document["file"] = None
    try:
        results.publish(ident, full, table=table, records=records)
        document["receipt_path"] = receipt_path
    except receipts.LocalIO as exc:
        document = saving_failed(document, exc)
    document = receipts.ordered(document, receipts.DOCUMENT_ORDER)
    printed = receipts.fit(document, args.max_chars, lambda i: previews[i])
    return printed, receipts.exit_code(printed)


def saving_failed(document, exc):
    """Nothing was saved, so no path is named; a target that returned data now reports local_io, and a rate limit already met keeps its own code."""
    document.pop("receipt_path", None)
    document["file"] = None
    for result in document["results"]:
        if result["status"] in ("ok", "empty"):
            result["status"] = "error"
            result.pop("data", None)
            result["error"] = receipts.failure("local_io", exc, exc.fix)
    document["status"] = receipts.document_status([r["status"] for r in document["results"]])
    return document
