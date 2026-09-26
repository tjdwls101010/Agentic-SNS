"""Market summaries, sectors and industries."""
import yfinance as yf

from yfinance_skill.yahoo.datasets import RATE, WEIGHT, Dataset

SECTORS = ["basic-materials", "communication-services", "consumer-cyclical", "consumer-defensive", "energy", "financial-services", "healthcare", "industrials", "real-estate", "technology", "utilities"]
DOMAIN_DATA = {"overview": "overview", "top-companies": "top_companies", "research-reports": "research_reports", "industries": "industries", "top-etfs": "top_etfs", "top-funds": "top_mutual_funds", "top-performing": "top_performing_companies", "top-growth": "top_growth_companies"}


def summary(target, args, context, warnings):
    return yf.Market(args.region, timeout=args.timeout).summary


def sectors(target, args, context, warnings):
    return [key for key in SECTORS if args.filter.lower() in key]


REGION_INTERPRETATION = {
    "region": "--region takes only the country codes Yahoo serves for this dataset; an unserved code returns the United States result with no warning, which is indistinguishable from a real answer.",
    "keys": "Sector keys are hyphenated (consumer-cyclical); fund sector-weights uses underscores.",
}
# 성진: 같은 값을 overview는 market_weight(밑줄), 구성종목 표는 "market weight"(공백)로 부른다. 한쪽만 선언하면
# 다른 쪽이 계약 없이 나간다. ytd return은 특히 위험하다 — 실측 raw 3.654가 원천 표기로 "365.40%"다.
DOMAIN_UNITS = {"market weight": WEIGHT, "market_weight": WEIGHT,
                "ytd return": RATE, "growth estimate": RATE}

REGION_GOTCHA = "Outside the United States the name column arrives null for every row, so a non-US region identifies companies by symbol only. That is a degraded answer, not an empty one."


def domain(kind):
    def fetch(target, args, context, warnings):
        entity = kind(args.key, region=args.region)
        if args.region != "US":
            context["region_note"] = "Outside the United States this dataset returns null names, so rows are identified by symbol alone."
        return getattr(entity, DOMAIN_DATA[args.dataset])
    return fetch


DATASETS = {
    "market.summary": Dataset(
        summary,
        interpretation={"shape": "A mapping keyed by exchange, so --fields selects exchanges rather than columns and there are no rows for --limit to cut."}),
    "market.sectors": Dataset(
        sectors,
        interpretation={"coverage": "These are the known Yahoo sector keys, not a live enumeration of what the source will accept today."}),
    "market.sector": Dataset(
        domain(yf.Sector), rows=20, units=DOMAIN_UNITS, interpretation=REGION_INTERPRETATION, gotchas=[REGION_GOTCHA]),
    "market.industry": Dataset(
        domain(yf.Industry), rows=20, units=DOMAIN_UNITS, interpretation=REGION_INTERPRETATION, gotchas=[REGION_GOTCHA]),
}
