"""One company or ETF: overview-derived leaves, section pages backed by route-init-data, statements and price bars."""

from urllib.parse import urlencode, urljoin

import markup
from finviz import condition, leaf

BASE = "https://finviz.com/stock"
TICKERS = (("tickers",), dict(nargs="+", metavar="TICKER", help="One or more Finviz tickers; each becomes its own result."))


FROM_ARG = (("--from",), dict(dest="from_id", metavar="ID", default=None, help="Extract this section from a page already observed under this id instead of requesting it again; the six overview sections are six readings of one request. The result keeps that observation's id and observed_at."))


def stock_page(ctx, ticker, section, args=None, **extra):
    query = {"t": ticker, "ty": section}
    query.update({k: v for k, v in extra.items() if v is not None})
    url = BASE + "?" + urlencode(query)
    obs = ctx.replay(args.from_id, url) if getattr(args, "from_id", None) else ctx.observe(url)
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


def stock_leaf(name, help, output, **options):
    extra = options.pop("args", [])
    if options.pop("overview", False):  # the sections that all come from stock?t=TICKER&ty=c
        extra = extra + [FROM_ARG]
    return leaf("stock", name, help=help, output=output, args=[TICKERS] + extra, targets="tickers", **options)


@stock_leaf("snapshot", "Company or ETF header and every snapshot metric with its own definition; repeated labels stay separate.", {"ticker, name, last_close, as_of, change": "header facts as displayed; as_of is Finviz's quote time text", "metrics": "[{label, value, definition, unit}] in page order, where the same label can appear twice with different definitions. Asked for several tickers at once, each metric carries label and value only, because the definitions are the same page's text repeated per ticker; --fields label,value,definition brings them back."}, records="metrics", narrow=["--filter", "--fields", "--limit"], context=["ticker", "name", "last_close", "as_of", "change"], overview=True, window=lambda data, args: data if len(args.tickers) == 1 or args.fields else dict(data, metrics=[{"label": m["label"], "value": m["value"]} for m in data["metrics"]]))
def snapshot(ctx, args, ticker):
    obs, page = stock_page(ctx, ticker, "c", args)
    found = markup.metrics(page)
    if not found:
        raise obs.fail("structure_changed", "No snapshot metrics were found.", "Read the saved raw page with read ID --raw.")
    obs.result["data"] = dict(header(page), metrics=found)
    return obs.result


@stock_leaf("profile", "Company description and Finviz peer tickers from the overview page.", {"ticker, name": "header facts", "description": "profile paragraph as displayed", "peers": "tickers Finviz lists as peers", "links": "{website} from the company header"}, overview=True)
def profile(ctx, args, ticker):
    obs, page = stock_page(ctx, ticker, "c", args)
    peers = [markup.query_param(urljoin(obs.url, a["href"]), "t") for a in page.select(".fullview-links a[href]") if "/stock" in urljoin(obs.url, a["href"])]
    facts = header(page)
    site = page.select_one(".quote-header_ticker-wrapper_company a[href]")
    obs.result["data"] = {"ticker": facts["ticker"], "name": facts["name"], "description": markup.text(page.select_one(".fullview-profile")), "peers": [p for p in peers if p], "links": {"website": site["href"]} if site is not None else {}}
    return obs.result


@stock_leaf("ratings", "Analyst rating actions from the overview page.", {"list of rating actions": "rows keyed by the table headers: Date, Action, Analyst, Rating Change, Price Target Change"}, narrow=["--limit", "--filter"], overview=True)
def ratings(ctx, args, ticker):
    obs, page = stock_page(ctx, ticker, "c", args)
    table = page.select_one("table.js-table-ratings")
    obs.result["data"] = markup.table_records(table, obs.url)[1] if table is not None else []
    return obs.result


@stock_leaf("news", "Headlines listed on the overview page; each links to its external source.", {"list of headlines": "{time, title, url, source} newest first; time is Finviz's display text and the article body lives at url"}, narrow=["--limit", "--filter"], default_limit=40, overview=True)
def news(ctx, args, ticker):
    obs, page = stock_page(ctx, ticker, "c", args)
    items = []
    for row in page.select("#news-table tr"):
        cells = row.find_all("td", recursive=False)
        link = row.select_one("a[href]")
        if len(cells) < 2 or link is None:
            continue
        source = markup.text(row.select_one(".news-link-right"))
        items.append({"time": markup.text(cells[0]), "title": markup.text(link), "url": urljoin(obs.url, link["href"]), "source": source.strip("() ") or None})
    obs.result["data"] = items
    return obs.result


