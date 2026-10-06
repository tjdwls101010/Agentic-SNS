"""Company profile, shares outstanding, news entries and SEC filing entries."""
import yfinance as yf

from invest.yahoo.datasets import Dataset
from invest.yahoo.info import ASSEMBLED, INFO_UNITS, PROFILE_FIELDS, RISK, SIBLING, info
from invest.yahoo.units import COUNT, DATETIME, EPOCH, SHARES, u


def shares(ticker, args, context):
    series = ticker.get_shares_full(start=args.start, end=args.end)
    if series is not None:
        series = series.rename("shares")
        series.index.name = "Date"
    return series


def news(ticker, args, context):
    """Yahoo search's news for the symbol. The ticker news feed yfinance 1.7.0 reads (/xhr/ncp) answers 404, which yfinance turns into an empty list."""
    entries = yf.Search(ticker.ticker, max_results=0, news_count=args.limit, lists_count=0, include_nav_links=False, timeout=args.timeout).news
    received = len(entries or [])
    context.coverage.update(requested=args.limit)
    if 0 < received < args.limit:
        context.warn("shortfall", f"{received} of the {args.limit} entries asked for arrived on the first page, the only one read; a short list does not mean there is no more news.")
    return entries


NEWS_UNITS = {"providerPublishTime": u(DATETIME, EPOCH)}


def filings(ticker, args, context):
    return ticker.get_sec_filings()


def filing_preview(entry):
    """What a trimmed receipt shows of one filing: its date, form type and how many documents it has."""
    if not isinstance(entry, dict):
        return entry
    return {"date": entry.get("date"), "type": entry.get("type"), "exhibits": len(entry.get("exhibits") or {})}


DATASETS = {
    "company.profile": Dataset(
        info, form="records", units=INFO_UNITS, fields=PROFILE_FIELDS,
        coverage="Yahoo's info response for the symbol: every field it carries is in result.json",
        notes=(SIBLING, ASSEMBLED, RISK), possible=("cross_currency_fields",)),
    "company.shares": Dataset(
        shares, units={"shares": u(SHARES), "Date": u(DATETIME)},
        coverage="share counts as Yahoo reports them over the range, dated when Yahoo reports them; the dates do not follow a filing calendar"),
    "company.news": Dataset(
        news, form="records", counted=True, units=NEWS_UNITS,
        coverage="the first page of Yahoo search's news for the symbol, not every article",
        notes=("Each entry is a headline with its publisher, link, providerPublishTime and relatedTickers; it is not the article.",
               "Entries are not strictly ordered by time."),
        possible=("shortfall",)),
    "company.filings": Dataset(
        filings, form="records", preview=filing_preview, units={"epochDate": u(DATETIME, EPOCH), "maxAge": u(COUNT)},
        coverage="the SEC filings Yahoo currently lists for the symbol, newest first; Form 4 and older filings may be absent",
        notes=("date is the filing date; exhibits map each document type to Yahoo's copy of the SEC document.",)),
}
