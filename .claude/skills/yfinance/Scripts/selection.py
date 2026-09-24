"""The selection every path shares: field projection, field listing and the row window.

It runs on the encoded value, so the first call and every later `read` of the same observation select through this one
function and cannot disagree about what a row or a field was.
"""
from encode import is_table, row_count
from envelope import InputError


# ---- field paths -------------------------------------------------------------------------------------------------


def dig(record, path):
    """Resolve a dotted field path. company news nests its article under content, so the only projection that reaches
    a title is content.title; a flat --fields could name nothing that actually reduced the payload."""
    value = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None, False
        value = value[part]
    return value, True


def paths_of(record, prefix="", depth=0):
    """Every dotted path a record offers: the nested objects as well as the scalars inside them.

    Listing only the leaves made a whole sub-object unselectable, so --fields content.thumbnail was refused as unknown
    while content.thumbnail.originalUrl was accepted — a reader cannot tell from the value which one a name is.
    """
    found = []
    for key, value in record.items():
        here = f"{prefix}{key}"
        found.append(here)
        if isinstance(value, dict) and value and depth < 3:
            found.extend(paths_of(value, here + ".", depth + 1))
    return found


def available_fields(data):
    if is_table(data):
        return [str(c) for c in data["columns"]]
    if isinstance(data, list) and data and all(isinstance(r, dict) for r in data):
        return list(dict.fromkeys(p for r in data for p in paths_of(r)))
    if isinstance(data, dict):
        return list(dict.fromkeys(paths_of(data)))
    return []


# ---- selection ---------------------------------------------------------------------------------------------------


def take_rows(data, keep, recent):
    """Keep `keep` rows from the end when the source publishes oldest first, otherwise from the start.

    The direction is the leaf's, never a global rule: a series printed oldest first loses its newest rows to a prefix
    cut, and one printed newest first loses its newest rows to a suffix cut. Both failures are silent.
    """
    if keep is None or row_count(data) is None or row_count(data) <= keep:
        return data, None
    side = "newest" if recent else "first"
    if is_table(data):
        rows = data["data"][-keep:] if recent else data["data"][:keep]
        index = data["index"][-keep:] if recent else data["index"][:keep]
        return dict(data, data=rows, index=index), side
    return (data[-keep:] if recent else data[:keep]), side


def project(data, fields):
    """Keep the named fields. Missing names are an error rather than a silent empty column."""
    if is_table(data):
        by_name = {str(c): i for i, c in enumerate(data["columns"])}
        missing = [f for f in fields if f not in by_name]
        if missing:
            raise InputError(f"Unknown fields {missing}; list this command's fields with --list-fields --filter TEXT.")
        keep = [by_name[f] for f in fields]
        return dict(data, columns=[data["columns"][i] for i in keep], data=[[row[i] for i in keep] for row in data["data"]])
    if isinstance(data, list) and data and all(isinstance(r, dict) for r in data):
        missing = [f for f in fields if not any(dig(r, f)[1] for r in data)]
        if missing:
            raise InputError(f"Unknown fields {missing}; list this command's fields with --list-fields --filter TEXT.")
        return [{f: dig(r, f)[0] for f in fields} for r in data]
    if isinstance(data, dict):
        resolved = {f: dig(data, f) for f in fields}
        missing = [f for f, (_, found) in resolved.items() if not found]
        if missing:
            raise InputError(f"Unknown fields {missing}; list this command's fields with --list-fields --filter TEXT.")
        return {f: value for f, (value, _) in resolved.items()}
    raise InputError("This result has no named fields to select; narrow it with --limit instead.")


def select(data, args, item, coverage=None, keep=None):
    """Apply --list-fields, the field projection and the row window, recording what was left out.

    `keep` overrides the row count so the budget can narrow an already-selected result without re-deciding the
    projection or the direction.
    """
    coverage = {} if coverage is None else coverage
    if getattr(args, "list_fields", False):
        term = (getattr(args, "filter", "") or "").lower()
        return [f for f in available_fields(data) if term in f.lower()], coverage
    received = row_count(data)
    if received is not None:
        coverage.setdefault("received", received)
    start = getattr(args, "row_start", 0) or 0
    if start and received is not None:
        if start >= received:
            raise InputError(f"--start {start} is past the {received} rows this observation holds; its last row is at {received - 1}.")
        data = dict(data, data=data["data"][start:], index=data["index"][start:]) if is_table(data) else data[start:]
        coverage["start"] = start

    requested = getattr(args, "fields", None)
    fields = requested or (list(item.fields) if item and item.fields else None)
    if fields:
        # 성진: 값이 전부 결측이어도 열 이름은 있다. 비었다고 투영을 건너뛰면 --fields가 조용히 무시되고
        # 요청하지 않은 열이 함께 돌아온다 — 선택이 적용됐다고 읽을 근거는 그대로 둔 채.
        offered = available_fields(data)
        if offered:
            if not requested:
                fields = [f for f in fields if f in offered]  # a default projection describes the common shape, not this target's exact one
            if fields:
                data = project(data, fields)
                coverage["fields"] = {"received": len(offered), "shown": len(fields), "source": "requested" if requested else "leaf_default"}
        elif requested:
            coverage["unverified_fields"] = requested  # nothing came back at all, so the names could not be checked against a real shape

    explicit = getattr(args, "limit", None)
    limit = keep if keep is not None else explicit if explicit is not None else (item.limit if item else None)
    # 성진: read는 관측을 앞에서부터 걸어 나가므로 창이 앞으로 간다. recent를 여기서도 적용하면 --start를 올려도 매번
    # 같은 꼬리가 나오고, 호출 수만 늘어난 채 앞쪽 행에는 영원히 닿지 못한다 — 합계만 보면 완독한 것처럼 보인다.
    paging = hasattr(args, "row_start")
    data, side = take_rows(data, limit, bool(item and item.recent) and not paging)
    if side:
        coverage["kept"] = "window" if paging else side
        coverage["truncated_by"] = "budget" if keep is not None else "explicit_limit" if explicit is not None else "leaf_default"
    shown = row_count(data)
    if shown is not None:
        coverage["shown"] = shown
        coverage["exhaustive"] = shown == coverage.get("received")
    return data, coverage


def select_sides(encoded, args, item, coverage):
    """An option chain holds two independently limited tables, so each side reports its own coverage."""
    data, per_side = {}, {}
    for side, table in encoded.items():
        seen = {}
        data[side], _ = select(table, args, item, seen)
        per_side[side] = seen
    coverage.update(per_side)
    return data
