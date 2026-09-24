"""Leaf declarations and everything derived from them: the parser, --help, schema, statuses and exit codes."""

import argparse
import os
import re
from pathlib import Path

from transport import Failure

LEAVES = []
GROUPS = {
    "schema": "Describe commands, arguments, defaults and output shapes offline",
    "doctor": "Check Python, curl and the observation store offline",
    "search": "Find securities by name or ticker",
    "read": "Read saved observations again with the original command's selectors, without a new request",
    "screen": "Finviz stock screener: filters, signals, columns and screening runs",
    "stock": "One company or ETF: overview sections, earnings, forecast, dividends, revenue, short interest, options, filings, statements, prices, ETF holdings",
    "groups": "Sector, industry, country and capitalization groups",
    "market": "Futures, forex and crypto quotes and performance, market maps and bubbles",
    "calendar": "Earnings, dividend, economic and earnings-season calendars",
    "news": "News headlines, Market Pulse explanations and Finviz-hosted articles",
    "insiders": "Insider trades across the market",
}
DEFAULT_STORE = str(Path.home() / ".cache/finviz-skill/observations.sqlite3")
DEFAULT_MAX_CHARS = 20000
SMALLEST_DOCUMENT = 200
OPERATIONAL = [
    (("--max-chars",), dict(type=int, default=DEFAULT_MAX_CHARS, help="Output budget in characters, at least 200. A result over it shows the records that fit, reports status partial and names a continuation command that reads the rest of the same selection.")),
    (("--store",), dict(default=os.environ.get("FINVIZ_STORE", DEFAULT_STORE), help="SQLite observation store; read needs the same path to find earlier IDs.")),
]
RECORD_SELECTORS = [
    (("--filter",), dict(default=None, help="Case-insensitive substring; keeps records whose own values or scalar lists contain it.")),
    (("--fields",), dict(default=None, help="Comma-separated record fields to keep; an unknown name is refused with the available ones.")),
    (("--start",), dict(type=int, default=0, help="Zero-based position among the records the selection matched; continuation and next commands set it.")),
    (("--limit",), dict(type=int, default=None, help="Records to show from --start; without it each collection's own default window applies (schema lists it).")),
]
EXIT_CODES = {"ok": 0, "invalid": 2, "access_restricted": 5, "upstream": 6, "empty": 7, "partial": 8, "too_large": 9}
STATUSES = {
    "ok": "the requested range was shown in full; a selection that matched nothing is ok with coverage.matched 0",
    "partial": "usable records with a stated gap: coverage.cut is budget (continuation reads the rest), a target failed (its error), or the source left a gap (warnings)",
    "empty": "the source returned no records; not proof that the data does not exist",
    "too_large": "not one record fits --max-chars, or the context alone does not; error.fix names a projection or a raw window that fits",
    "error": "no usable result; error.code and error.fix say what to do",
}
ENVELOPE = {
    "target": "the ticker, query or identifier this result answers",
    "request": "the arguments the command used, after defaults",
    "id": "saved observation ID; read ID returns it again with the same selectors and no new request",
    "observed_at": "UTC time this CLI received the response; not a market or reporting time",
    "source": "url, requested_url, http_status and redirects (each hop's own id); pages or dependencies when several responses built the result",
    "conditions": "the source parameters you chose: {requested, status: confirmed|not_applied|unverified, evidence}; HTTP 200 alone never confirms one",
    "coverage": "per collection: received from the source, matched by the selection, shown here, start, cut (default, limit or budget when something matched was left out), source_total when the source states one; keyed by section when the command has several",
    "continuation": "document level: the command (arguments after finviz.py) that shows the rest of the requested range when the budget cut it, one per cut section; following it to the end equals the unbudgeted answer",
    "next": "after the requested range was shown in full: the command that reads further matched records from the store, or the next source page as a new observation; absent when neither exists, which does not prove completeness",
    "data": "the context fields followed by each shown collection as a list of records; other_sections counts the collections not shown",
    "warnings": "limitations that affect how the data can be used",
    "error": "{code, message, fix}; fix is a command or an instruction that resolves it",
}


class Collection:
    """A list of records inside one observation, how it is ordered and the window a default answer shows."""

    def __init__(self, records, order="source order", reverse=False, default=None, local=(), key=None):
        self.records, self.order, self.reverse, self.default, self.local, self.key = records, order, reverse, default, list(local), key


