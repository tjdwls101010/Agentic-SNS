"""Market summaries, sectors and industries."""
import yfinance as yf

from yfinance_skill.registry import RATE, WEIGHT, Arg, group, leaf

group("market", "Market summaries, sectors and industries")

# 성진: Sector·Industry의 region은 yf.MarketRegion(US/GB/ASIA/EUROPE/…)이 아니라 ISO 3166-1 alpha-2다 — 다른 이름공간이라
# MarketRegion을 choices로 쓰면 실제로 동작하는 KR·JP·DE가 거절된다. 아래 목록은 실측이다: 각 코드로 top-companies를
# 부르고 US와 같은 종목이 오면 조용한 대체로 판정했다. ZZ·XX·UK·EU와 NL·CH·IE·ZA 등은 전부 그 대체에 걸렸다.
DOMAIN_REGIONS = ["US", "AR", "AU", "BR", "CA", "CN", "DE", "DK", "ES", "FI", "FR", "GB", "GR", "HK", "IL", "IN", "IT", "JP", "KR", "MY", "NO", "PT", "QA", "RU", "SE", "SG", "TH", "TR", "TW"]
SECTORS = ["basic-materials", "communication-services", "consumer-cyclical", "consumer-defensive", "energy", "financial-services", "healthcare", "industrials", "real-estate", "technology", "utilities"]
DOMAIN_DATA = {"overview": "overview", "top-companies": "top_companies", "research-reports": "research_reports", "industries": "industries", "top-etfs": "top_etfs", "top-funds": "top_mutual_funds", "top-performing": "top_performing_companies", "top-growth": "top_growth_companies"}


@leaf("market", "summary", "Benchmark index quotes for a market region.",
      args=[Arg("--region", choices=[r.value for r in yf.MarketRegion], default="US", help="Yahoo market region.")],
      narrow=["--fields", "--region"],
      interpretation={"shape": "A mapping keyed by exchange, so --fields selects exchanges rather than columns and there are no rows for --limit to cut."})
def summary(target, args, context, warnings):
    return yf.Market(args.region, timeout=args.timeout).summary


@leaf("market", "sectors", "Sector keys accepted by market sector.", narrow=["--filter"],
      interpretation={"coverage": "These are the known Yahoo sector keys, not a live enumeration of what the source will accept today."})
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


def domain_args(datasets):
    # 성진: 닫힌 선택지가 G1을 인터페이스 층에서 없앤다 — 서비스되지 않는 코드는 경고 없이 미국 데이터를 돌려줬다.
    return [Arg("key", help="Sector key from market sectors, or industry key from market sector KEY --dataset industries."),
            Arg("--region", choices=DOMAIN_REGIONS, default="US", help="Country code, restricted to the regions Yahoo serves; others return the United States result with no warning. Outside the US the name column arrives null."),
            Arg("--dataset", choices=["overview", "top-companies", "research-reports"] + datasets, default="overview", help="Part of the sector or industry to return.")]


def domain(kind):
    def fetch(target, args, context, warnings):
        entity = kind(args.key, region=args.region)
        if args.region != "US":
            context["region_note"] = "Outside the United States this dataset returns null names, so rows are identified by symbol alone."
        return getattr(entity, DOMAIN_DATA[args.dataset])
    return fetch


leaf("market", "sector", "One sector's overview, industries, top companies, funds or research.",
     args=domain_args(["industries", "top-etfs", "top-funds"]),
     limit=20, narrow=["--fields", "--limit", "--dataset"], units=DOMAIN_UNITS,
     interpretation=REGION_INTERPRETATION, gotchas=[REGION_GOTCHA])(domain(yf.Sector))

leaf("market", "industry", "One industry's overview, companies or research.",
     args=domain_args(["top-performing", "top-growth"]),
     limit=20, narrow=["--fields", "--limit", "--dataset"], units=DOMAIN_UNITS,
     interpretation=REGION_INTERPRETATION, gotchas=[REGION_GOTCHA])(domain(yf.Industry))
