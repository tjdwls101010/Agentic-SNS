"""Company profile, shares outstanding, news and filing links."""
from yfinance_skill.yahoo.datasets import SHARES, Dataset
from yfinance_skill.yahoo.info import CURRENCY_SPLIT, INFO_UNITS, info, info_time


def shares(ticker, args, context, warnings):
    return ticker.get_shares_full(start=args.start, end=args.end)


def news(ticker, args, context, warnings, rows):
    context["requested"] = rows
    return ticker.get_news(count=rows, tab=args.tab)


def filings(ticker, args, context, warnings):
    return ticker.get_sec_filings()


DATASETS = {
    "company.profile": Dataset(
        info, ticker=True, shares_info=True, source_time=info_time, units=INFO_UNITS,
        interpretation={"sibling": "prices quote selects the price side of this same assembled response; --from reuses the observation rather than requesting it again.",
                        "currency": CURRENCY_SPLIT,
                        "governance": "The risk fields are ISS governance deciles, 1-10 relative to the company's index and region, where 1 is the lowest relative risk; they are ranks, not scores out of ten."},
        gotchas=["companyOfficers and executiveTeam are omitted from the default projection because they are large; ask for them by name."]),
    "company.shares": Dataset(
        shares, ticker=True, recent=True, units={"value": SHARES},
        interpretation={"dates": "Each row is a share count dated to the day Yahoo reports it; dates come dozens a year and can repeat within a day, so they do not follow a quarterly filing calendar.",
                        "range": "An omitted --end means now and an omitted --start means about 18 months before the end."}),
    "company.news": Dataset(
        news, ticker=True, counted=True,
        shortfall=("{received} usable entries arrived of the {requested} asked for. yfinance drops sponsored entries from what the feed sent, "
                   "so a short page does not show that the feed ended, and these are not every article about the company."),
        interpretation={"payload": "Each entry nests its article under content, so a field path is dotted: content.title, content.provider.displayName.",
                        "not_the_article": "Entries locate sources; the text here is a summary, not the article. Read the article itself with a web reader."},
        gotchas=["The default projection leaves out content.thumbnail and content.storyline, which are large; name those paths to get them.",
                 "Entries are not strictly ordered by pubDate, so the first entry is not reliably the most recent."]),
    "company.filings": Dataset(
        filings, ticker=True,
        interpretation={"dates": "date is the filing date. Entries arrive newest first.",
                        "not_the_filing": "These are links and metadata. Read the original filing with the sec skill."},
        gotchas=["exhibits holds a link map per filing and is most of this payload; it is outside the default projection, so name it to get it."]),
}
