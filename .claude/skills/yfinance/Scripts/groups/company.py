"""Company profile, shares outstanding, news and filing links."""
from groups.prices import CURRENCY_SPLIT, FROM, INFO_UNITS, info, info_time
from registry import SHARES, SYMBOLS, Arg, dates, effective_limit, get, group, leaf

group("company", "Profile, shares outstanding, news and filing links")

PROFILE_FIELDS = ("symbol", "longName", "quoteType", "currency", "financialCurrency", "sector", "sectorKey", "industry", "industryKey",
                  "country", "state", "city", "address1", "zip", "phone", "website", "irWebsite", "fullTimeEmployees", "longBusinessSummary",
                  "auditRisk", "boardRisk", "compensationRisk", "shareHolderRightsRisk", "overallRisk", "governanceEpochDate",
                  "heldPercentInsiders", "heldPercentInstitutions", "lastFiscalYearEnd", "mostRecentQuarter", "lastSplitDate", "lastSplitFactor")

leaf("company", "profile", "Business description, sector, governance risk and headquarters for one company.",
     args=[SYMBOLS, FROM], ticker=True, shares_info=True, source_time=info_time,
     fields=PROFILE_FIELDS, narrow=["--fields"], units=INFO_UNITS,
     interpretation={"sibling": "prices quote selects the price side of this same assembled response; --from reuses the observation rather than requesting it again.",
                     "currency": CURRENCY_SPLIT,
                     "governance": "The risk fields are Yahoo's 1-10 decile ranks within the peer group, where 1 is the lowest measured risk; they are ranks, not scores out of ten."},
     gotchas=["companyOfficers and executiveTeam are omitted from the default projection because they are large; ask for them by name."])(info)


@leaf("company", "shares", "Shares outstanding as Yahoo observed it over a date range.",
      args=[SYMBOLS, *dates("ISO date YYYY-MM-DD; default is about 18 months ago.", "ISO date YYYY-MM-DD; default is now.")], ticker=True,
      recent=True, narrow=["--limit", "--start/--end"],
      units={"value": SHARES},
      interpretation={"dates": "Each row is a Yahoo observation timestamp rounded to a whole day, not a filing or record date.",
                      "range": "An omitted --end means now and an omitted --start means about 18 months earlier."})
def shares(ticker, args, context, warnings):
    return ticker.get_shares_full(start=args.start, end=args.end)


NEWS_FIELDS = ("content.title", "content.pubDate", "content.provider.displayName", "content.canonicalUrl.url", "content.summary")


@leaf("company", "news", "Recent article and press-release entries referencing this company.",
      args=[SYMBOLS, Arg("--tab", choices=["news", "all", "press releases"], default="news", help="Article source: news articles, press releases, or all.")], ticker=True,
      limit=10, fields=NEWS_FIELDS, narrow=["--fields", "--limit", "--tab"],
      interpretation={"payload": "Each entry nests its article under content, so a field path is dotted: content.title, content.provider.displayName.",
                      "not_the_article": "Entries locate sources; the text here is a summary, not the article. Read the article itself with a web reader."},
      gotchas=["The default projection leaves out thumbnail and storyline, which measured together as over half the payload.",
               "Entries are not strictly ordered by pubDate: measured, a later item carried a newer timestamp than an earlier one, so the first entry is not reliably the most recent."])
def news(ticker, args, context, warnings):
    context["upstream_requested"] = effective_limit(args, get("company", "news")) or 10
    return ticker.get_news(count=context["upstream_requested"], tab=args.tab)


@leaf("company", "filings", "SEC filing entries with their Yahoo EDGAR links.",
      args=[SYMBOLS], ticker=True,
      limit=20, fields=("date", "type", "title", "edgarUrl"), narrow=["--fields", "--limit"],
      interpretation={"dates": "date is the filing date. Entries arrive newest first.",
                      "not_the_filing": "These are links and metadata. Read the original filing with the sec skill."},
      gotchas=["exhibits holds a link map per filing and measured as the majority of this payload; it is outside the default projection and has to be asked for by name."])
def filings(ticker, args, context, warnings):
    return ticker.get_sec_filings()
