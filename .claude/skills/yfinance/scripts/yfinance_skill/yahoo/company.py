"""Company profile, shares outstanding, news and filing links."""
from yfinance_skill.yahoo.datasets import SHARES, Dataset, asked
from yfinance_skill.yahoo.info import CURRENCY_SPLIT, INFO_UNITS, info, info_time

PROFILE_FIELDS = ("symbol", "longName", "quoteType", "currency", "financialCurrency", "sector", "sectorKey", "industry", "industryKey",
                  "country", "state", "city", "address1", "zip", "phone", "website", "irWebsite", "fullTimeEmployees", "longBusinessSummary",
                  "auditRisk", "boardRisk", "compensationRisk", "shareHolderRightsRisk", "overallRisk", "governanceEpochDate",
                  "heldPercentInsiders", "heldPercentInstitutions", "lastFiscalYearEnd", "mostRecentQuarter", "lastSplitDate", "lastSplitFactor")


def shares(ticker, args, context, warnings):
    return ticker.get_shares_full(start=args.start, end=args.end)


NEWS_FIELDS = ("content.title", "content.pubDate", "content.provider.displayName", "content.canonicalUrl.url", "content.summary")


def news(ticker, args, context, warnings):
    context["upstream_requested"] = asked(args, DATASETS["company.news"]) or 10
    return ticker.get_news(count=context["upstream_requested"], tab=args.tab)


def filings(ticker, args, context, warnings):
    return ticker.get_sec_filings()


DATASETS = {
    "company.profile": Dataset(
        info, ticker=True, shares_info=True, source_time=info_time, fields=PROFILE_FIELDS, units=INFO_UNITS,
        interpretation={"sibling": "prices quote selects the price side of this same assembled response; --from reuses the observation rather than requesting it again.",
                        "currency": CURRENCY_SPLIT,
                        "governance": "The risk fields are Yahoo's 1-10 decile ranks within the peer group, where 1 is the lowest measured risk; they are ranks, not scores out of ten."},
        gotchas=["companyOfficers and executiveTeam are omitted from the default projection because they are large; ask for them by name."]),
    "company.shares": Dataset(
        shares, ticker=True, recent=True, units={"value": SHARES},
        interpretation={"dates": "Each row is a Yahoo observation timestamp rounded to a whole day, not a filing or record date.",
                        "range": "An omitted --end means now and an omitted --start means about 18 months earlier."}),
    "company.news": Dataset(
        news, ticker=True, rows=10, fields=NEWS_FIELDS,
        interpretation={"payload": "Each entry nests its article under content, so a field path is dotted: content.title, content.provider.displayName.",
                        "not_the_article": "Entries locate sources; the text here is a summary, not the article. Read the article itself with a web reader."},
        gotchas=["The default projection leaves out thumbnail and storyline, which are most of the payload; name them to get them.",
                 "Entries are not strictly ordered by pubDate, so the first entry is not reliably the most recent."]),
    "company.filings": Dataset(
        filings, ticker=True, rows=20, fields=("date", "type", "title", "edgarUrl"),
        interpretation={"dates": "date is the filing date. Entries arrive newest first.",
                        "not_the_filing": "These are links and metadata. Read the original filing with the sec skill."},
        gotchas=["exhibits holds a link map per filing and is most of this payload; it is outside the default projection, so name it to get it."]),
}
