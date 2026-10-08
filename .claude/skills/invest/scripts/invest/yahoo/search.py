"""Instruments, news, curated lists or research reports matching a name or keyword."""
import yfinance as yf

from invest.yahoo.datasets import Dataset
from invest.yahoo.info import CROSS_CURRENCY, INFO_UNITS
from invest.yahoo.units import DATETIME, EPOCH, PERCENT, RATIO, UNVERIFIED, u

LOOKUP = {"all": "get_all", "stock": "get_stock", "mutualfund": "get_mutualfund", "etf": "get_etf", "index": "get_index", "future": "get_future",
          "currency": "get_currency", "cryptocurrency": "get_cryptocurrency"}


class Search(Dataset):
    """Instrument candidates are rows; news, lists and research are records."""

    def form_for(self, args):
        return "table" if args.dataset == "quotes" else "records"


def search(target, args, context):
    if args.dataset == "research":
        found = yf.Search(args.query, max_results=0, news_count=0, lists_count=0, include_research=True, include_nav_links=False, timeout=args.timeout)
        return found.research
    context.coverage["requested"] = args.limit
    if args.dataset == "quotes":
        frame = getattr(yf.Lookup(args.query, timeout=args.timeout), LOOKUP[args.type])(count=args.limit)
        received = 0 if frame is None else len(frame)
    else:
        found = yf.Search(args.query, max_results=0, news_count=args.limit if args.dataset == "news" else 0,
                          lists_count=args.limit if args.dataset == "lists" else 0, include_research=False, include_nav_links=False, timeout=args.timeout)
        frame = getattr(found, args.dataset)
        received = len(frame or [])
    if 0 < received < args.limit:
        context.warn("shortfall", f"{received} of the {args.limit} asked for arrived on the first page, the only page read; a short list does not show nothing else matches.")
    return frame


DATASETS = {
    "search": Search(
        search, ticker=False, counted=True, row_currency="currency", cross_currency=CROSS_CURRENCY,
        units={**INFO_UNITS, "providerPublishTime": u(DATETIME, EPOCH), "rank": u(UNVERIFIED),
               "regularMarketPercentChange": u(RATIO, PERCENT, evidence="regularMarketChange / (regularMarketPrice - regularMarketChange) x 100 (AAPL)")},
        coverage="the first page of Yahoo's matches, not every match",
        notes=("Candidates are matches, not a confirmed identity: a stock, its depositary receipt and a similarly named fund can appear together.",
               "rank is Yahoo's ordering score for the match, not a measurement."),
        possible=("shortfall",)),
}
