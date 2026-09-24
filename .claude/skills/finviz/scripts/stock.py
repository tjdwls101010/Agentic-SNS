"""One company or ETF: the overview page's sections, section pages backed by route-init-data, statements and price bars."""

from urllib.parse import urlencode, urljoin

import markup
from contract import Collection, Selector, condition, leaf

BASE = "https://finviz.com/stock"
TICKERS = (("tickers",), dict(nargs="+", metavar="TICKER", help="One or more Finviz tickers; each becomes its own result and observation."))


def stock_page(ctx, ticker, section, **extra):
    query = {"t": ticker, "ty": section}
    query.update({k: v for k, v in extra.items() if v is not None})
    obs = ctx.observe(BASE + "?" + urlencode(query))
    page = markup.soup(obs)
    found = page.select_one("h1[data-ticker]")
    if found is None:
        raise obs.fail("structure_changed", "The stock page has no ticker header.", "Read the saved raw page with read ID --raw; the ticker may be unknown or the page layout changed.")
    if found["data-ticker"].upper() != ticker.upper():
        raise obs.fail("ticker_mismatch", "Finviz served " + found["data-ticker"] + " for " + ticker + ".", "Use search to resolve the intended ticker.")
    obs.result["target"] = found["data-ticker"]
    return obs, page


def header(page):
    for hidden in page.select(".quote-header-wrapper .sr-only"):
        hidden.decompose()
    node = page.select_one("h1[data-ticker]")
    return {"ticker": node["data-ticker"], "name": markup.text(page.select_one(".quote-header_ticker-wrapper_company")), "last_close": markup.text(page.select_one(".quote-price_price")), "as_of": markup.text(page.select_one(".quote-price_date")), "change": markup.text(page.select_one(".quote-price_change"))}


def stock_leaf(name, help, **options):
    return leaf("stock", name, help=help, args=[TICKERS] + options.pop("args", []), targets="tickers", **options)


OVERVIEW = {
    "snapshot": Collection("{label, value, definition, unit} in page order; the same label can appear twice with different definitions, and value keeps the page's own string"),
    "news": Collection("{date, time, title, url, source} newest first; date is carried from the row that opened the day, time is the row's own text, and the article lives at url", default=20),
    "ratings": Collection("rows keyed by the table headers: Date, Action, Analyst, Rating Change, Price Target Change; newest first", default=10),
    "insiders": Collection("rows keyed by the table headers plus owner_url (Finviz owner page) and filing_url (SEC Form 4); newest first", default=10),
    "insider_monthly": Collection("Finviz's monthly aggregates as published: date (epoch seconds), saleAggregated, buyAggregated and transaction counts", default=12),
    "ownership_managers": Collection("{investorId, name, slug, percOwnership}: the largest institutional managers", default=10),
    "ownership_funds": Collection("{investorId, name, slug, percOwnership}: the largest funds", default=10),
    "flows": Collection("{date, aum, flow} per day; ETFs only", order="newest day first", reverse=True, default=20),
}