@stock_leaf("insiders", "Insider transactions listed on the overview page plus Finviz's monthly buy/sell aggregates.", {"trades": "rows keyed by the table headers plus owner_url (Finviz owner page) and filing_url (SEC Form 4)", "monthly": "Finviz's monthly aggregates as published: date (epoch), saleAggregated, buyAggregated and counts"}, records="trades", narrow=["--limit", "--filter", "--fields"], overview=True)
def insiders(ctx, args, ticker):
    obs, page = stock_page(ctx, ticker, "c", args)
    table = markup.table_with_header(page, "Insider Trading")
    trades = []
    if table is not None:
        for row, tr in zip(markup.table_records(table, obs.url)[1], [tr for tr in table.select("tr") if tr.find_all("td", recursive=False)]):
            links = [urljoin(obs.url, a["href"]) for a in tr.select("a[href]")]
            row["owner_url"] = next((u for u in links if "insidertrading" in u), None)
            row["filing_url"] = next((u for u in links if "sec.gov" in u), None)
            trades.append(row)
    monthly = page.select_one("script#insider-init-data-0")
    obs.result["data"] = {"trades": trades, "monthly": markup.script_json(page, obs, "insider-init-data-0") if monthly else None}
    return obs.result


@stock_leaf("ownership", "Largest institutional managers and funds as Finviz publishes them on the overview page.", {"managers": "[{investorId, name, slug, percOwnership}]", "funds": "[{investorId, name, slug, percOwnership}]"}, overview=True)
def ownership(ctx, args, ticker):
    obs, page = stock_page(ctx, ticker, "c", args)
    if page.select_one("script#institutional-ownership-init-data-0") is None:
        obs.result["data"] = {}
        return obs.result
    held = markup.script_json(page, obs, "institutional-ownership-init-data-0")
    obs.result["data"] = {"managers": held.get("managersOwnership"), "funds": held.get("fundsOwnership")}
    return obs.result


@stock_leaf("flows", "ETF fund flows and assets under management by day, as published on the overview page.", {"list of days": "{date, aum, flow} oldest first, ending at the most recent day; ETFs only"}, narrow=["--limit"], default_limit=120, recent=True, overview=True)
def flows(ctx, args, ticker):
    obs, page = stock_page(ctx, ticker, "c", args)
    if page.select_one("script#route-init-data-fundflows-0") is None:
        obs.result["data"], obs.result["warnings"] = [], ["Fund flows are published for ETFs only; " + ticker + " has none on its overview page."]
        return obs.result
    obs.result["data"] = markup.script_json(page, obs, "route-init-data-fundflows-0")
    return obs.result


def section_data(ctx, ticker, section, **extra):
    obs, page = stock_page(ctx, ticker, section, **extra)
    return obs, page, markup.script_json(page, obs, "route-init-data")


DATASETS = {"quarterly": "earningsData", "annual": "earningsAnnualData", "revisions": "earningsRevisionsData", "reaction": "priceReactionData"}


@stock_leaf("earnings", "Reported and estimated EPS and sales by fiscal period, annual history, estimate revisions, or price reactions around reports.", {"next_earnings_date": "Finviz's next report date", "dataset": "which dataset the records come from", "records": "source records newest first: quarterly/annual carry epsActual, epsEstimate, salesActual, salesEstimate and analyst counts; revisions carry estimateDate, mean, high, low, up/downRevisions per fiscalPeriod; reaction carries per-day price moves"}, args=[(("--dataset",), dict(default="quarterly", choices=list(DATASETS), help="Which earnings dataset to return.")), (("--fiscal-period",), dict(default=None, help="Keep only records whose fiscalPeriod equals this, e.g. 2026Q3 or 2025FY; revisions have thousands of records."))], records="records", narrow=["--fiscal-period", "--limit", "--fields"], default_limit=40, context=["next_earnings_date", "dataset"])
def earnings(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "ea")
    records = init.get(DATASETS[args.dataset]) or []
    obs.result["coverage"] = {"received": len(records)}
    if args.fiscal_period:
        records = [r for r in records if str(r.get("fiscalPeriod")) == args.fiscal_period]
    obs.result["data"] = {"next_earnings_date": init.get("earningsDate"), "dataset": args.dataset, "records": records}
    return obs.result


@stock_leaf("forecast", "Analyst price targets and the history of recommendation counts.", {"target_price, target_price_low, target_price_high, analysts": "current consensus as published", "last_close, last_time": "the price Finviz compares against", "recommendations": "[{recomDate, targetPrice, targetPriceLow, targetPriceHigh, analysts, buy, overweight, hold, underweight, sell, price}] newest first"}, records="recommendations", narrow=["--limit", "--fields"], context=["last_close", "last_time", "analysts"])
def forecast(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "fc")
    obs.result["data"] = {"target_price": init.get("targetPrice"), "target_price_low": init.get("targetPriceLow"), "target_price_high": init.get("targetPriceHigh"), "analysts": init.get("targetPriceAnalysts"), "last_close": init.get("lastClose"), "last_time": init.get("lastTime"), "recommendations": init.get("recommendationsData") or []}
    return obs.result


