"""Read-only Finviz CLI: one JSON document on stdout, diagnostics on stderr. `schema` describes every command from the parser itself."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlencode

import output
from transport import Failure, Store, fetch

LEAVES = []
GROUPS = {
    "schema": "Describe commands, arguments, defaults and output shapes offline",
    "doctor": "Check Python, curl and the observation store offline",
    "search": "Find securities by name or ticker",
    "screen": "Finviz stock screener: filters, signals, columns, views and screening runs",
    "stock": "One company or ETF: snapshot, profile, ratings, news, insiders, ownership, flows, earnings, forecast, dividends, revenue, short interest, options, filings, statements, prices",
    "groups": "Sector, industry, country and capitalization groups",
    "market": "Futures, forex and crypto quotes, market maps and bubbles",
    "calendar": "Earnings, dividend, economic and earnings-season calendars",
    "news": "News headlines, Market Pulse explanations and Finviz-hosted articles",
    "insiders": "Insider trades across the market",
    "open": "Read any supported finviz.com URL with the generic extractor",
    "read": "Read a saved observation in slices without a new request",
    "inspect": "List the JSON pointers inside a saved observation",
}
COMMON = [
    (("--max-chars",), dict(type=int, default=20000, help="Maximum output characters; larger results become a too_large error with narrowing advice, never a truncated document.")),
    (("--filter",), dict(default=None, help="Case-insensitive substring; keeps only records whose JSON contains it (discovery lists and record lists).")),
    (("--fields",), dict(default=None, help="Comma-separated record fields to keep; unknown names return the available ones.")),
    (("--limit",), dict(type=int, default=None, help="Maximum records to output; the observation keeps everything received.")),
    (("--store",), dict(default=os.environ.get("FINVIZ_STORE", str(Path.home() / ".cache/finviz-skill/observations.sqlite3")), help="SQLite observation store; use the same path to read earlier IDs.")),
    (("--connect-timeout",), dict(type=float, default=10, help="Connection timeout in seconds.")),
    (("--timeout",), dict(type=float, default=60, help="Per-request timeout in seconds.")),
    (("--max-bytes",), dict(type=int, default=16 * 1024 * 1024, help="Maximum response size in bytes.")),
]


class Leaf:
    def __init__(self, group, name, help, output, fn, args, narrow, records, targets):
        self.group, self.name, self.help, self.output, self.fn = group, name, help, output, fn
        self.args, self.narrow, self.records, self.targets = args, narrow, records, targets

    @property
    def path(self):
        return self.group + (" " + self.name if self.name else "")


def leaf(group, name=None, *, help, output, args=(), narrow=(), records=None, targets=None):
    """Register a command. `records` names the list inside data that --filter/--fields/--limit act on (None = data itself); `targets` names a positional list that yields one result per value."""

    def register(fn):
        LEAVES.append(Leaf(group, name, help, output, fn, list(args), list(narrow), records, targets))
        return fn

    return register


def condition(requested, status="unverified", evidence=None):
    return {"requested": requested, "status": status, "evidence": evidence}


class Context:
    """Per-invocation transport and the observations waiting to be saved."""

    def __init__(self, args, store):
        self.args, self.store, self.pending = args, store, []

    def observe(self, url):
        try:
            obs = fetch(url, self.args)
        except Failure as exc:
            if exc.observation is not None:
                self.pending.append(exc.observation)
            raise
        self.pending.append(obs)
        return obs

    def flush(self):
        for obs in self.pending:
            self.store.save(obs.result, obs.raw)
        self.pending = []


# ---- built-in leaves -------------------------------------------------------------------------------------------------


@leaf("search", help="Find security candidates by company name or ticker fragment.", args=[(("query",), dict(help="Company name or ticker fragment."))], output={"[]": "candidates as returned: ticker, company, exchange and any extra source fields"}, narrow=["--limit", "--filter"])
def search(ctx, args, target):
    obs = ctx.observe("https://finviz.com/api/suggestions?" + urlencode({"input": args.query}))
    obs.result["target"] = args.query
    obs.result["data"] = obs.json()
    return obs.result


@leaf("doctor", help="Report the local Python, curl and store without contacting Finviz.", output={"python": "interpreter version", "curl": "curl version line", "store": "observation store path", "problems": "what to fix, if anything"})
def doctor(ctx, args, target):
    try:
        proc = subprocess.run(["curl", "--version"], capture_output=True, text=True)
        version = proc.stdout.splitlines()[0] if proc.stdout else proc.stderr.strip()
    except FileNotFoundError:
        version = None
    match = re.search(r"curl (\d+)\.(\d+)", version or "")
    problems = []
    if sys.version_info < (3, 11):
        problems.append("Python 3.11+ is required.")
    if not match or tuple(map(int, match.groups())) < (8, 4):
        problems.append("curl 8.4+ is required; found: " + str(version))
    result = output.plain("doctor", {"python": sys.version.split()[0], "curl": version, "store": str(ctx.store.path), "problems": problems})
    if problems:
        result["status"], result["error"] = "error", output.error_info("runtime", "; ".join(problems), "Install the listed requirements and rerun doctor.")
    return result


@leaf("read", help="Read a saved observation, or a JSON Pointer inside it, without a new request.", args=[(("id",), dict(help="Observation ID from an earlier result.")), (("--pointer",), dict(default="", help="JSON Pointer into the saved envelope, e.g. /data or /data/rows/0.")), (("--start",), dict(type=int, default=0, help="Zero-based start when the selected value is a list.")), (("--raw",), dict(action="store_true", help="Return the received response text instead of the extracted envelope."))], output={"*": "the selected value; source, conditions, coverage and status of the original observation are repeated so a slice keeps its context", "selection": "pointer, start, received (list length) and shown"})
def read(ctx, args, target):
    if args.pointer and not args.pointer.startswith("/"):
        raise Failure("invalid_pointer", "A JSON Pointer starts with '/'.", "Use a pointer from inspect, e.g. /data.")
    saved = ctx.store.get(args.id)
    result = {k: saved[k] for k in ("target", "id", "source", "conditions", "coverage", "continuation", "warnings") if saved.get(k) is not None}
    result["observed_at"], result["status"] = saved.get("observed_at"), "ok"
    if saved.get("status") == "error":
        result["warnings"] = result.get("warnings", []) + ["The original observation failed: " + saved["error"]["message"]]
    if args.raw:
        result["data"] = ctx.store.get(args.id, raw=True).decode("utf-8", errors="replace")
        return result
    value = saved
    for token in args.pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        try:
            value = value[int(token)] if isinstance(value, list) else value[token]
        except (KeyError, IndexError, ValueError, TypeError):
            raise Failure("invalid_pointer", "Nothing at " + args.pointer + ".", "Run inspect " + args.id + " to list available pointers.")
    selection = {"pointer": args.pointer or "/", "start": args.start}
    if isinstance(value, list):
        selection["received"] = len(value)
        value = value[args.start :]
    result["data"], result["selection"] = value, selection
    return result


@leaf("inspect", help="List pointers, types and sizes inside a saved observation without printing its records.", args=[(("id",), dict(help="Observation ID from an earlier result.")), (("--depth",), dict(type=int, default=4, help="How many levels to descend."))], output={"[]": "{pointer, type, count} for each container; lists show their first item's shape"})
def inspect(ctx, args, target):
    saved = ctx.store.get(args.id)

    def walk(value, pointer, depth):
        entries = [{"pointer": pointer or "/", "type": type(value).__name__, "count": len(value) if isinstance(value, (dict, list)) else None}]
        if depth < args.depth:
            if isinstance(value, dict):
                for key, child in value.items():
                    entries += walk(child, pointer + "/" + str(key).replace("~", "~0").replace("/", "~1"), depth + 1)
            elif isinstance(value, list) and value:
                entries += walk(value[0], pointer + "/0", depth + 1)
        return entries

    result = output.plain(args.id, walk(saved, "", 0))
    result["id"] = args.id
    return result


@leaf("schema", help="Describe groups, commands, arguments with defaults, output shapes, statuses and exit codes; offline.", args=[(("scope",), dict(nargs="*", help="Optional GROUP or GROUP LEAF to describe in detail."))], output={"groups": "group -> command -> one-line purpose (unscoped)", "arguments": "name -> {help, default, choices, required} for the scoped command, shared options included", "output": "data key -> meaning for the scoped command", "narrowing": "arguments that reduce output size for the scoped command", "envelope": "meaning of each result field", "statuses": "result statuses", "exit_codes": "process exit code per outcome"})
def schema(ctx, args, target):
    parser = build_parser()
    scope = args.scope
    if not scope:
        groups = {}
        for item in LEAVES:
            groups.setdefault(item.group, {})[item.name or ""] = item.help
        data = {"groups": groups, "group_purposes": GROUPS, "shared_options": describe_actions(parser._actions), "envelope": output.ENVELOPE, "statuses": output.STATUSES, "exit_codes": output.EXIT_CODES, "usage": "finviz.py [shared options] GROUP [LEAF] [arguments]; shared options are also accepted after the command."}
        return output.plain("schema", data)
    matches = [item for item in LEAVES if item.group == scope[0] and (len(scope) == 1 or item.name == scope[1])]
    if not matches:
        raise Failure("invalid_scope", "No command " + " ".join(scope) + ".", "Run schema without arguments to list groups and commands.")
    if len(matches) > 1:
        return output.plain(" ".join(scope), {"commands": {m.name: m.help for m in matches}, "purpose": GROUPS[scope[0]]})
    item = matches[0]
    sub = leaf_parser(parser, item)
    actions = [a for a in sub._actions if a.help is not argparse.SUPPRESS] + [a for a in parser._actions if a.option_strings and a.help is not argparse.SUPPRESS]
    data = {"command": item.path, "description": item.help, "arguments": describe_actions(actions), "output": item.output, "narrowing": item.narrow, "records": item.records, "statuses": output.STATUSES, "exit_codes": output.EXIT_CODES}
    return output.plain(item.path, data)


# ---- parser -----------------------------------------------------------------------------------------------------------


class Formatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


def describe_actions(actions):
    described = {}
    for action in actions:
        if not action.option_strings and action.dest == "group":
            continue
        if action.option_strings and action.option_strings[0] in ("-h",):
            continue
        name = action.option_strings[0] if action.option_strings else action.dest
        described[name] = {"help": action.help, "default": None if action.default is argparse.SUPPRESS else action.default, "choices": list(action.choices) if action.choices else None, "required": bool(action.required) if action.option_strings else action.nargs not in ("?", "*")}
    return described


def leaf_parser(parser, item):
    group = parser._subparsers._group_actions[0].choices[item.group]
    if item.name is None:
        return group
    return group._subparsers._group_actions[0].choices[item.name]


def epilog(item):
    return "Output keys: " + ", ".join(item.output) + ". Full contract: schema " + item.path + ". Shared options (--fields, --limit, --filter, --max-chars, --store, timeouts) are accepted here too; finviz.py --help explains them."


def build_parser():
    parser = argparse.ArgumentParser(prog="finviz.py", description="Read public Finviz data. stdout: one JSON document; stderr: diagnostics. `schema [GROUP [LEAF]]` describes every command offline.", formatter_class=Formatter, epilog="Shared options may be written before GROUP or after the command.")
    hidden = argparse.ArgumentParser(add_help=False)
    for flags, options in COMMON:
        parser.add_argument(*flags, **options)
        hidden.add_argument(*flags, **dict(options, default=argparse.SUPPRESS, help=argparse.SUPPRESS))
    groups = parser.add_subparsers(dest="group", metavar="GROUP", required=True)
    by_group = {}
    for item in LEAVES:
        by_group.setdefault(item.group, []).append(item)
    for name, items in by_group.items():
        if items[0].name is None:
            sub = groups.add_parser(name, help=GROUPS[name], description=items[0].help, parents=[hidden], formatter_class=Formatter, epilog=epilog(items[0]))
            for flags, options in items[0].args:
                sub.add_argument(*flags, **options)
            continue
        group = groups.add_parser(name, help=GROUPS[name], description=GROUPS[name] + ".", formatter_class=Formatter)
        leaves = group.add_subparsers(dest="leaf", metavar="LEAF", required=True)
        for item in items:
            sub = leaves.add_parser(item.name, help=item.help, description=item.help, parents=[hidden], formatter_class=Formatter, epilog=epilog(item))
            for flags, options in item.args:
                sub.add_argument(*flags, **options)
    return parser


def find_leaf(args):
    return next(item for item in LEAVES if item.group == args.group and item.name == getattr(args, "leaf", None))


def request_of(args, item):
    names = [(flags[0].lstrip("-").replace("-", "_")) for flags, _ in item.args]
    return {name: getattr(args, name, None) for name in names if name != item.targets}


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    item = find_leaf(args)
    if args.max_chars <= 0 or args.timeout <= 0 or args.connect_timeout <= 0 or args.max_bytes <= 0 or (args.limit is not None and args.limit < 0):
        parser.error("limits must be positive")
    try:
        store = Store(args.store)
    except OSError as exc:
        output.diagnostic("cannot open store: " + str(exc))
        return output.EXIT_CODES["invalid"]
    ctx = Context(args, store)
    targets = getattr(args, item.targets) if item.targets else [None]
    results = []
    for target in targets:
        try:
            result = item.fn(ctx, args, target)
            result.setdefault("target", target)
        except Failure as exc:
            result = exc.observation.result if exc.observation is not None else output.plain(target)
            result["target"], result["status"], result["error"] = target if target is not None else result.get("target", item.path), "error", exc.info()
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            obs = ctx.pending[-1] if ctx.pending else None
            result = obs.result if obs is not None else output.plain(target)
            result["target"], result["status"], result["error"] = target if target is not None else result.get("target", item.path), "error", output.error_info("parse_error", type(exc).__name__ + ": " + str(exc)[:200], "The provider structure may have changed; read the saved raw response with read ID --raw.")
        finally:
            ctx.flush()
        results.append(output.finalize(result, args, item, request_of(args, item)))
    return output.emit(results, args, item)


if __name__ == "__main__":
    sys.exit(main())