@stock_leaf("overview", "One overview page, read once: the header, the profile, and the snapshot, news, ratings, insider, ownership and fund-flow sections.", collections=OVERVIEW, sections=["snapshot"], context={"ticker, name, last_close, as_of, change": "header facts as displayed; as_of is Finviz's quote time text", "description, peers, website": "the profile paragraph, Finviz's peer tickers and the company website"})
def overview(ctx, args, ticker):
    obs, page = stock_page(ctx, ticker, "c")
    context = header(page)
    peers = [markup.query_param(urljoin(obs.url, a["href"]), "t") for a in page.select(".fullview-links a[href]") if "/stock" in urljoin(obs.url, a["href"])]
    site = page.select_one(".quote-header_ticker-wrapper_company a[href]")
    context.update(description=markup.text(page.select_one(".fullview-profile")) or None, peers=[p for p in peers if p], website=site["href"] if site is not None else None)
    found = {"snapshot": markup.metrics(page), "news": headlines(page, obs.url)}
    table = page.select_one("table.js-table-ratings")
    if table is not None:
        found["ratings"] = markup.table_records(table, obs.url)[1]
    table = markup.table_with_header(page, "Insider Trading")
    if table is not None:
        found["insiders"] = with_insider_links(table, obs.url)
    if page.select_one("script#insider-init-data-0") is not None:
        found["insider_monthly"] = markup.script_json(page, obs, "insider-init-data-0") or []
    if page.select_one("script#institutional-ownership-init-data-0") is not None:
        held = markup.script_json(page, obs, "institutional-ownership-init-data-0")
        found["ownership_managers"], found["ownership_funds"] = held.get("managersOwnership") or [], held.get("fundsOwnership") or []
    if page.select_one("script#route-init-data-fundflows-0") is not None:
        found["flows"] = markup.script_json(page, obs, "route-init-data-fundflows-0") or []
    if not found["snapshot"]:
        raise obs.fail("structure_changed", "No snapshot metrics were found.", "Read the saved raw page with read ID --raw.")
    if "flows" not in found and args.sections and "flows" in args.sections.split(","):
        obs.result["warnings"] = ["Fund flows are published for ETFs only; " + ticker + " has none on its overview page."]
    obs.result["context"], obs.result["collections"] = context, found
    return obs.result


def headlines(page, base):
    items, day = [], None
    for row in page.select("#news-table tr"):
        cells = row.find_all("td", recursive=False)
        link = row.select_one("a[href]")
        if len(cells) < 2 or link is None:
            continue
        stamp = markup.text(cells[0]).split()
        if len(stamp) > 1:
            day = stamp[0]
        source = markup.text(row.select_one(".news-link-right"))
        items.append({"date": day, "time": stamp[-1] if stamp else None, "title": markup.text(link), "url": urljoin(base, link["href"]), "source": source.strip("() ") or None})
    return items


def with_insider_links(table, base):
    rows = markup.table_records(table, base)[1]
    for row, tr in zip(rows, [tr for tr in table.select("tr") if tr.find_all("td", recursive=False)]):
        links = [urljoin(base, a["href"]) for a in tr.select("a[href]")]
        row["owner_url"] = next((u for u in links if "insidertrading" in u), None)
        row["filing_url"] = next((u for u in links if "sec.gov" in u), None)
    return rows


def section_data(ctx, ticker, section, **extra):
    obs, page = stock_page(ctx, ticker, section, **extra)
    return obs, page, markup.script_json(page, obs, "route-init-data")


def revision_history(records, period, context):
    """One fiscal period's whole history, or else the newest estimate of every period and estimate type with the length of its history."""
    if period:
        return [r for r in records if str(r.get("fiscalPeriod")) == period]
    latest, counts = {}, {}
    for record in records:
        key = (record.get("fiscalPeriod"), record.get("estimateType"))
        counts[key] = counts.get(key, 0) + 1
        latest.setdefault(key, record)
    return [dict(record, history_count=counts[key]) for key, record in latest.items()]


EARNINGS = {
    "quarterly": Collection("{fiscalPeriod, earningsDate, fiscalEndDate, epsActual, epsEstimate, salesActual, salesEstimate, analyst counts}: reported quarters newest first, then the projected quarters", default=12),
    "annual": Collection("the same fields per fiscal year, projected years included", order="latest fiscal year first", reverse=True, default=10),
    "revisions": Collection("{fiscalPeriod, estimateType, estimateDate, estimates, upRevisions, downRevisions, mean, high, low, price}; estimateType E is EPS and S is sales. Without --fiscal-period, the newest estimate of each period and type with history_count; with it, that period's every estimate", order="latest fiscal period first, newest estimate first within each period and type", reverse=True, local=[Selector(("--fiscal-period",), dict(default=None, help="Show this fiscal period's whole estimate history newest first, e.g. 2026Q4 or 2026FY, instead of the newest estimate per period."), revision_history)]),
    "reaction": Collection("{fiscalPeriod, reportDate, rsi, reactions: {window: {date, price, prevPrice, priceDiff, spyPriceDiff}}} newest report first", default=8),
}


