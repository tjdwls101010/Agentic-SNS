"""Offline discovery: the command catalogue and each leaf's contract, read from the same declarations execution uses.

The command surface (parsers, groups, commands, shared arguments, exit codes) arrives from cli.py; what the output
means is owned here, and what the values mean comes from each command's Yahoo dataset.
"""
import argparse
import contextlib

from yfinance_skill import budget, yahoo
from yfinance_skill.envelope import STATUSES, InputError, ordered, result

ENVELOPE = {
    "target": "the symbol, query or key this result answers",
    "id": "saved observation id; every adapter return is saved before local selection, so a result that did not fit is still reachable with read",
    "observed_at": "when this CLI received the response",
    "source_time": "the time the source itself put on this data, where it supplies one; after a close it can be hours before observed_at",
    "status": "see statuses",
    "conditions": "only the arguments this response carries evidence for: {requested, status: confirmed|not_applied|unverified, evidence}. A successful call is not evidence that a condition was applied",
    "coverage": "received = rows the adapter returned, shown = rows printed (or written with --out), kept = which end a limit kept, truncated_by = leaf_default (this leaf's own window, status ok) or budget (your range did not fit, status partial), fields = how many of the available fields the projection kept",
    "data": "the selected value; tables are {index, columns, data, index_names, column_names}. With --out: {out, rows, columns, first, last}, where rows is this target's share of the file and columns may become a count when the summary would not fit",
    "warnings": "limitations that affect how this data can be used",
    "error": "{code, message, fix}",
}


def shared_arguments(root, sample, reader, defaults, applies):
    """Each shared argument once, with where it applies; a leaf's own window is in that leaf's default_window."""
    found = {}
    for action in [*root._actions, *sample._actions, *reader._actions]:
        if action.dest not in applies or action.option_strings[0] in found:
            continue
        default = defaults.get(action.dest) if action.default == argparse.SUPPRESS else action.default
        if action.dest == "limit":
            default = "the command's default_window.rows"
        found[action.option_strings[0]] = {"help": action.help, "default": default, "applies_to": applies[action.dest]}
    return found


def describe(parser, item, applies, pointer):
    defaults = argparse.Namespace(group=item.group, leaf=item.name, **{a.dest: a.default for a in parser._actions if a.dest != "help"})
    for fill in (item.command.defaults, item.dataset.prepare):
        if fill:
            with contextlib.suppress(InputError):
                fill(defaults)
    arguments = {}
    for action in parser._actions:
        if action.dest == "help" or action.dest in applies:
            continue
        name = action.option_strings[0] if action.option_strings else action.dest
        value = getattr(defaults, action.dest, action.default)
        required = bool(action.required) if action.option_strings else action.nargs not in ("?", "*")
        spec = {"help": action.help, "default": value, "choices": list(action.choices) if action.choices else None, "required": required or None}
        arguments[name] = {k: v for k, v in spec.items() if v is not None and v is not False}  # an absent key means null or false
    described = {
        "command": item.path,
        "description": item.purpose,
        "arguments": arguments,
        # 성진: 공통 인자·봉투·상태·종료코드는 리프마다 같다. 49번 싣는 순간 밀도가 아니라 반복이고, 리프 고유의 계약을 그 안에 묻는다.
        "common": pointer,
        "default_window": {"rows": item.limit, "fields": list(item.fields) or None, "limit_keeps": item.limit_keeps()},
        "units": item.units or None,
        "interpretation": item.interpretation or None,
        "limits": item.limits or None,
        "narrowing": list(item.narrow) or None,
        "gotchas": list(item.gotchas) or None,
        "notes": parser.epilog,
    }
    return {k: v for k, v in described.items() if v is not None}


def schema_data(args, parsers, root, groups, commands, defaults, applies, pointer, exit_codes):
    scope = tuple(args.scope)
    if len(scope) > 2 or (scope and scope[0] not in groups):
        raise InputError("schema expects an existing GROUP [LEAF]; run schema with no scope to list the groups.")
    if len(scope) == 1 and scope[0] in commands:
        scope = (scope[0], "")  # a group whose only command is the group itself
    if len(scope) == 2:
        command = commands.get(scope[0] + (" " + scope[1] if scope[1] else ""))
        if command is None:
            raise InputError(f"No command {' '.join(scope)}; use schema {scope[0]} to list its commands.")
        data = describe(parsers[scope], yahoo.bind(command), applies, pointer)
        if args.filter:
            data["arguments"] = {k: v for k, v in data["arguments"].items() if args.filter.lower() in (k + str(v)).lower()}
        return data
    listed = {}
    for command in commands.values():
        if scope and command.group != scope[0]:
            continue
        listed.setdefault(command.group, {})[command.name or ""] = command.purpose
    found = listed.get(scope[0], {}) if scope else listed
    matched = {k: v for k, v in found.items() if args.filter.lower() in (k + str(v)).lower()}
    # 성진: 걸러낸 목록이 돌려주지 않은 그룹까지 설명하면, 좁히려고 준 --filter가 출력을 거의 줄이지 못한다.
    shown_groups = {scope[0]} if scope else set(matched)
    described = {"commands": matched, "group_purposes": {k: v for k, v in groups.items() if k in shown_groups},
                 "next": "schema GROUP LEAF for that command's arguments, default window, units and known limits"}
    if not scope and not args.filter:
        # 성진: --filter를 준 호출은 명령을 찾는 중이다. 그때까지 봉투 설명을 함께 실으면 좁히려는 시도가 같은 예산에 다시 걸린다.
        described["common_arguments"] = shared_arguments(root, next(iter(parsers.values())), parsers["read"], defaults, applies)
        described["output"] = {"envelope": ENVELOPE, "statuses": STATUSES, "exit_codes": exit_codes}
    return described


def run(args, parsers, root, *, groups, commands, defaults, applies, pointer, exit_codes):
    """Describe the requested scope and print it; returns what budget.emit reports."""
    data = schema_data(args, parsers, root, groups, commands, defaults, applies, pointer, exit_codes)
    return budget.emit([ordered(result("schema", data))], args, None, {"scope": args.scope}, scoped=bool(args.scope))
