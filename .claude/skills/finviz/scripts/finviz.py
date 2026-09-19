"""Read-only Finviz CLI: one JSON document on stdout, diagnostics on stderr. `schema` describes every command from the parser itself."""

import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from urllib.parse import urlencode

import output
from transport import Failure, Observation, Store, fetch

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
    (("--max-chars",), dict(type=int, default=20000, help="Maximum output characters, at least 200: a shorter budget could not hold the error document that reports it. A larger result becomes a too_large error naming how to narrow it, never a truncated document.")),
    (("--filter",), dict(default=None, help="Case-insensitive substring; keeps records whose own values or scalar lists contain it (nested objects such as option lists are not searched).")),
    (("--fields",), dict(default=None, help="Comma-separated record fields to keep; unknown names return the available ones. Where the data is a mapping, these are the fields inside each entry and --keys chooses the entries.")),
    (("--keys",), dict(default=None, help="Comma-separated entries to keep where the data is a mapping, e.g. instruments or series names; unknown names return the available ones.")),
    (("--limit",), dict(type=int, default=None, help="Maximum records to output; the observation keeps everything received.")),
    (("--store",), dict(default=os.environ.get("FINVIZ_STORE", str(Path.home() / ".cache/finviz-skill/observations.sqlite3")), help="SQLite observation store; use the same path to read earlier IDs.")),
]
# 성진: 전송 손잡이는 운영자의 것이지 Finviz 질문에 답하는 모델의 선택지가 아니다. 환경 변수로 받고 doctor가 실효값을 보고한다.
TRANSPORT = {"FINVIZ_CONNECT_TIMEOUT": ("connect_timeout", float, 10.0), "FINVIZ_TIMEOUT": ("timeout", float, 60.0), "FINVIZ_MAX_BYTES": ("max_bytes", int, 16 * 1024 * 1024)}


def transport_settings():
    values = {}
    for variable, (name, kind, fallback) in TRANSPORT.items():
        raw = os.environ.get(variable)
        try:
            values[name] = kind(raw) if raw not in (None, "") else fallback
        except ValueError:
            raise Failure("invalid_argument", variable + " is not a number: " + raw, "Set " + variable + " to a positive number or unset it to use " + str(fallback) + ".")
        if values[name] <= 0:
            raise Failure("invalid_argument", variable + " must be positive.", "Set " + variable + " above zero or unset it to use " + str(fallback) + ".")
    return argparse.Namespace(**values)


class Leaf:
    def __init__(self, group, name, help, output, fn, args, narrow, records, targets, default_limit, keyed, context, recent, window):
        self.group, self.name, self.help, self.output, self.fn = group, name, help, output, fn
        self.args, self.narrow, self.records, self.targets, self.default_limit = args, narrow, records, targets, default_limit
        self.keyed, self.context, self.recent, self.window = keyed, list(context), recent, window

    @property
    def path(self):
        return self.group + (" " + self.name if self.name else "")


def leaf(group, name=None, *, help, output, args=(), narrow=(), records=None, targets=None, default_limit=None, keyed=False, context=(), recent=False, window=None):
    """Register a command. `records` names the collection inside data (None = data itself); `keyed` enables selection of mapping keys; `targets` names a positional list that yields one result per value; `context` names the data fields a slice of this result cannot be interpreted without, which read carries alongside the slice; `recent` marks a series published oldest first, where a limit keeps the newest records instead of the first; `window` is the leaf's own default range, applied to the printed result only, so the saved observation still holds everything the source returned."""

    def register(fn):
        LEAVES.append(Leaf(group, name, help, output, fn, list(args), list(narrow), records, targets, default_limit, keyed, context, recent, window))
        return fn

    return register


# 성진: 리프 35개가 같은 문장을 다시 싣지 않도록, 값을 바꿀 조건은 무인자 schema에만 붙인다.
SHARED_NOTES = {
    "--max-chars": "The default 20,000 is a safety boundary, not the working limit: each command's own default range is what keeps a result to one screen, and this catches the cases where that range is still too wide. Raise it when you deliberately want a whole catalogue, option chain or page in one document; the too_large message names the exact size that would fit.",
    "--store": "Observations outlive the call that made them, so a later read or inspect needs the same path; the default keeps them in the user cache.",
}


def condition(requested, status="unverified", evidence=None):
    return {"requested": requested, "status": status, "evidence": evidence}