@stock_leaf("earnings", "Reported and estimated EPS and sales by quarter and year, estimate revisions, and price reactions around reports, from one page.", collections=EARNINGS, sections=["quarterly"], context={"next_earnings_date": "Finviz's next report date"})
def earnings(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "ea")
    obs.result["context"] = {"next_earnings_date": init.get("earningsDate")}
    obs.result["collections"] = {name: init.get(key) or [] for name, key in (("quarterly", "earningsData"), ("annual", "earningsAnnualData"), ("revisions", "earningsRevisionsData"), ("reaction", "priceReactionData"))}
    return obs.result


@stock_leaf("forecast", "Analyst price targets and the history of recommendation counts.", collections={"recommendations": Collection("{recomDate, targetPrice, targetPriceLow, targetPriceHigh, analysts, buy, overweight, hold, underweight, sell, price}", order="newest date first", reverse=True, default=20)}, context={"target_price, target_price_low, target_price_high, analysts": "current consensus as published", "last_close, last_time": "the price Finviz compares against"})
def forecast(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "fc")
    obs.result["context"] = {"target_price": init.get("targetPrice"), "target_price_low": init.get("targetPriceLow"), "target_price_high": init.get("targetPriceHigh"), "analysts": init.get("targetPriceAnalysts"), "last_close": init.get("lastClose"), "last_time": init.get("lastTime")}
    obs.result["collections"] = {"recommendations": init.get("recommendationsData") or []}
    return obs.result


@stock_leaf("dividends", "Dividend payments, annual totals and the current estimate.", collections={"payments": Collection("{Ticker, Exdate, Ordinary, Special} newest first", default=20), "annual": Collection("{FiscalPeriod, Amount, Yield, Payout, Estimate}; Estimate true marks a projected year", order="latest fiscal year first", reverse=True)}, sections=["payments", "annual"], context={"ex_date, estimate, ttm, last_close": "current dividend facts as published"})
def dividends(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "dv")
    obs.result["context"] = {"ex_date": init.get("dividendExDate"), "estimate": init.get("dividendEstimate"), "ttm": init.get("dividendTTM"), "last_close": init.get("lastClose")}
    obs.result["collections"] = {"payments": init.get("dividendsData") or [], "annual": init.get("dividendsAnnualData") or []}
    return obs.result


REVENUE_BLOCKS = {"products": "products_and_services", "regions": "regions", "segments": "segment"}


@stock_leaf("revenue", "Revenue by product, region or segment per fiscal year, with the SEC filing each value came from; one page holds all three breakdowns.", collections={name: Collection("{series, fiscal_year, report_end_date, value, source_filing_url, ...every other source field}, series in source order; --fields always keeps series", key="series") for name in REVENUE_BLOCKS}, sections=["products"], context={"unit": "breakdown -> the unit the source states for its values", "series": "breakdown -> series name -> record count, including series the source lists with no records"})
def revenue(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "rv")
    units, series, found = {}, {}, {}
    for name, key in REVENUE_BLOCKS.items():
        block = init.get(key)
        if not isinstance(block, dict):
            continue
        units[name] = block.get("unit")
        named = block.get("revenues") or {}
        series[name] = {label: len(values or []) for label, values in named.items()}
        found[name] = [dict({"series": label}, **value) for label, values in named.items() for value in values or []]
    obs.result["context"], obs.result["collections"] = {"unit": units, "series": series}, found
    return obs.result


