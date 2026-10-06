"""Instrument discovery by name, symbol or keyword."""
import yfinance as yf

from invest.yahoo.datasets import Dataset

LOOKUP = {"all": "get_all", "stock": "get_stock", "mutualfund": "get_mutualfund", "etf": "get_etf", "index": "get_index", "future": "get_future", "currency": "get_currency", "cryptocurrency": "get_cryptocurrency"}


def search(target, args, context, warnings, rows):
    context["coverage_scope"] = "first_page_only"
    if args.dataset != "research":  # research takes no count, so there is nothing a short answer falls short of
        context["requested"] = rows
    if args.dataset == "quotes":
        return getattr(yf.Lookup(args.query, timeout=args.timeout), LOOKUP[args.type])(count=rows)
    found = yf.Search(args.query, max_results=0, news_count=rows if args.dataset == "news" else 0, lists_count=rows if args.dataset == "lists" else 0, include_research=args.dataset == "research", include_nav_links=False, timeout=args.timeout)
    return getattr(found, args.dataset)


DATASETS = {
    "search": Dataset(
        search, counted=True,
        shortfall=("{received} of the {requested} asked for arrived on the first page of search results, the only page read; "
                   "a short list does not show that nothing else matches."),
        interpretation={"identity": "Candidates are search matches, not a confirmed identity: an equity, its depositary receipt and a similarly named fund appear together.",
                        "coverage": "quotes reads only the first Lookup page, and news and lists only the first page of search results; a symbol absent here is not proof it does not exist."}),
}
