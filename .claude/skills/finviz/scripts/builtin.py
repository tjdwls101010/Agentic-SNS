"""Offline and source-agnostic commands: schema, doctor, search and read."""

import argparse
import os
import re
import subprocess
import sys
from urllib.parse import urlencode

import contract
from contract import Collection, leaf
from selection import View
from transport import Failure, SETTINGS, now


def plain(target, context):
    return {"target": target, "id": None, "observed_at": now(), "status": "ok", "context": context, "collections": {}}


@leaf("search", help="Find security candidates by company name or ticker fragment.", args=[(("query",), dict(metavar="QUERY", help="Company name or ticker fragment."))], collections={"candidates": Collection("as returned: ticker, company, exchange and any extra source fields")})
def search(ctx, args, target):
    obs = ctx.observe("https://finviz.com/api/suggestions?" + urlencode({"input": args.query}))
    obs.result["target"] = args.query
    found = obs.json()
    if not isinstance(found, list):
        raise obs.fail("structure_changed", "The suggestions API did not return a list.", "Read the saved raw response with read ID --raw.")
    obs.result["collections"] = {"candidates": found}
    return obs.result


@leaf(
    "doctor",
    help="Report the local Python, curl, store and transport limits without contacting Finviz.",
    context={"python": "interpreter version", "curl": "curl version line", "store": "observation store path", "transport": "the connect timeout, request timeout and response size limit in force, and which of FINVIZ_CONNECT_TIMEOUT, FINVIZ_TIMEOUT and FINVIZ_MAX_BYTES set them", "problems": "what to fix, if anything"},
)
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
    limits = {name: getattr(ctx.transport, name) for _, (name, _, _) in sorted(SETTINGS.items())}
    result = plain("doctor", {"python": sys.version.split()[0], "curl": version, "store": str(ctx.store.path), "transport": dict(limits, set_by=[v for v in SETTINGS if os.environ.get(v)] or "defaults"), "problems": problems})
    if problems:
        result["status"], result["error"] = "error", {"code": "runtime", "message": "; ".join(problems), "fix": "Install the listed requirements and rerun doctor."}
    return result


@leaf(
    "schema",
    help="Describe groups, commands, arguments with defaults, collections, units, statuses and exit codes; offline.",
    args=[(("scope",), dict(nargs="*", metavar="SCOPE", help="Optional GROUP or GROUP LEAF to describe in detail."))],
    context={
        "groups": "group -> command -> one-line purpose (unscoped)", "arguments": "name -> {help, default, choices, required} for the scoped command",
        "context": "non-record data fields and their meaning", "collections": "name -> {records, order, default_window, selectors}",
        "units": "numeric field -> unit, where the unit was confirmed against the page that displays it", "envelope": "meaning of each result field",
        "statuses": "result statuses", "exit_codes": "process exit code per outcome",
    },
)
def schema(ctx, args, target):
    scope = args.scope
    if not scope:
        return plain("schema", contract.root_schema())
    matches = [item for item in contract.LEAVES if item.group == scope[0] and (len(scope) == 1 or item.name == scope[1])]
    if not matches or len(scope) > 2:
        raise Failure("invalid_scope", "No command " + " ".join(scope) + ".", "Run schema without arguments to list groups and commands.")
    if len(matches) > 1:
        return plain(" ".join(scope), {"commands": {m.name: m.help for m in matches}, "purpose": contract.GROUPS[scope[0]]})
    return plain(matches[0].path, contract.leaf_schema(matches[0]))


@leaf(
    "read",
    help="Show saved observations again with the selectors of the command that made them, or the raw response in character windows; no new request.",
    args=[
        (("ids",), dict(nargs="+", metavar="ID", help="Observation IDs from earlier results; several must come from the same command.")),
        (("--section",), dict(default=None, help="The one collection to show from an observation whose command has several; defaults to the sections that command showed.")),
        (("--raw",), dict(action="store_true", help="Return the received response text instead of the extracted records.")),
        (("--chars",), dict(default=None, help="Character range START-END of the raw text, e.g. 0-20000 or 20000- for the rest; END is exclusive. Needs --raw.")),
    ],
    context={"*": "the original command's context and collections, selected with that command's own selectors (--filter, --fields, --start, --limit and its collection selectors), with its status, warnings and conditions carried over"},
)
def read(ctx, args, target):
    raise AssertionError("read is dispatched by read_views")