@stock_leaf("short-interest", "Short interest history with float and average volume.", collections={"readings": Collection("{ticker, timestamp (epoch seconds), shortInterest, sharesFloat, averageVolume} as published", order="newest reading first", reverse=True, default=24)})
def short_interest(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "si")
    obs.result["collections"] = {"readings": init if isinstance(init, list) else []}
    return obs.result


def one_side(records, side, context):
    return [c for c in records if c.get("type") == side] if side else records


def around_last_close(records, keep, context):
    """The contracts on the `keep` strikes closest to the underlying; a plain prefix would return only the lowest strikes of the chain."""
    last_close = context.get("last_close")
    strikes = sorted({c["strike"] for c in records if isinstance(c.get("strike"), (int, float))})
    if not keep or keep >= len(strikes) or not isinstance(last_close, (int, float)):
        return records
    chosen = set(sorted(strikes, key=lambda s: abs(s - last_close))[:keep])
    return [c for c in records if c.get("strike") in chosen]


@stock_leaf("options", "Option chain for one expiry with Finviz's implied volatility and greeks.", args=[(("--expiry",), dict(default=None, help="Expiry YYYY-MM-DD from a previous result's expiries; the source's nearest expiry when omitted."))], collections={"contracts": Collection("{strike, type, openInterest, bidPrice, askPrice, lastClose, iv, delta, gamma, theta, vega, rho, ...} as published, by strike with puts and calls interleaved", local=[Selector(("--type",), dict(default=None, choices=["call", "put"], help="Keep only calls or only puts."), one_side), Selector(("--strikes",), dict(type=int, default=20, help="Keep the contracts on the N strikes nearest last_close, calls and puts alike; 0 keeps the whole expiry."), around_last_close)])}, context={"expiries": "expiries the source offers; pass one to --expiry", "current_expiry": "the expiry the chain belongs to", "last_close, last_time": "underlying price context"})
def options(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "oc", e=args.expiry)
    if args.expiry:
        obs.result["conditions"] = {"expiry": condition(args.expiry, "confirmed" if init.get("currentExpiry") == args.expiry else "not_applied", init.get("currentExpiry"))}
    obs.result["context"] = {"expiries": init.get("expiries"), "current_expiry": init.get("currentExpiry"), "last_close": init.get("lastClose"), "last_time": init.get("lastTime")}
    obs.result["collections"] = {"contracts": init.get("options") or []}
    return obs.result


def one_form(records, form, context):
    return [r for r in records if r.get("form") == form] if form else records


@stock_leaf("filings", "SEC filing list for the company with links to the originals; 30 per source page.", args=[(("--page",), dict(type=int, default=1, help="One-based source page; a next command sets it.")), (("--sort",), dict(default=None, help="Source sort key, e.g. -filingDate (the default order)."))], collections={"filings": Collection("{form, filingDate, reportDate, description, filing (index URL), document (primary document URL), accessionNumber} newest filing first", local=[Selector(("--form",), dict(default=None, help="Keep only this form type, e.g. 10-K; it narrows the received page, so page through with next commands to reach older filings."), one_form)])}, context={"available_forms": "form types present for this company", "form_categories": "Finviz's form groupings"}, paging="page")
def filings(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "lf", page=args.page if args.page != 1 else None, sort=args.sort)
    entries = init.get("entries") or {}
    conditions = {"page": condition(args.page, "confirmed" if entries.get("page") == args.page else "not_applied", entries.get("page"))}
    if args.sort:
        conditions["sort"] = condition(args.sort, "confirmed" if init.get("initialSort") == args.sort else "not_applied", init.get("initialSort"))
    obs.result["conditions"] = conditions
    obs.result["totals"] = {"filings": {"source_total": entries.get("totalItemsCount")}}
    total_pages = entries.get("totalPages")
    if total_pages and (entries.get("page") or 0) < total_pages:
        obs.result["next_page"] = entries["page"] + 1
    obs.result["context"] = {"available_forms": init.get("availableForms"), "form_categories": init.get("formCategories")}
    obs.result["collections"] = {"filings": entries.get("items") or []}
    return obs.result


