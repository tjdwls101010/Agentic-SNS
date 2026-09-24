"""Read-only Finviz CLI: one JSON document on stdout, silence on stderr. Parse, run the leaf per target, save, select, fit the budget, print."""

import re
import sqlite3
import sys

import budget
import builtin
import contract
from selection import View, dumps
from store import Store
from transport import Failure, fetch, now, settings


class Context:
    """Per-invocation transport and the observations waiting to be saved."""

    def __init__(self, args, store, item):
        self.args, self.store, self.item, self.pending = args, store, item, []
        self.transport = settings()

    def observe(self, url):
        try:
            obs = fetch(url, self.transport, keep=self.pending.append)
        except Failure as exc:
            if exc.observation is not None:
                self.pending.append(exc.observation)
            raise
        self.pending.append(obs)
        return obs

    def flush(self, request):
        for obs in self.pending:
            obs.result["leaf"] = self.item.path
            obs.result.setdefault("request", request)
            if obs.result.get("status") == "ok" and obs.result.get("collections") and not any(obs.result["collections"].values()):
                obs.result["status"] = "empty"
            self.store.save(obs.result, obs.raw)
        self.pending = []


def load_modules():
    """Command modules register their leaves on import; the parser is built after all of them are loaded."""
    for name in ("screener", "stock", "markets", "calendars", "news", "insiders"):
        __import__(name)


def sections_of(item, args, words):
    if not item.collections:
        return []
    sections = [s.strip() for s in args.sections.split(",") if s.strip()] if item.multi else list(item.collections)
    unknown = [s for s in sections if s not in item.collections]
    if unknown or not sections:
        raise Failure("invalid_argument", "Unknown sections: " + ", ".join(unknown) + ".", "Use --sections with any of: " + ", ".join(item.collections) + ".")
    if len(sections) > 1 and (args.filter or args.fields or args.start):
        raise Failure("invalid_argument", "--filter, --fields and --start select within one section; several sections carry different fields.", "Ask for one section, e.g. --sections " + sections[0] + ", and read the others from the same id with read ID --section NAME.")
    builtin.check_locals(item, sections, words)
    return sections


def check_numbers(args):
    if args.max_chars < contract.SMALLEST_DOCUMENT:
        raise Failure("invalid_argument", "--max-chars must be at least " + str(contract.SMALLEST_DOCUMENT) + ", the size of the shortest document that can state an error.", "Pass --max-chars 200 or more.")
    if (getattr(args, "limit", None) or 0) < 0 or (getattr(args, "start", None) or 0) < 0:
        raise Failure("invalid_argument", "--start and --limit may not be negative.", "Pass 0 or a positive count.")


def argument_error(exc, words):
    path = contract.path_in(words)
    error = exc.info()
    flag = re.search(r"argument (--[\w-]+).*expected one argument", error["message"])
    if flag and flag[1] in words and words.index(flag[1]) + 1 < len(words) and words[words.index(flag[1]) + 1].startswith("-"):
        error["fix"] = error["fix"].replace(flag[1] + "=-VALUE", flag[1] + "=" + words[words.index(flag[1]) + 1])
    if path and "finviz.py --help" in error["fix"] and path != "finviz.py":
        error["fix"] = "Correct the arguments; finviz.py " + path + " --help lists them and schema " + path + " gives their defaults and choices."
    return {"status": "error", "results": [{"target": path or "finviz.py", "status": "error", "error": error}]}


def main(argv=None):
    load_modules()
    parser = contract.build_parser()
    words = list(argv if argv is not None else sys.argv[1:])
    try:
        args, extras = parser.parse_known_args(words)
        item = contract.leaf_of(args)
        if extras and item.path != "read":
            raise Failure("invalid_argument", "unrecognized arguments: " + " ".join(extras), "Correct the arguments; finviz.py " + item.path + " --help lists the ones " + item.path + " accepts and schema " + item.path + " gives their defaults and choices.")
        settings()
        check_numbers(args)
        sections = sections_of(item, args, words) if item.path != "read" else []
    except Failure as exc:
        print(dumps(argument_error(exc, words)))
        return contract.EXIT_CODES["invalid"]
    try:
        store = Store(args.store)
    except (OSError, sqlite3.Error) as exc:
        result = {"target": item.path, "observed_at": now(), "status": "error", "error": {"code": "local_io", "message": "Cannot open the observation store " + args.store + ": " + str(exc), "fix": "Pass a writable file path with --store or FINVIZ_STORE."}}
        text = dumps({"status": "error", "results": [result]})
        print(text)
        return budget.exit_code(text)
    ctx = Context(args, store, item)
    if item.path == "read":
        try:
            views = builtin.read_views(ctx, args, extras)
        except Failure as exc:
            views = [View({"target": " ".join(args.ids), "observed_at": now(), "status": "error", "error": exc.info()}, item, args, [], args)]
    else:
        views = [run(ctx, item, args, target, sections) for target in (getattr(args, item.targets) if item.targets else [None])]
    text = budget.fit(views, args.max_chars)
    print(text)
    return budget.exit_code(text)


def run(ctx, item, args, target, sections):
    request = contract.request_of(args, item)
    try:
        result = item.fn(ctx, args, target)
        result.setdefault("target", target)
    except Failure as exc:
        exc.record()
        result = exc.observation.result if exc.observation is not None else {"target": target, "id": None, "observed_at": now()}
        result.update(target=target if target is not None else result.get("target", item.path), status="error", error=exc.info())
    except (OSError, sqlite3.Error) as exc:
        result = {"target": target if target is not None else item.path, "observed_at": now(), "status": "error", "error": {"code": "local_io", "message": type(exc).__name__ + ": " + str(exc)[:200], "fix": "Check the --out path, the --store path and local disk permissions."}}
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        obs = ctx.pending[-1] if ctx.pending else None
        result = obs.result if obs is not None else {"target": target, "observed_at": now()}
        result.update(target=target if target is not None else result.get("target", item.path), status="error", error={"code": "parse_error", "message": type(exc).__name__ + ": " + str(exc)[:200], "fix": "The provider structure may have changed; read the saved raw response with read ID --raw."})
    try:
        ctx.flush(request)
    except (OSError, sqlite3.Error) as exc:
        result = dict(result, status="error", error={"code": "local_io", "message": "Saving the observation failed: " + str(exc)[:200], "fix": "Check the --store path and disk space."})
    result.setdefault("request", request)
    return View(result, item, args, [] if result.get("export") else sections, args)


if __name__ == "__main__":
    sys.exit(main())