@stock_leaf("dividends", "Dividend payments, annual totals and the current estimate.", {"ex_date, estimate, ttm, last_close": "current dividend facts as published", "payments": "[{Ticker, Exdate, Ordinary, Special}] newest first", "annual": "[{FiscalPeriod, Amount, Yield, Payout, Estimate}]; Estimate true marks a projected year"}, records="payments", narrow=["--limit", "--fields"], context=["ex_date", "estimate", "ttm", "last_close"])
def dividends(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "dv")
    obs.result["data"] = {"ex_date": init.get("dividendExDate"), "estimate": init.get("dividendEstimate"), "ttm": init.get("dividendTTM"), "last_close": init.get("lastClose"), "payments": init.get("dividendsData") or [], "annual": init.get("dividendsAnnualData") or []}
    return obs.result


@stock_leaf("revenue", "Revenue by product, region or segment per fiscal year, with the SEC filing each value came from.", {"unit": "source currency or scale, preserved alongside selected series", "series": "name -> source records [{fiscal_year, report_end_date, source_filing_url, value, ...}]; --keys selects series names, --filter matches names or values, --limit counts series; unit stays alongside them"}, args=[(("--by",), dict(default="products", choices=["products", "regions", "segment"], help="Breakdown to return."))], records="series", narrow=["--filter", "--keys", "--limit"], context=["unit"])
def revenue(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "rv")
    block = init.get({"products": "products_and_services", "regions": "regions", "segment": "segment"}[args.by]) or {}
    obs.result["data"] = {"unit": block.get("unit"), "series": block.get("revenues") or {}}
    return obs.result


@stock_leaf("short-interest", "Short interest history with float and average volume.", {"list of readings": "{ticker, timestamp (epoch), shortInterest, sharesFloat, averageVolume} as published, oldest first and ending at the most recent reading"}, narrow=["--limit"], recent=True)
def short_interest(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "si")
    obs.result["data"] = init if isinstance(init, list) else []
    return obs.result


def chain_window(data, args):
    """The contracts a chain is read for: one side if asked, on the strikes nearest the underlying."""
    contracts = data["contracts"]
    if args.type:
        contracts = [c for c in contracts if c.get("type") == args.type]
    return dict(data, contracts=around_last_close(contracts, data.get("last_close"), args.strikes))


def around_last_close(contracts, last_close, keep):
    """The contracts on the `keep` strikes closest to the underlying; a plain prefix would return only the lowest strikes of the chain."""
    strikes = sorted({c["strike"] for c in contracts if isinstance(c.get("strike"), (int, float))})
    if not keep or keep >= len(strikes) or last_close is None or len(strikes) != len({c.get("strike") for c in contracts}):
        return contracts
    chosen = set(sorted(strikes, key=lambda s: abs(s - last_close))[:keep])
    return [c for c in contracts if c.get("strike") in chosen]


@stock_leaf("options", "Option chain for one expiry with Finviz's implied volatility and greeks.", {"expiries": "expiries the source offers; pass one to --expiry", "current_expiry": "the expiry the chain belongs to", "last_close, last_time": "underlying price context", "contracts": "[{strike, type, openInterest, bidPrice, askPrice, lastClose, iv, delta, gamma, theta, vega, rho, ...}] as published"}, args=[(("--expiry",), dict(default=None, help="Expiry YYYY-MM-DD from a previous result's expiries; the source's nearest expiry when omitted.")), (("--type",), dict(default=None, choices=["call", "put"], help="Keep only calls or only puts (local selection).")), (("--strikes",), dict(type=int, default=20, help="Keep the contracts on the N strikes nearest last_close, calls and puts alike, in source order; 0 keeps the whole expiry, which usually needs a larger --max-chars."))], records="contracts", window=chain_window, narrow=["--strikes", "--type", "--fields", "--limit"], context=["current_expiry", "last_close", "last_time"])
def options(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "oc", e=args.expiry)
    contracts = init.get("options") or []
    if args.expiry:
        obs.result["conditions"] = {"expiry": condition(args.expiry, "confirmed" if init.get("currentExpiry") == args.expiry else "not_applied", init.get("currentExpiry"))}
    obs.result["data"] = {"expiries": init.get("expiries"), "current_expiry": init.get("currentExpiry"), "last_close": init.get("lastClose"), "last_time": init.get("lastTime"), "contracts": contracts}
    return obs.result