def read_views(ctx, args, extras):
    if args.chars and not args.raw:
        raise Failure("invalid_argument", "--chars selects characters of the raw response text.", "Add --raw, or select records with the original command's selectors.")
    if args.raw:
        if len(args.ids) > 1 or extras or args.section:
            raise Failure("invalid_argument", "--raw reads one observation's response text; selectors and --section apply to records.", "read " + args.ids[0] + " --raw [--chars START-END]")
        return [raw_view(ctx, args)]
    stored = [ctx.store.get(ident) for ident in args.ids]
    leaves = {s.get("leaf") for s in stored}
    if len(leaves) > 1:
        raise Failure("invalid_argument", "These observations come from different commands: " + ", ".join(sorted(str(x) for x in leaves)) + ".", "Read them in separate calls, one command's ids at a time.")
    origin = contract.find(next(iter(leaves)) or "")
    if origin is None or "collections" not in stored[0]:
        raise Failure("unsupported_observation", "Observation " + args.ids[0] + " was not saved in the form read selects from.", "read " + args.ids[0] + " --raw returns the response it received.")
    accepted = ", ".join(flag for flags, _ in contract.selector_specs(origin) for flag in flags[:1])
    try:
        sel = contract.selector_parser(origin).parse_args(extras)
    except Failure as exc:
        raise Failure("invalid_argument", exc.message, "read takes the selectors of " + origin.path + (": " + accepted if accepted else ": none") + ", plus --section and --raw.")
    if args.section and args.section not in origin.collections:
        raise Failure("invalid_argument", "No section " + args.section + " in " + origin.path + ".", "Use one of: " + ", ".join(origin.collections) + ".")
    for s in stored:
        if s.get("status") == "error" and extras:
            raise Failure("invalid_argument", "Observation " + s["id"] + " failed before any records were extracted, so there is nothing to select.", "read " + s["id"] + " --raw returns the response it received.")
    views = []
    for s in stored:
        if args.section:
            sections = [args.section]
        elif origin.multi:
            sections = [x for x in str((s.get("request") or {}).get("sections") or ",".join(origin.sections)).split(",") if x in origin.collections]
        else:
            sections = list(origin.collections)
        check_locals(origin, sections, extras)
        if s.get("status") == "error":  # a replay keeps the failure, so several ids read together stay partial
            error = dict(s.get("error") or {})
            error["fix"] = (error.get("fix") or "").rstrip(".") + ". read " + s["id"] + " --raw returns the response it received."
            s = dict(s, error=error)
            sections = []
        views.append(View(s, origin, sel, sections, args))
    return views


def raw_view(ctx, args):
    saved = ctx.store.get(args.ids[0])
    text = ctx.store.get(args.ids[0], raw=True).decode("utf-8", errors="replace")
    start, end = char_range(args.chars, len(text))
    result = dict(saved, status="ok" if saved.get("status") != "partial" else "partial", collections={}, context={})
    if saved.get("status") == "error":
        error = saved.get("error") or {}
        result["warnings"] = list(saved.get("warnings") or []) + ["The original observation failed (" + str(error.get("code")) + ": " + str(error.get("message")) + ")."]
    view = View(result, contract.find("read"), argparse.Namespace(), [], args)
    view.raw = {"text": text[start:end], "total": len(text), "start": start}
    return view


def char_range(spec, total):
    """START-END character offsets into one string; END is exclusive and may be left open."""
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d*)\s*", spec or "0-")
    if not match:
        raise Failure("invalid_argument", "--chars takes START-END character offsets.", "Write --chars 0-20000 for the first window, or --chars 20000- for everything after it.")
    start = int(match.group(1))
    end = min(int(match.group(2)), total) if match.group(2) else total
    if not total:
        return 0, 0
    if start >= total:
        raise Failure("invalid_argument", "--chars starts at " + str(start) + " but the text is " + str(total) + " characters.", "Start below " + str(total) + ".")
    if end <= start:
        raise Failure("invalid_argument", "--chars END must be greater than START.", "Write an exclusive END above START, e.g. --chars " + str(start) + "-" + str(start + 20000) + ".")
    return start, end


def given(flags, words):
    # 성진: 명시 여부를 argv 문자열로 판정한다; 옵션 값이 플래그와 같은 문자열이면 오판한다. argparse가 명시 여부를 알려 주는 경로가 생기면 그것으로 바꾼다.
    return any(w == f or w.startswith(f + "=") for w in words for f in flags)


def check_locals(item, sections, words):
    """A collection's own selector given while that collection is not shown would be ignored; refuse it instead."""
    for name, selector in item.locals():
        if name not in sections and given(selector.flags, words):
            raise Failure("invalid_argument", selector.flags[0] + " applies to " + name + ", which is not among the sections shown (" + ", ".join(sections) + ").", "Add --sections " + name + " (or read ID --section " + name + ").")
