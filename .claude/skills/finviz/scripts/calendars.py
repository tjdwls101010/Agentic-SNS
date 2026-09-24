"""Earnings, dividend, economic and earnings-season calendars; named in the plural so the standard library's calendar stays reachable."""

from urllib.parse import urlencode

import markup
from contract import Collection, condition, leaf

CALENDAR_PATHS = {"earnings": "/calendar/earnings", "dividends": "/calendar/dividends", "economic": "/calendar/economic", "season": "/calendar/earnings/season-preview"}
DATE_ARG = (("--date",), dict(default=None, help="Start date YYYY-MM-DD; the page states back the start date it used as date_from, and the date condition is judged from that statement."))
PAGE_ARG = (("--page",), dict(type=int, default=1, help="One-based source page; a next command sets it. Pages after the first come from the calendar API, which states back no date or sort, so those conditions stay unverified."))
SORT_ARG = (("--sort",), dict(default=None, help="Source sort key, e.g. earningsDate or -earningsDate. The page repeats any key it is given, so an agreeing echo leaves the sort unverified; a disagreeing one reports not_applied."))
CALENDAR_ARGS = {"earnings": [DATE_ARG, PAGE_ARG, SORT_ARG], "dividends": [DATE_ARG, PAGE_ARG, SORT_ARG], "economic": [DATE_ARG, SORT_ARG], "season": []}
CALENDAR_HELP = {"earnings": "Earnings calendar: report dates with EPS and sales estimates, actuals and surprises.", "dividends": "Dividend calendar: ex-dates with ordinary and special amounts and yields.", "economic": "Economic calendar: events with actual, previous and forecast values.", "season": "Earnings season preview: upcoming reports per day with estimates."}
CALENDAR_RECORDS = {"earnings": "source records: ticker, earningsDate, isEarningDateEstimate, epsEstimate, epsActual, salesEstimate, salesActual and more", "dividends": "source records: ticker, exdate, ordinary, special, yield and more", "economic": "source records: event, date, actual, previous, forecast and more", "season": "source records: date, ticker, company, earningsDate, epsEstimate, salesEstimate and more"}


def calendar_leaf(kind):
    context = {"date_from": "the start date the source states it used; null when the response states none, as the paging API does"}
    if kind == "season":
        context["totals_per_day"] = "report counts per day over the source's whole preview"
    return leaf("calendar", kind, help=CALENDAR_HELP[kind], args=CALENDAR_ARGS[kind], collections={"items": Collection(CALENDAR_RECORDS[kind])}, context=context, paging="page" if PAGE_ARG in CALENDAR_ARGS[kind] else None)


def calendar(ctx, args, target):
    kind = args.leaf
    date, page, sort = getattr(args, "date", None), getattr(args, "page", 1), getattr(args, "sort", None)
    # The page applies dateFrom and sort and states them back in route-init-data, so page 1 is read from it; the API states nothing back and is used only past page 1.
    use_api = page != 1
    date_from = date
    if use_api and not date_from:
        page_obs, page_data = calendar_page_data(ctx, kind)
        date_from = page_data.get("initialDateFrom")
        if not date_from:
            raise page_obs.fail("structure_changed", "The calendar page does not state its default date.", "Pass --date explicitly.")
    if use_api:
        query = {"dateFrom": date_from, "page": page, "sort": sort or ("earningsDate" if kind == "earnings" else None)}
        obs = ctx.observe("https://finviz.com/api/calendar/" + kind + "?" + urlencode({k: v for k, v in query.items() if v is not None}))
        root = obs.json()
        entries = root if isinstance(root, dict) else None
        items = root.get("items", []) if isinstance(root, dict) else root
        data = {}
        stated_date, stated_sort = (None if date else date_from), None  # the API states no start date of its own
    else:
        obs, data = calendar_page_data(ctx, kind, {"dateFrom": date, "sort": sort})
        entries = data.get("entries") if isinstance(data.get("entries"), dict) else None
        items = entries.get("items", []) if entries else (data.get("entries") or [])
        stated_date, stated_sort = data.get("initialDateFrom"), data.get("initialSort")
    if not isinstance(items, list):
        raise obs.fail("structure_changed", "The calendar response has no item list.", "Read the saved raw response with read ID --raw.")
    obs.result["target"] = kind
    obs.result["context"] = {"date_from": stated_date}
    if kind == "season":
        obs.result["context"]["totals_per_day"] = data.get("totalsPerDay")
    obs.result["collections"] = {"items": items}
    conditions = {}
    if date:
        conditions["date"] = echoed_condition(date, stated_date, "source_date_from")
    if page != 1 or (use_api and kind != "economic"):
        observed = entries.get("page") if entries else None
        conditions["page"] = condition(page, ("confirmed" if observed == page else "not_applied") if observed is not None else "unverified", observed)
    if sort:
        conditions["sort"] = echoed_condition(sort, stated_sort, "source_sort", validated=False)
    obs.result["conditions"] = conditions
    totals = {}
    if entries:
        total_pages = entries.get("totalPages")
        totals["source_total"] = entries.get("totalItemsCount")
        if total_pages and (entries.get("page") or 0) < total_pages:
            obs.result["next_page"] = entries["page"] + 1
    elif data and data.get("totalCount") is not None:
        totals["source_total"] = data["totalCount"]
    obs.result["totals"] = {"items": {k: v for k, v in totals.items() if v is not None}}
    return obs.result


for _kind in CALENDAR_PATHS:
    calendar_leaf(_kind)(calendar)


def echoed_condition(requested, stated, evidence_key, validated=True):
    """Judge a selector by the value the source states back, never by whether the returned rows happen to satisfy it.

    An echo only confirms when the source refuses what it cannot use: the calendar page replaces an unusable date
    with its own default, so an agreeing date was accepted, but it repeats any sort key it is handed, including one
    the API rejects outright, so an agreeing sort echo is the request coming back and establishes nothing.
    """
    if stated is None:
        return condition(requested, "unverified", None)
    if str(stated) != str(requested):
        return condition(requested, "not_applied", {evidence_key: stated})
    return condition(requested, "confirmed" if validated else "unverified", {evidence_key: stated})


def calendar_page_data(ctx, kind, query=None):
    parameters = urlencode({k: v for k, v in (query or {}).items() if v is not None})
    obs = ctx.observe("https://finviz.com" + CALENDAR_PATHS[kind] + ("?" + parameters if parameters else ""))
    root = markup.script_json(markup.soup(obs), obs, "route-init-data")
    data = root.get("data") if isinstance(root, dict) else None
    if not isinstance(data, dict):
        raise obs.fail("structure_changed", "The calendar page has no data block.", "Read the saved raw page with read ID --raw.")
    return obs, data