class Selector:
    """A selector that applies to one collection only: an argparse option and the function that narrows or reshapes its records."""

    def __init__(self, flags, options, apply):
        self.flags, self.options, self.apply = flags, options, apply
        self.dest = options.get("dest") or flags[0].lstrip("-").replace("-", "_")


class Leaf:
    def __init__(self, group, name, help, fn, args, collections, sections, context, units, targets, paging):
        self.group, self.name, self.help, self.fn, self.args = group, name, help, fn, list(args)
        self.collections, self.sections, self.context, self.units = dict(collections or {}), list(sections or list(collections or {})[:1]), dict(context or {}), dict(units or {})
        self.targets, self.paging = targets, paging

    @property
    def path(self):
        return self.group + (" " + self.name if self.name else "")

    @property
    def multi(self):
        return len(self.collections) > 1

    def locals(self):
        return [(name, selector) for name, collection in self.collections.items() for selector in collection.local]


def leaf(group, name=None, *, help, args=(), collections=None, sections=None, context=None, units=None, targets=None, paging=None):
    """Register a command. `collections` maps a name to its Collection; `sections` are the collections shown by default when there are several; `context` maps the non-record data fields to their meaning; `units` maps a numeric field to its unit; `targets` names a positional list that yields one result per value; `paging` is the dest of the argument that asks the source for another page."""

    def register(fn):
        LEAVES.append(Leaf(group, name, help, fn, args, collections, sections, context, units, targets, paging))
        return fn

    return register


def condition(requested, status="unverified", evidence=None):
    return {"requested": requested, "status": status, "evidence": evidence}


def request_of(args, item):
    """The source arguments a result was fetched with, after defaults; stored so read and next commands can rebuild the request."""
    found = {}
    for flags, options in item.args:
        dest = options.get("dest") or flags[0].lstrip("-").replace("-", "_")
        if dest != item.targets and getattr(args, dest, None) is not None:
            found[dest] = getattr(args, dest)
    if item.multi:
        found["sections"] = args.sections
    return found


def find(path):
    return next((item for item in LEAVES if item.path == path), None)


# ---- parser ------------------------------------------------------------------------------------------------------------


class Formatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


class Parser(argparse.ArgumentParser):
    """One JSON document on stdout is the contract; an argument error is one too, pointing at the command that refused it."""

    def error(self, message):
        fix = "Correct the arguments; " + self.prog + " --help lists them and schema " + self.prog.removeprefix("finviz.py").strip() + " gives their defaults and choices."
        flag = re.search(r"argument (--[\w-]+).*expected one argument", message)
        if flag:  # a value such as -marketcap reads as an option unless it is attached with =
            fix = "Attach a value that starts with - using =, as in " + flag[1] + "=-VALUE. " + fix
        raise Failure("invalid_argument", message, fix)


def without(options, *keys):
    return {k: v for k, v in options.items() if k not in keys}


def selector_specs(item):
    """The selectors a leaf's records accept: the four record selectors, its collections' own selectors and, with several collections, --sections."""
    if not item.collections:
        return []
    specs = list(RECORD_SELECTORS)
    for name, selector in item.locals():
        specs.append((selector.flags, dict(selector.options, help=selector.options["help"] + (" Applies to " + name + "." if item.multi else ""))))
    return specs


def sections_spec(item):
    names = ", ".join(item.collections)
    return (("--sections",), dict(default=",".join(item.sections), help="Comma-separated collections to show from this one response: " + names + ". With several, --limit applies to each and --filter, --fields and --start are refused."))


def add(parser, specs):
    for flags, options in specs:
        parser.add_argument(*flags, help=options["help"].replace("%", "%%"), **without(options, "help"))


def epilog(item):
    shown = ", ".join(item.collections) if item.collections else "context only"
    return "Collections: " + shown + ". Full contract: schema " + item.path + ". --max-chars and --store are accepted here too; finviz.py --help explains them."


