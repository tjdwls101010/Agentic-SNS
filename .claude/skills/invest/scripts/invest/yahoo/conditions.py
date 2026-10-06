"""What a response itself shows about an argument that was sent: confirmed, not applied, or unverified."""


def column(data, name):
    """One column of an encoded table by name, or the index; empty when the table lacks it."""
    if not (isinstance(data, dict) and {"index", "columns", "data"} <= set(data)):
        return []
    if name == "index":
        return list(data["index"])
    by_name = {str(c): i for i, c in enumerate(data["columns"])}
    return [row[by_name[name]] for row in data["data"]] if name in by_name else []


def condition(requested, status="unverified", evidence=None):
    """What a condition actually did to this response. A 200 with rows is not evidence that a filter was applied."""
    return {"requested": requested, "status": status, "evidence": evidence}


def within_dates(values, field, start, end):
    """Confirm a date range from the rows' own dates (`values`, from the column `field`): every row inside it confirms, any row outside contradicts."""
    values = [str(v)[:10] for v in values if v is not None]
    if not values:
        return None
    outside = [v for v in values if (start and v < start) or (end and v > end)]
    return condition({"start": start, "end": end}, "not_applied" if outside else "confirmed",
                     {"field": field, "rows": len(values), "range": [min(values), max(values)], "outside": outside[:3]})


def monotonic(data, field, ascending):
    values = [v for v in column(data, field) if isinstance(v, (int, float))]
    if len(values) < 2:
        return None
    ordered = all(a <= b for a, b in zip(values, values[1:])) if ascending else all(a >= b for a, b in zip(values, values[1:]))
    return condition({"sort": field, "ascending": ascending}, "confirmed" if ordered else "not_applied",
                     {"field": field, "first": values[0], "last": values[-1], "rows": len(values)})
