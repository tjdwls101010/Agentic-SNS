"""Instrument discovery by name, symbol or keyword."""
import yfinance as yf

from yfinance_skill.envelope import InputError
from yfinance_skill.registry import Arg, effective_limit, get, group, leaf

group("search", "Find instruments by name, symbol or keyword")

LOOKUP = {"all": "get_all", "stock": "get_stock", "mutualfund": "get_mutualfund", "etf": "get_etf", "index": "get_index", "future": "get_future", "currency": "get_currency", "cryptocurrency": "get_cryptocurrency"}


def check(args):
    if args.dataset != "quotes" and args.type != "all":
        raise InputError("--type only filters instrument quotes; use --dataset quotes")


@leaf("search", "", "Find instrument candidates by name, symbol or keyword.",
      args=[Arg("query", help="Company name, symbol fragment or keyword."),
            Arg("--type", choices=["all", "stock", "mutualfund", "etf", "index", "future", "currency", "cryptocurrency"], default="all", help="Instrument type filter; applies to --dataset quotes only."),
            Arg("--dataset", choices=["quotes", "news", "lists", "research"], default="quotes", help="quotes: instrument candidates; news: articles; lists: Yahoo curated lists; research: research reports.")],
      limit=10, narrow=["--limit", "--type", "--dataset"], check=check,
      forbidden=lambda args: ["--type"] if getattr(args, "dataset", "quotes") != "quotes" else [],
      interpretation={"identity": "Candidates are search matches, not a confirmed identity: an equity, its depositary receipt and a similarly named fund appear together.",
                      "coverage": "Only the first Lookup page is available; a symbol absent here is not proof it does not exist."},
      gotchas=["--type filters --dataset quotes only; the other datasets ignore it."])
def search(target, args, context, warnings):
    context["coverage_scope"] = "first_page_only"
    asked = effective_limit(args, get("search", "")) or 10
    if args.dataset == "quotes":
        return getattr(yf.Lookup(args.query, timeout=args.timeout), LOOKUP[args.type])(count=asked)
    found = yf.Search(args.query, max_results=0, news_count=asked if args.dataset == "news" else 0, lists_count=asked if args.dataset == "lists" else 0, include_research=args.dataset == "research", include_nav_links=False, timeout=args.timeout)
    return getattr(found, args.dataset)