class Context:
    """Per-invocation transport and the observations waiting to be saved."""

    def __init__(self, args, store, item=None):
        self.args, self.store, self.pending, self.item = args, store, [], item
        self.transport = transport_settings()

    def observe(self, url):
        try:
            obs = fetch(url, self.transport, keep=self.pending.append)
        except Failure as exc:
            if exc.observation is not None:
                self.pending.append(exc.observation)
            raise
        self.pending.append(obs)
        for pending in self.pending:
            if self.item is not None:
                pending.result.setdefault("command", self.item.path)  # store-only: finalize never prints it, and read uses it to find this leaf's context fields
        return obs

    def replay(self, ident, url):
        """Run this leaf's extractor over a response already in the store. The result keeps the original id and observed_at: it is another reading of that observation, not a new one, so it is not saved again."""
        saved = self.store.get(ident)
        seen = (saved.get("source") or {}).get("url")
        if seen != url:
            raise Failure("invalid_argument", "Observation " + ident + " is " + str(seen) + ", not " + url + ".", "Pass an id observed from this same page, or drop --from to request it.")
        obs = Observation(url, (saved.get("source") or {}).get("requested_url") or url, (saved.get("source") or {}).get("http_status"), {}, self.store.get(ident, raw=True), (saved.get("source") or {}).get("redirects") or [], True)
        obs.id, obs.result["id"], obs.result["observed_at"] = ident, ident, saved.get("observed_at")
        return obs

    def flush(self):
        for obs in self.pending:
            if self.item is not None:
                output.settle_empty(obs.result, self.item)
            self.store.save(obs.result, obs.raw)
        self.pending = []


# ---- built-in leaves -------------------------------------------------------------------------------------------------


@leaf("search", help="Find security candidates by company name or ticker fragment.", args=[(("query",), dict(metavar="QUERY", help="Company name or ticker fragment."))], output={"list of candidates": "as returned: ticker, company, exchange and any extra source fields"}, narrow=["--limit", "--filter"])
def search(ctx, args, target):
    obs = ctx.observe("https://finviz.com/api/suggestions?" + urlencode({"input": args.query}))
    obs.result["target"] = args.query
    obs.result["data"] = obs.json()
    return obs.result


@leaf("doctor", help="Report the local Python, curl and store without contacting Finviz.", output={"python": "interpreter version", "curl": "curl version line", "store": "observation store path", "transport": "the connect timeout, request timeout and response size limit in force, and which of FINVIZ_CONNECT_TIMEOUT, FINVIZ_TIMEOUT and FINVIZ_MAX_BYTES set them", "problems": "what to fix, if anything"})
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
    limits = {name: getattr(ctx.transport, name) for _, (name, _, _) in sorted(TRANSPORT.items())}
    result = output.plain("doctor", {"python": sys.version.split()[0], "curl": version, "store": str(ctx.store.path), "transport": dict(limits, set_by=[v for v in TRANSPORT if os.environ.get(v)] or "defaults"), "problems": problems})
    if problems:
        result["status"], result["error"] = "error", output.error_info("runtime", "; ".join(problems), "Install the listed requirements and rerun doctor.")
    return result