@stock_leaf("filings", "SEC filing list for the company with links to the originals; 30 per page.", {"items": "[{form, filingDate, reportDate, description, filing (index URL), document (primary document URL), accessionNumber}]", "available_forms": "form types present for this company", "form_categories": "Finviz's form groupings"}, args=[(("--page",), dict(type=int, default=1, help="One-based page from a previous continuation.")), (("--sort",), dict(default=None, help="Source sort key, e.g. -filingDate (the default order).")), (("--form",), dict(default=None, help="Keep only this form type, e.g. 10-K (local selection; the source has no form filter)."))], records="items", narrow=["--form", "--limit", "--fields"])
def filings(ctx, args, ticker):
    obs, page, init = section_data(ctx, ticker, "lf", page=args.page if args.page != 1 else None, sort=args.sort)
    entries = init.get("entries") or {}
    items = entries.get("items") or []
    if args.form:
        items = [i for i in items if i.get("form") == args.form]
        if not items and entries.get("items"):
            obs.result["warnings"] = ["No " + args.form + " on page " + str(args.page) + "; the source has no form filter, so page through with --page (continuation) to find older filings."]
    conditions = {"page": condition(args.page, "confirmed" if entries.get("page") == args.page else "not_applied", entries.get("page"))}
    if args.sort:
        conditions["sort"] = condition(args.sort, "confirmed" if init.get("initialSort") == args.sort else "not_applied", init.get("initialSort"))
    obs.result["conditions"] = conditions
    total_pages = entries.get("totalPages")
    obs.result["coverage"] = {"received": len(entries.get("items") or []), "source_total": entries.get("totalItemsCount"), "exhaustive": False, "pagination_end": entries.get("page") == total_pages if total_pages else None}
    if total_pages and entries.get("page", 0) < total_pages:
        obs.result["continuation"] = {"page": entries["page"] + 1}
    obs.result["data"] = {"items": items, "available_forms": init.get("availableForms"), "form_categories": init.get("formCategories")}
    return obs.result


@stock_leaf("statement", "Income statement, balance sheet or cash flow as Finviz publishes it: source strings per period.", {"currency": "currency label from the source; no scale is published", "periods": "column labels, e.g. TTM, 2025FY or 2026Q3", "period_end_dates": "period end date per column", "items": "line item -> values aligned to periods, as source strings"}, args=[(("--kind",), dict(default="income", choices=["income", "balance", "cashflow"], help="Statement to read.")), (("--period",), dict(default="annual", choices=["annual", "quarterly"], help="Annual or quarterly columns."))], narrow=["--fields"], context=["currency", "periods", "period_end_dates"])
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
        raise obs.fail("array_alignment", "Rows with a different length than Period: " + ", ".join(misaligned[:5]), "Read the saved raw response; the values were not padded or cut.")
    obs.result["data"] = {"currency": source.get("currency"), "periods": periods, "period_end_dates": rows.pop("Period End Date", None), "items": rows}
    return obs.result


ARRAYS = ("date", "open", "high", "low", "close", "volume")


@stock_leaf("prices", "Price bars from Finviz's quote API for a stock or a futures, forex or crypto instrument.", {"bars": "[{date_epoch (seconds as supplied), open, high, low, close, volume}] oldest first, only when every array has the same length", "last": "the remaining scalar fields as supplied, e.g. lastClose, lastTime"}, args=[(("--instrument",), dict(default="stock", choices=["stock", "futures", "forex", "crypto"], help="Instrument family the ticker belongs to.")), (("--timeframe",), dict(default="d", help="Source timeframe: d daily, w weekly, m monthly, or intraday codes such as i1, i5.")), (("--bars",), dict(type=int, default=30, help="Bars requested; the source may return fewer."))], records="bars", narrow=["--bars", "--limit"])
def prices(ctx, args, ticker):
    obs = ctx.observe("https://finviz.com/api/quote?" + urlencode({"instrument": args.instrument, "ticker": ticker, "timeframe": args.timeframe, "barsCount": args.bars}))
    obs.result["target"] = ticker
    source = obs.json()
    obs.result["data"] = source
    lengths = {k: len(source[k]) for k in ARRAYS if isinstance(source.get(k), list)}
    if "date" not in lengths:
        raise obs.fail("structure_changed", "The quote response has no date array.", "Read the saved raw response with read ID --raw.")
    if len(set(lengths.values())) > 1:
        raise obs.fail("array_alignment", "Price arrays differ in length: " + ", ".join(k + "=" + str(v) for k, v in lengths.items()), "Do not zip these arrays into bars; read the saved arrays with read ID --pointer /data/close and treat the shorter ones as incomplete.")
    bars = [dict(zip(["date_epoch" if k == "date" else k for k in lengths], values)) for values in zip(*(source[k] for k in lengths))]
    obs.result["data"] = {"bars": bars, "last": {k: v for k, v in source.items() if k not in lengths and not isinstance(v, list)}}
    return obs.result