@stock_leaf("statement", "Income statement, balance sheet or cash flow as Finviz publishes it: one record per line item with a source string per period.", args=[(("--kind",), dict(default="income", choices=["income", "balance", "cashflow"], help="Statement to read.")), (("--period",), dict(default="annual", choices=["annual", "quarterly"], help="Annual or quarterly columns."))], collections={"items": Collection("{item, <period>: value, ...} in source order; --filter matches line items, --fields names periods such as TTM or 2025FY and item is always kept", key="item")}, context={"currency": "currency label from the source; no scale is published", "periods": "column labels, e.g. TTM, 2025FY or 2026Q3", "period_end_dates": "period end date per column"})
def statement(ctx, args, ticker):
    code = {"income": "I", "balance": "B", "cashflow": "C"}[args.kind] + ("A" if args.period == "annual" else "Q")
    obs = ctx.observe("https://finviz.com/api/statement?" + urlencode({"t": ticker, "so": "F", "s": code}))
    obs.result["target"] = ticker
    source = obs.json()
    rows = dict(source.get("data") or {})
    periods = rows.pop("Period", None)
    if not periods:
        raise obs.fail("structure_changed", "The statement has no Period row.", "Read the saved raw response with read ID --raw.")
    misaligned = [k for k, v in rows.items() if len(v) != len(periods)]
    if misaligned:
        raise obs.fail("array_alignment", "Rows with a different length than Period: " + ", ".join(misaligned[:5]), "Read the saved raw response with read ID --raw; the values were not padded or cut.")
    ends = rows.pop("Period End Date", None)
    columns = markup.unique_headers(periods)
    obs.result["context"] = {"currency": source.get("currency"), "periods": columns, "period_end_dates": ends}
    obs.result["collections"] = {"items": [dict({"item": name}, **dict(zip(columns, values))) for name, values in rows.items()]}
    return obs.result


ARRAYS = ("date", "open", "high", "low", "close", "volume")


@stock_leaf("prices", "Price bars from Finviz's quote API for a stock or a futures, forex or crypto instrument.", args=[(("--instrument",), dict(default="stock", choices=["stock", "futures", "forex", "crypto"], help="Instrument family the ticker belongs to.")), (("--timeframe",), dict(default="d", help="Source timeframe: d daily, w weekly, m monthly, or intraday codes such as i1, i5.")), (("--bars",), dict(type=int, default=30, help="Bars requested from the source; it may return fewer."))], collections={"bars": Collection("{date_epoch (seconds as supplied), open, high, low, close, volume}, only when every array has the same length", order="newest bar first", reverse=True)}, context={"last": "the remaining scalar fields as supplied, e.g. lastClose, lastTime"})
def prices(ctx, args, ticker):
    obs = ctx.observe("https://finviz.com/api/quote?" + urlencode({"instrument": args.instrument, "ticker": ticker, "timeframe": args.timeframe, "barsCount": args.bars}))
    obs.result["target"] = ticker
    source = obs.json()
    lengths = {k: len(source[k]) for k in ARRAYS if isinstance(source.get(k), list)}
    if "date" not in lengths:
        raise obs.fail("structure_changed", "The quote response has no date array.", "Read the saved raw response with read ID --raw.")
    if len(set(lengths.values())) > 1:
        raise obs.fail("array_alignment", "Price arrays differ in length: " + ", ".join(k + "=" + str(v) for k, v in lengths.items()), "Do not zip these arrays into bars; read ID --raw returns them as received, and the shorter ones are incomplete.")
    bars = [dict(zip(["date_epoch" if k == "date" else k for k in lengths], values)) for values in zip(*(source[k] for k in lengths))]
    obs.result["context"] = {"last": {k: v for k, v in source.items() if k not in lengths and not isinstance(v, list)}}
    obs.result["collections"] = {"bars": bars}
    return obs.result
