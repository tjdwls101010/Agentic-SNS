"""Instrument discovery by name, symbol or keyword."""
import yfinance as yf

from yfinance_skill.yahoo.datasets import Dataset, asked

LOOKUP = {"all": "get_all", "stock": "get_stock", "mutualfund": "get_mutualfund", "etf": "get_etf", "index": "get_index", "future": "get_future", "currency": "get_currency", "cryptocurrency": "get_cryptocurrency"}


def search(target, args, context, warnings):
    context["coverage_scope"] = "first_page_only"
    requested = asked(args, DATASETS["search"]) or 10
    if args.dataset == "quotes":
        return getattr(yf.Lookup(args.query, timeout=args.timeout), LOOKUP[args.type])(count=requested)
    found = yf.Search(args.query, max_results=0, news_count=requested if args.dataset == "news" else 0, lists_count=requested if args.dataset == "lists" else 0, include_research=args.dataset == "research", include_nav_links=False, timeout=args.timeout)
    return getattr(found, args.dataset)


DATASETS = {
    "search": Dataset(
        search, rows=10,
        interpretation={"identity": "Candidates are search matches, not a confirmed identity: an equity, its depositary receipt and a similarly named fund appear together.",
                        "coverage": "Only the first Lookup page is available; a symbol absent here is not proof it does not exist."},
        gotchas=["--type filters --dataset quotes only; the other datasets ignore it."]),
}
