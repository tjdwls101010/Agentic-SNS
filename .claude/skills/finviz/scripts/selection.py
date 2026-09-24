"""One selection rule for every collection, the rendered result, and the commands that continue or extend it."""

import json
import shlex

import contract
from transport import Failure, now


def searchable(record):
    """The text --filter matches: a record's own values and scalar lists, not the objects nested inside it."""
    parts = []
    for value in record.values() if isinstance(record, dict) else [record]:
        if isinstance(value, list):
            parts += [str(v) for v in value if not isinstance(v, (list, dict))]
        elif not isinstance(value, dict):
            parts.append(str(value))
    return " ".join(parts).lower()


class Picked:
    """One collection after selection and before the budget: the requested range and how it relates to what was received."""

    def __init__(self, records, received, matched, start, bound, cut, absent=False):
        self.records, self.received, self.matched, self.start, self.bound, self.cut, self.absent = records, received, matched, start, bound, cut, absent


def pick(result, item, name, sel):
    """Declared order, --filter, the collection's own selectors, --start, the window (--limit or the default), then --fields."""
    collection = item.collections[name]
    if name not in (result.get("collections") or {}):
        return Picked([], 0, 0, 0, None, None, absent=True)
    records = list(result["collections"][name])
    received = len(records)
    if collection.reverse:
        records.reverse()
    if sel.filter:
        term = sel.filter.lower()
        records = [r for r in records if term in searchable(r)]
    for selector in collection.local:
        records = selector.apply(records, getattr(sel, selector.dest, selector.options.get("default")), result.get("context") or {})
    matched = len(records)
    start = sel.start or 0
    bound = sel.limit if sel.limit is not None else collection.default
    window = records[start:]
    cut = None
    if bound is not None and len(window) > bound:
        window, cut = window[:bound], "limit" if sel.limit is not None else "default"
    if sel.fields:
        fields = [f.strip() for f in sel.fields.split(",") if f.strip()]
        known = list(dict.fromkeys(k for r in records if isinstance(r, dict) for k in r))
        missing = [f for f in fields if f not in known] if records else []
        if missing:
            raise Failure("invalid_fields", "Unknown fields in " + name + ": " + ", ".join(missing) + ".", "Available fields: " + ", ".join(known) + ".")
        keep = ([collection.key] if collection.key and collection.key not in fields else []) + fields + (["observation_id"] if "observation_id" in known and "observation_id" not in fields else [])
        window = [{f: r.get(f) for f in keep} for r in window]
    return Picked(window, received, matched, start, bound, cut)


def coverage(p, shown, totals=None):
    if p.absent:
        return {"absent": True}
    found = {"received": p.received, "matched": p.matched, "shown": shown, "start": p.start}
    if shown < len(p.records):
        found["cut"] = "budget"
    elif p.cut:
        found["cut"] = p.cut
    return found | (totals or {})


class View:
    """What one result prints: an observation (or a plain offline result), the leaf that describes it, the selectors and the sections to show."""

    def __init__(self, result, item, sel, sections, ops):
        self.result, self.item, self.sel, self.sections, self.ops = result, item, sel, list(sections), ops
        self.picked, self.raw = {}, None
        if self.result.get("status") != "error":
            try:
                self.picked = {name: pick(result, item, name, sel) for name in self.sections}
            except Failure as exc:
                self.result = dict(result, status="error", error=exc.info())
                self.picked = {}

    @property
    def upper(self):
        if self.raw is not None:
            return len(self.raw["text"])
        return max((len(p.records) for p in self.picked.values()), default=0)


def is_empty(value):
    if isinstance(value, dict):
        return not value or all(is_empty(v) for v in value.values())
    if isinstance(value, list):
        return not value
    return value is None or value == ""


ORDER = ["target", "request", "id", "observed_at", "source", "conditions", "coverage", "next", "status", "data", "chars", "warnings", "error"]


def render(view, cap):
    result, item = view.result, view.item
    out = {"target": result.get("target"), "request": request_of(view), "id": result.get("id"), "observed_at": result.get("observed_at") or now(), "source": {k: v for k, v in (result.get("source") or {}).items() if k != "headers" and v not in (None, [], False, {})}, "conditions": result.get("conditions"), "status": result.get("status", "ok"), "warnings": list(result.get("warnings") or [])}
    if result.get("error"):
        out["error"] = result["error"]  # a partial result names the failure that left its gap
    if out["status"] == "error":
        return ordered(out)
    if view.raw is not None:
        return render_raw(view, out, cap)
    context = result.get("context") or {}
    data = dict(context)
    covered, cut, following = {}, False, []
    for name, p in view.picked.items():
        shown = min(len(p.records), cap)
        data[name] = p.records[:shown]
        covered[name] = coverage(p, shown, (result.get("totals") or {}).get(name))
        cut = cut or shown < len(p.records)
        if p.absent:
            continue
        if p.received and not p.matched:
            out["warnings"].append("The selection matched 0 of the " + str(p.received) + " " + name + " received.")
        if shown == len(p.records):
            following.append(next_command(view, name, p, shown))
    if item.multi:
        others = {name: len(records) for name, records in (result.get("collections") or {}).items() if name not in view.picked}
        if others:
            data["other_sections"] = others
    out["data"] = data
    if result.get("export"):  # rows went to a file: the result reports the file and what the selection wrote
        data["export"], out["coverage"] = result["export"], result.get("export_coverage")
        if result.get("next_page") and view.item.paging:
            out["next"] = source_command(view, result["next_page"])
        if not (result.get("export_coverage") or {}).get("received") and out["status"] == "ok":
            out["status"] = "empty"
    elif view.picked:
        out["coverage"] = covered if item.multi else next(iter(covered.values()))
        if all(p.absent or p.received == 0 for p in view.picked.values()) and out["status"] == "ok":
            out["status"] = "empty"
    elif is_empty(context) and out["status"] == "ok" and result.get("id") and not result.get("failed"):
        out["status"] = "empty"
    if out["status"] == "empty":
        out["warnings"].append("The source returned no records; this is not proof that the data does not exist.")
    if cut and out["status"] in ("ok", "empty"):
        out["status"] = "partial"
    following = [c for c in following if c]
    if following:
        out["next"] = following[0] if len(following) == 1 else following
    return ordered(out)


