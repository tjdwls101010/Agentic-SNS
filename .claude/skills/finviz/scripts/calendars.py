"""Earnings, dividend, economic and earnings-season calendars; named in the plural so the standard library's calendar stays reachable."""

from urllib.parse import urlencode

import markup
from contract import Collection, condition, leaf
from transport import Failure

CALENDAR_PATHS = {"earnings": "/calendar/earnings", "dividends": "/calendar/dividends", "economic": "/calendar/economic", "season": "/calendar/earnings/season-preview"}
SORTS = {"earnings": ["ticker", "company", "earningsDate", "marketCap", "epsEstimate", "epsActual", "epsSurprise", "epsReportedEstimate", "epsReportedActual", "epsReportedSurprise", "salesEstimate", "salesActual", "salesSurprise", "oneDayPriceReaction"], "dividends": ["ticker", "company", "exdate", "ordinary", "special", "yield"]}
DATE_ARG = (("--date",), dict(default=None, help="Start date YYYY-MM-DD; the page states back the start date it used as date_from, and the date condition is judged from that statement."))
PAGE_ARG = (("--page",), dict(type=int, default=1, help="One-based source page; a next command sets it. Pages after the first come from the calendar API, which states back no date or sort, so those conditions stay unverified."))
SORT_HELP = "Source sort key, and a leading - for descending. The page repeats any key it is given, so an agreeing echo leaves the sort unverified; a disagreeing one reports not_applied."


def sort_arg(kind):
    keys = SORTS.get(kind)
    if not keys:
        return (("--sort",), dict(default=None, help=SORT_HELP))
    return (("--sort",), dict(default=None, choices=keys + ["-" + k for k in keys], metavar="KEY", help="Sort key: " + ", ".join(keys) + ". " + SORT_HELP))


DAY_ARG = (("--day",), dict(default=None, help="Read every report on one date YYYY-MM-DD instead of the preview's per-day sample."))
CALENDAR_ARGS = {"earnings": [DATE_ARG, PAGE_ARG, sort_arg("earnings")], "dividends": [DATE_ARG, PAGE_ARG, sort_arg("dividends")], "economic": [DATE_ARG, sort_arg("economic")], "season": [DATE_ARG, DAY_ARG]}
CALENDAR_HELP = {"earnings": "Earnings calendar: report dates with EPS and sales estimates, actuals and surprises.", "dividends": "Dividend calendar: ex-dates with ordinary and special amounts and yields.", "economic": "Economic calendar: events with actual, previous and forecast values.", "season": "Earnings season preview: upcoming reports per day with estimates."}
CALENDAR_RECORDS = {"earnings": "source records: ticker, earningsDate, isEarningDateEstimate, epsEstimate, epsActual, salesEstimate, salesActual and more", "dividends": "source records: ticker, exdate, ordinary, special, yield and more", "economic": "source records: event, ticker (the series calendar event reads), date, importance, actual, previous, forecast and more", "season": "source records: date, ticker, company, earningsDate, epsEstimate, salesEstimate and more"}


def calendar_leaf(kind):
    context = {"date_from": "the start date the source states it used; null when the response states none, as the paging API does"}
    if kind == "season":
        context["totals_per_day"] = "report counts per day over the source's whole preview"
    units = {"marketCap": "millions USD"} if kind == "earnings" else None
    return leaf("calendar", kind, help=CALENDAR_HELP[kind], args=CALENDAR_ARGS[kind], collections={"items": Collection(CALENDAR_RECORDS[kind])}, context=context, units=units, paging="page" if PAGE_ARG in CALENDAR_ARGS[kind] else None)


def calendar(ctx, args, target):
    kind = args.leaf
    date, page, sort = getattr(args, "date", None), getattr(args, "page", 1), getattr(args, "sort", None)
    if getattr(args, "day", None):
        return season_day(ctx, args)
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


@leaf(
    "calendar",
    "event",
    help="One economic series: its history of actual and estimated values and its recent and upcoming releases, by the ticker an economic calendar row carries.",
    args=[(("ticker",), dict(metavar="TICKER", help="Economic series ticker from a calendar economic row, e.g. FDTR.")), DATE_ARG],
    collections={"history": Collection("{refDate, actual, estimate, reference} per release", order="newest release first", reverse=True, default=24), "releases": Collection("event rows for this series as on the economic calendar: event, date, actual, previous, forecast, importance and more")},
    sections=["history"],
    context={"category, description, frequency, unit, source, source_url": "the series as the source describes it; unit is the chart unit of the history values"},
)
def event(ctx, args, target):
    query = {"ticker": args.ticker, "dateFrom": args.date}
    obs = ctx.observe("https://finviz.com/api/calendar/economic/detail?" + urlencode({k: v for k, v in query.items() if v is not None}))
    source = obs.json()
    if not isinstance(source, dict) or not isinstance(source.get("chartData", []), list):
        raise obs.fail("structure_changed", "The economic detail API has no chart data.", "Read the saved raw response with read ID --raw.")
    stated = source.get("ticker")
    obs.result["target"] = args.ticker
    obs.result["conditions"] = {"ticker": condition(args.ticker, ("confirmed" if str(stated).upper() == args.ticker.upper() else "not_applied") if stated else "unverified", stated)}
    if args.date:
        obs.result["conditions"]["date"] = condition(args.date, "unverified", None)
    obs.result["context"] = {"category": source.get("category"), "description": source.get("description"), "frequency": source.get("frequency"), "unit": source.get("chartUnit"), "source": source.get("chartSource"), "source_url": source.get("chartSourceUrl")}
    obs.result["collections"] = {"history": source.get("chartData") or [], "releases": source.get("table") or []}
    return obs.result


def season_day(ctx, args):
    if args.date:
        raise Failure("invalid_argument", "--day reads one date's reports and --date the preview weeks from a start date; they do not combine.", "Drop one of them.")
    obs = ctx.observe("https://finviz.com/api/calendar/earnings/season-preview/day?" + urlencode({"date": args.day}))
    items = obs.json()
    if not isinstance(items, list):
        raise obs.fail("structure_changed", "The season-preview day API did not return a list.", "Read the saved raw response with read ID --raw.")
    days = sorted({str(i.get("date")) for i in items})
    obs.result["target"] = args.day
    obs.result["conditions"] = {"day": condition(args.day, ("confirmed" if days == [args.day] else "not_applied") if items else "unverified", days or None)}
    obs.result["context"] = {"date_from": None, "totals_per_day": None}
    obs.result["collections"] = {"items": items}
    return obs.result