def build_parser():
    parser = Parser(prog="finviz.py", description="Read public Finviz data. stdout: one JSON document; stderr: diagnostics. `schema [GROUP [LEAF]]` describes every command offline.", formatter_class=Formatter, epilog="--max-chars and --store may be written before GROUP or after the command.")
    hidden = argparse.ArgumentParser(add_help=False)
    for flags, options in OPERATIONAL:
        parser.add_argument(*flags, help=options["help"].replace("%", "%%"), **without(options, "help"))
        hidden.add_argument(*flags, help=argparse.SUPPRESS, default=argparse.SUPPRESS, **without(options, "help", "default"))
    groups = parser.add_subparsers(dest="group", metavar="GROUP", parser_class=Parser, required=True)
    by_group = {}
    for item in LEAVES:
        by_group.setdefault(item.group, []).append(item)
    for name, items in by_group.items():
        if items[0].name is None:
            leaf_parser(groups, items[0], name, hidden, "finviz.py " + name)
            continue
        group = groups.add_parser(name, help=GROUPS[name], description=GROUPS[name] + ".", formatter_class=Formatter, prog="finviz.py " + name)
        leaves = group.add_subparsers(dest="leaf", metavar="LEAF", parser_class=Parser, required=True)
        for item in items:
            leaf_parser(leaves, item, item.name, hidden, "finviz.py " + item.path)
    return parser


def leaf_parser(subparsers, item, name, hidden, prog):
    sub = subparsers.add_parser(name, help=item.help if item.name else GROUPS[item.group], description=item.help, parents=[hidden], formatter_class=Formatter, epilog=epilog(item), prog=prog)
    add(sub, item.args)
    add(sub, selector_specs(item))
    if item.multi:
        add(sub, [sections_spec(item)])
    return sub


def selector_parser(item):
    """What read accepts after the ids of an observation made by `item`: its selectors, none of the arguments that shaped the request."""
    parser = Parser(prog="finviz.py read", add_help=False)
    add(parser, selector_specs(item))
    return parser


def subparser(parser, item):
    group = parser._subparsers._group_actions[0].choices[item.group]
    return group if item.name is None else group._subparsers._group_actions[0].choices[item.name]


def describe(actions):
    described = {}
    for action in actions:
        if action.help is argparse.SUPPRESS or (action.option_strings and action.option_strings[0] == "-h"):
            continue
        name = action.option_strings[0] if action.option_strings else action.dest
        described[name] = {"help": action.help, "default": None if action.default is argparse.SUPPRESS else action.default, "choices": list(action.choices) if action.choices else None, "required": bool(action.required) if action.option_strings else action.nargs not in ("?", "*")}
    return described


def leaf_schema(item):
    parser = build_parser()
    actions = subparser(parser, item)._actions + [a for a in parser._actions if a.option_strings]
    data = {"command": item.path, "description": item.help, "arguments": describe(actions)}
    if item.context:
        data["context"] = item.context
    if item.collections:
        data["collections"] = {name: {"records": c.records, "order": c.order + (" (the source publishes the reverse; it is served turned around)" if c.reverse else ""), "default_window": c.default, "always_kept_by_fields": c.key, "selectors": [s.flags[0] for s in c.local]} for name, c in item.collections.items()}
    if item.multi:
        data["default_sections"] = item.sections
    if item.units:
        data["units"] = item.units
    if item.paging:
        data["source_paging"] = "--" + item.paging.replace("_", "-") + " asks the source for another page, a new observation; --start and --limit move within the records already received"
    data["statuses"], data["exit_codes"] = STATUSES, EXIT_CODES
    return data


def root_schema():
    groups = {}
    for item in LEAVES:
        groups.setdefault(item.group, {})[item.name or ""] = item.help
    return {"groups": groups, "group_purposes": GROUPS, "operational_options": describe(build_parser()._actions[1:3]), "transport_limits": "connect timeout, request timeout and response size come from FINVIZ_CONNECT_TIMEOUT, FINVIZ_TIMEOUT and FINVIZ_MAX_BYTES; doctor reports the values in force", "envelope": ENVELOPE, "statuses": STATUSES, "exit_codes": EXIT_CODES, "usage": "finviz.py [--max-chars N] [--store PATH] GROUP [LEAF] [arguments]"}


def leaf_of(args):
    return next(item for item in LEAVES if item.group == args.group and item.name == getattr(args, "leaf", None))


def path_in(words):
    """The command named in argv, skipping option values: an option before GROUP must not hide which leaf refused an argument."""
    groups = {item.group for item in LEAVES}
    for index, word in enumerate(words):
        if word in groups and (index == 0 or not words[index - 1].startswith("--") or "=" in words[index - 1] or words[index - 1] in ("-h", "--help")):
            nxt = words[index + 1] if index + 1 < len(words) else None
            if find(word + " " + str(nxt)):
                return word + " " + nxt
            if find(word):
                return word
            return word
    return None