def render_raw(view, out, cap):
    raw = view.raw
    out["data"] = raw["text"][:cap]
    out["chars"] = {"received": raw["total"], "start": raw["start"], "shown": min(cap, len(raw["text"]))}
    if cap < len(raw["text"]):
        out["status"] = "partial" if out["status"] == "ok" else out["status"]
    elif raw["start"] + len(raw["text"]) < raw["total"]:
        out["next"] = command(["read", view.result["id"], "--raw", "--chars", str(raw["start"] + len(raw["text"])) + "-"], view.ops)
    if raw["total"] == 0 and out["status"] == "ok":
        out["status"] = "empty"
    return ordered(out)


def ordered(out):
    return {k: out[k] for k in ORDER if k in out and (out[k] not in (None, {}, []) or k == "data")}


def request_of(view):
    found = {k: v for k, v in (view.result.get("request") or {}).items() if v is not None}
    if view.item.collections:
        found |= {k: v for k, v in selector_values(view.item, view.sel).items()}
    return found


def selector_values(item, sel):
    """The selectors that differ from their defaults, by option name: the part of a selection a command has to carry."""
    values = {}
    for flags, options in contract.RECORD_SELECTORS + [(s.flags, s.options) for _, s in item.locals()]:
        dest = options.get("dest") or flags[0].lstrip("-").replace("-", "_")
        value = getattr(sel, dest, options.get("default"))
        if value != options.get("default") and value is not None:
            values[flags[0]] = value
    return values


def tokens(values):
    found = []
    for flag, value in values.items():
        if value is True:
            found.append(flag)
        elif value is not False:
            found += [flag, str(value)]
    return found


def command(words, ops):
    if ops is not None and getattr(ops, "max_chars", contract.DEFAULT_MAX_CHARS) != contract.DEFAULT_MAX_CHARS:
        words = words + ["--max-chars", str(ops.max_chars)]
    if ops is not None and getattr(ops, "store", None) not in (None, contract.OPERATIONAL[1][1]["default"]):
        words = words + ["--store", ops.store]
    return shlex.join(words)


def read_command(ids, item, sel, section, start, limit, ops):
    values = {k: v for k, v in selector_values(item, sel).items() if k not in ("--start", "--limit")}
    words = ["read", *ids] + (["--section", section] if item.multi else []) + tokens(values)
    if start:
        words += ["--start", str(start)]
    if limit is not None:
        words += ["--limit", str(limit)]
    return command(words, ops)


def continuation(views, cap):
    """One command per section the budget cut, covering every result that shows it: they were cut to the same count, so one --start continues all of them."""
    found = []
    raw = next((v for v in views if v.raw is not None and cap < len(v.raw["text"])), None)
    if raw is not None:
        begin = raw.raw["start"] + cap
        return [command(["read", raw.result["id"], "--raw", "--chars", str(begin) + "-" + str(raw.raw["start"] + len(raw.raw["text"]))], raw.ops)]
    first = next((v for v in views if v.picked), None)
    if first is None:
        return found
    for name in first.sections:
        showing = [v for v in views if name in v.picked and not v.picked[name].absent]
        if not any(cap < len(v.picked[name].records) for v in showing):
            continue
        p = next(v.picked[name] for v in showing if cap < len(v.picked[name].records))
        remaining = p.bound - cap if p.bound is not None else None
        found.append(read_command([v.result["id"] for v in showing if v.result.get("id")], first.item, first.sel, name, p.start + cap, remaining, first.ops))
    return found


def next_command(view, name, p, shown):
    """After the requested range: further matched records in the store first, then the source's next page."""
    end = p.start + shown
    if p.matched > end and view.result.get("id"):
        return read_command([view.result["id"]], view.item, view.sel, name, end, view.sel.limit, view.ops)
    page = view.result.get("next_page")
    if page and view.item.paging and name == next(iter(view.item.collections)):
        return source_command(view, page)
    return None


def source_command(view, page):
    """The same leaf asking the source for its next page: the request's arguments with the paging argument moved on, and the selectors minus the position."""
    item, request = view.item, dict(view.result.get("request") or {})
    request[item.paging] = page
    if request.get("out"):
        request["append"] = True  # the next page adds to the file this run wrote
    words = item.path.split()
    if item.targets and view.result.get("target"):
        words.append(str(view.result["target"]))
    for flags, options in item.args:
        dest = options.get("dest") or flags[0].lstrip("-").replace("-", "_")
        if dest == item.targets or dest not in request:
            continue
        value = request[dest]
        if not flags[0].startswith("-"):
            words += [str(v) for v in value] if isinstance(value, list) else [str(value)]
        elif value is True:
            words.append(flags[0])
        elif value not in (None, False) and value != options.get("default"):
            words += [flags[0], str(value)]
    values = {k: v for k, v in selector_values(item, view.sel).items() if k not in ("--start", "--limit")}
    if item.multi and view.sections != item.sections:
        values["--sections"] = ",".join(view.sections)
    return command(words + tokens(values), view.ops)


def dumps(doc):
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