@leaf("read", help="Read a saved observation, or a JSON Pointer inside it, without a new request.", args=[(("id",), dict(metavar="ID", help="Observation ID from an earlier result.")), (("--pointer",), dict(default="", help="JSON Pointer into the saved envelope, e.g. /data or /data/rows/0; / or empty is the whole envelope, /source/headers the response headers.")), (("--start",), dict(type=int, default=0, help="Zero-based start among list entries or object keys at the selected pointer; nested collections are not sliced.")), (("--raw",), dict(action="store_true", help="Return the received response text instead of the extracted envelope.")), (("--chars",), dict(default=None, help="Character range START-END of the raw text, e.g. 0-20000 or 20000- for the rest; END is exclusive and continuation names the next window. Needs --raw, because --start and --limit cut containers rather than one string."))], output={"*": "the selected value; source, conditions, coverage and the status of the original observation are repeated so a slice keeps what it was observed with", "selection": "pointer, start, received (list length, key count or raw character count), shown, and context: the data fields this leaf declares a slice cannot be read without"}, narrow=["--pointer", "--start", "--limit", "--chars"], keyed=True)
def read(ctx, args, target):
    if args.pointer and not args.pointer.startswith("/"):
        raise Failure("invalid_pointer", "A JSON Pointer starts with '/'.", "Use a pointer from inspect, e.g. /data.")
    if args.chars and not args.raw:
        raise Failure("invalid_argument", "--chars selects characters of the raw response text.", "Add --raw, or select the extracted envelope with --pointer, --start and --limit.")
    pointer = "" if args.pointer == "/" else args.pointer
    item = next(entry for entry in LEAVES if entry.path == "read")
    saved = ctx.store.get(args.id)
    if not pointer.startswith("/source/headers") and isinstance(saved.get("source"), dict):
        saved["source"] = {k: v for k, v in saved["source"].items() if k != "headers"}
    result = {k: saved[k] for k in ("target", "id", "source", "conditions", "coverage", "continuation", "warnings") if saved.get(k) is not None}
    result["observed_at"], result["status"] = saved.get("observed_at"), saved.get("status", "ok")
    if saved.get("status") == "error":
        # 성진: error를 그대로 실으면 finalize가 data를 떨어뜨려 실패한 관측을 읽을 수 없게 된다; 상태는 ok로 두고 경고로 알린다.
        result["status"] = "ok"
        result["warnings"] = result.get("warnings", []) + ["The original observation failed: " + saved["error"]["message"]]
    if args.raw:
        text = ctx.store.get(args.id, raw=True).decode("utf-8", errors="replace")
        start, end = char_range(args.chars, len(text))
        result["data"] = text[start:end]
        result["selection"] = {"pointer": "/raw", "start": start, "received": len(text), "shown": end - start}
        if end < len(text):
            result["continuation"] = {"chars": str(end) + "-" + str(end + max(end - start, 1))}
        return result
    value = saved
    for token in pointer.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        try:
            value = value[int(token)] if isinstance(value, list) else value[token]
        except (KeyError, IndexError, ValueError, TypeError):
            raise Failure("invalid_pointer", "Nothing at " + args.pointer + ".", "Run inspect " + args.id + " to list available pointers.")
    selection = {"pointer": pointer or "/", "start": args.start}
    if isinstance(value, (list, dict)):
        selection["received"] = len(value)
        value = value[args.start :] if isinstance(value, list) else {k: value[k] for k in list(value)[args.start :]}
        # 성진: 선택은 공유 경로가 한다. read가 따로 자르면 --keys·--filter의 순서와 coverage가 다른 명령과 어긋난다.
        value = output.select({"data": value, "coverage": result.get("coverage")}, args, item)["data"]
    if isinstance(value, (list, dict)):
        selection["shown"] = len(value)
        result["coverage"] = dict(result.get("coverage") or {}, received=selection["received"], shown=len(value))
    if pointer.startswith("/data/") and isinstance(saved.get("data"), dict):
        origin = next((item for item in LEAVES if item.path == saved.get("command")), None)
        carried = {f: saved["data"][f] for f in (origin.context if origin else ()) if f in saved["data"] and pointer != "/data/" + f}
        if carried:
            selection["context"] = carried
    result["data"], result["selection"], result["selection_applied"] = value, selection, True
    return result


def char_range(spec, total):
    """START-END character offsets into one string; END is exclusive and may be left open."""
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d*)\s*", spec or "0-")
    if not match:
        raise Failure("invalid_argument", "--chars takes START-END character offsets.", "Write --chars 0-20000 for the first window, or --chars 20000- for everything after it.")
    start = int(match.group(1))
    end = min(int(match.group(2)), total) if match.group(2) else total
    if not total:
        return 0, 0  # an empty response reads as empty rather than as a bad range
    if start >= total:
        raise Failure("invalid_argument", "--chars starts at " + str(start) + " but the text is " + str(total) + " characters.", "Start below " + str(total) + "; the selection reports received as the full length.")
    if end <= start:
        raise Failure("invalid_argument", "--chars END must be greater than START.", "Write an exclusive END above START, e.g. --chars " + str(start) + "-" + str(start + 20000) + ".")
    return start, end


@leaf("inspect", help="List the pointers, types and sizes inside a saved observation's data without printing its records.", args=[(("id",), dict(metavar="ID", help="Observation ID from an earlier result.")), (("--depth",), dict(type=int, default=4, help="How many levels to descend."))], output={"list of containers": "{pointer, type, count} under /data, plus any collection inside /source such as pages or dependencies; lists show their first item's shape. The envelope's own fields are described by schema, not counted here"})
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

    # 성진: 봉투 포인터는 schema의 envelope가 이미 소유한 지식이다; inspect는 리프마다 모양이 다른 /data와 /source의 동적 컬렉션만 센다.
    entries = walk(saved.get("data"), "/data", 0) if saved.get("data") is not None else []
    for key, value in (saved.get("source") or {}).items():
        if isinstance(value, (dict, list)):
            entries += walk(value, "/source/" + key, 0)
    result = output.plain(args.id, entries)
    result["id"] = args.id
    return result


@leaf("schema", help="Describe groups, commands, arguments with defaults, output shapes, statuses and exit codes; offline.", args=[(("scope",), dict(nargs="*", metavar="SCOPE", help="Optional GROUP or GROUP LEAF to describe in detail."))], output={"groups": "group -> command -> one-line purpose (unscoped)", "arguments": "name -> {help, default, choices, required} for the scoped command, shared options included", "output": "data key -> meaning for the scoped command", "narrowing": "arguments that reduce output size for the scoped command", "envelope": "meaning of each result field", "statuses": "result statuses", "exit_codes": "process exit code per outcome"})
def schema(ctx, args, target):
    parser = build_parser()
    scope = args.scope
    if not scope:
        groups = {}
        for item in LEAVES:
            groups.setdefault(item.group, {})[item.name or ""] = item.help
        shared = describe_actions(parser._actions)
        for name, note in SHARED_NOTES.items():
            shared[name]["when_to_change"] = note
        data = {"groups": groups, "group_purposes": GROUPS, "shared_options": shared, "transport_limits": "connect timeout, request timeout and response size come from FINVIZ_CONNECT_TIMEOUT, FINVIZ_TIMEOUT and FINVIZ_MAX_BYTES; doctor reports the values in force", "envelope": output.ENVELOPE, "statuses": output.STATUSES, "exit_codes": output.EXIT_CODES, "usage": "finviz.py [shared options] GROUP [LEAF] [arguments]; shared options are also accepted after the command."}
        return output.plain("schema", data)
    matches = [item for item in LEAVES if item.group == scope[0] and (len(scope) == 1 or item.name == scope[1])]
    if not matches:
        raise Failure("invalid_scope", "No command " + " ".join(scope) + ".", "Run schema without arguments to list groups and commands.")
    if len(matches) > 1:
        return output.plain(" ".join(scope), {"commands": {m.name: m.help for m in matches}, "purpose": GROUPS[scope[0]]})
    item = matches[0]
    sub = leaf_parser(parser, item)
    actions = [a for a in sub._actions if a.help is not argparse.SUPPRESS] + [a for a in parser._actions if a.option_strings and a.help is not argparse.SUPPRESS]
    data = {"command": item.path, "description": item.help, "arguments": describe_actions(actions), "output": item.output, "narrowing": item.narrow, "records": item.records, "default_limit": item.default_limit, "limit_keeps": "the newest records of a series published oldest first" if item.recent else "the first records in source order", "slice_context": item.context, "statuses": output.STATUSES, "exit_codes": output.EXIT_CODES}
    return output.plain(item.path, data)


# ---- parser -----------------------------------------------------------------------------------------------------------


class Formatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


class Parser(argparse.ArgumentParser):
    """The module promises one JSON document on stdout; an argument error is one too, with the same code and exit status as any other input error."""

    def error(self, message):
        raise Failure("invalid_argument", message, "Correct the arguments; " + self.prog + " --help lists them and schema describes their defaults and choices.")


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
    return "Output: " + ", ".join(item.output) + ("; without --limit the " + ("newest " if item.recent else "first ") + str(item.default_limit) + " records are kept and coverage reports the rest" if item.default_limit else "") + ". Full contract: schema " + item.path + ". Shared options (--fields, --keys, --limit, --filter, --max-chars, --store) are accepted here too; finviz.py --help explains them."


def build_parser():
    parser = Parser(prog="finviz.py", description="Read public Finviz data. stdout: one JSON document; stderr: diagnostics. `schema [GROUP [LEAF]]` describes every command offline.", formatter_class=Formatter, epilog="Shared options may be written before GROUP or after the command.")
    hidden = argparse.ArgumentParser(add_help=False, description="Shared options, accepted after the command as well as before GROUP.")
    for flags, options in COMMON:
        parser.add_argument(*flags, help=options["help"], **without(options, "help"))
        hidden.add_argument(*flags, help=argparse.SUPPRESS, default=argparse.SUPPRESS, **without(options, "help", "default"))
    groups = parser.add_subparsers(dest="group", metavar="GROUP", parser_class=Parser, required=True)
    by_group = {}
    for item in LEAVES:
        by_group.setdefault(item.group, []).append(item)
    for name, items in by_group.items():
        if items[0].name is None:
            sub = groups.add_parser(name, help=GROUPS[name], description=items[0].help, parents=[hidden], formatter_class=Formatter, epilog=epilog(items[0]))
            for flags, options in items[0].args:
                sub.add_argument(*flags, help=options["help"], **without(options, "help"))
            continue
        group = groups.add_parser(name, help=GROUPS[name], description=GROUPS[name] + ".", formatter_class=Formatter)
        leaves = group.add_subparsers(dest="leaf", metavar="LEAF", parser_class=Parser, required=True)
        for item in items:
            sub = leaves.add_parser(item.name, help=item.help, description=item.help, parents=[hidden], formatter_class=Formatter, epilog=epilog(item))
            for flags, options in item.args:
                sub.add_argument(*flags, help=options["help"], **without(options, "help"))
    return parser


def without(options, *keys):
    return {k: v for k, v in options.items() if k not in keys}


def find_leaf(args):
    return next(item for item in LEAVES if item.group == args.group and item.name == getattr(args, "leaf", None))


def request_of(args, item):
    names = [options.get("dest") or flags[0].lstrip("-").replace("-", "_") for flags, options in item.args]
    return {name: getattr(args, name, None) for name in names if name != item.targets}


def load_modules():
    """Command modules register their leaves on import; the parser is built after all of them are loaded."""
    sys.modules.setdefault("finviz", sys.modules[__name__])
    for name in ("screener", "stock", "markets", "feeds"):
        __import__(name)


def argument_error(failure, words):
    """Point the fix at the command that refused the argument: the root parser raises for a leaf's unrecognised flags too."""
    plain = [w for w in words if not w.startswith("-")]
    path = next((" ".join(plain[:count]) for count in (2, 1) if any(item.path == " ".join(plain[:count]) for item in LEAVES)), None)
    if path is None:
        return failure.info()
    return output.error_info(failure.code, failure.message, "Correct the arguments; finviz.py " + path + " --help lists the ones " + path + " accepts and schema " + path + " gives their defaults and choices.")


def main(argv=None):
    load_modules()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        item = find_leaf(args)
        transport_settings()
        if args.max_chars < output.SMALLEST_DOCUMENT or (args.limit is not None and args.limit < 0):
            # 성진: 오류 문서 자체가 들어갈 수 없는 예산을 받으면 그 뒤의 모든 응답이 계약을 어긴다; 경계를 받는 자리에서 거절한다.
            parser.error("--max-chars must be at least " + str(output.SMALLEST_DOCUMENT) + ", the size of the shortest document that can state an error, and --limit may not be negative")
    except Failure as exc:
        words = argv if argv is not None else sys.argv[1:]
        print(json.dumps({"status": "error", "results": [{"target": " ".join(words), "status": "error", "error": argument_error(exc, words)}]}, ensure_ascii=False, separators=(",", ":")))
        return output.EXIT_CODES["invalid"]
    try:
        store = Store(args.store)
    except (OSError, sqlite3.Error) as exc:
        result = output.plain(item.path)
        result["status"], result["error"] = "error", output.error_info("local_io", "Cannot open the observation store " + args.store + ": " + str(exc), "Pass a writable file path with --store or FINVIZ_STORE.")
        return output.emit([output.finalize(result, args, item, {})], args, item)
    ctx = Context(args, store, item)
    targets = getattr(args, item.targets) if item.targets else [None]
    results = []
    for target in targets:
        try:
            result = item.fn(ctx, args, target)
            result.setdefault("target", target)
        except Failure as exc:
            exc.record()
            result = exc.observation.result if exc.observation is not None else output.plain(target)
            result["target"], result["status"], result["error"] = target if target is not None else result.get("target", item.path), "error", exc.info()
        except (OSError, sqlite3.Error) as exc:
            result = output.plain(target)
            result["target"], result["status"], result["error"] = target if target is not None else item.path, "error", output.error_info("local_io", type(exc).__name__ + ": " + str(exc)[:200], "Check the --out path, the --store path and local disk permissions.")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            obs = ctx.pending[-1] if ctx.pending else None
            result = obs.result if obs is not None else output.plain(target)
            result["target"], result["status"], result["error"] = target if target is not None else result.get("target", item.path), "error", output.error_info("parse_error", type(exc).__name__ + ": " + str(exc)[:200], "The provider structure may have changed; read the saved raw response with read ID --raw.")
        finally:
            try:
                if isinstance(result, dict):
                    output.settle_empty(result, item)
                ctx.flush()
            except (OSError, sqlite3.Error) as exc:
                result = dict(result, status="error", error=output.error_info("local_io", "Saving the observation failed: " + str(exc)[:200], "Check the --store path and disk space."))
        results.append(output.finalize(result, args, item, request_of(args, item)))
    return output.emit(results, args, item)


if __name__ == "__main__":
    sys.exit(main())
