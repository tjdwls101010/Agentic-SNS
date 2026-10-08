"""Market summaries by region, and one sector's or industry's overview, companies, funds or research."""
import yfinance as yf

from invest.yahoo.datasets import Dataset
from invest.yahoo.info import CROSS_CURRENCY, INFO_UNITS
from invest.yahoo.units import COUNT, MONEY_UNCONFIRMED, PER_SHARE_UNCONFIRMED, RATIO, TEXT, u

PARTS = {"overview": "overview", "top-companies": "top_companies", "research-reports": "research_reports", "industries": "industries",
         "top-etfs": "top_etfs", "top-funds": "top_mutual_funds", "top-performing": "top_performing_companies", "top-growth": "top_growth_companies"}
RECORDS = ("overview", "research-reports")
# The same measure is market_weight in an overview and "market weight" in a company table; both are declared.
# Prices and amounts are in each company's own currency, which these lists do not state.
DOMAIN_UNITS = {"market weight": u(RATIO), "market_weight": u(RATIO), "ytd return": u(RATIO), "growth estimate": u(RATIO),
                "last price": u(PER_SHARE_UNCONFIRMED), "target price": u(PER_SHARE_UNCONFIRMED), "market cap": u(MONEY_UNCONFIRMED),
                "market_cap": u(MONEY_UNCONFIRMED), "companies_count": u(COUNT), "industries_count": u(COUNT), "employee_count": u(COUNT),
                "targetPrice": u(PER_SHARE_UNCONFIRMED)}


def summary(target, args, context):
    """A mapping keyed by exchange: one row per exchange, in sorted key order."""
    found = yf.Market(args.region, timeout=args.timeout).summary or {}
    return [{"exchange": key, **{("source.exchange" if k == "exchange" else k): v for k, v in value.items()}} for key, value in sorted(found.items())]


def domain(kind):
    def fetch(target, args, context):
        entity = kind(args.key, region=args.region)
        found = getattr(entity, PARTS[args.dataset])
        if args.region != "US":
            context.warn("names_null_outside_us", "Outside the United States Yahoo returns null names here, so rows are identified by symbol alone.")
        if isinstance(found, dict) and args.dataset in ("top-etfs", "top-funds"):
            return [{"symbol": symbol, "name": name} for symbol, name in found.items()]
        return found
    return fetch


class Domain(Dataset):
    """A sector or industry: its overview and research are records, every other part rows."""

    def form_for(self, args):
        if args.dataset in RECORDS:
            return "records"
        return "rows" if args.dataset in ("top-etfs", "top-funds") else "table"


REGION = "Yahoo answers a country code it does not serve with the United States' result and no warning, so --region offers only the codes it serves."
DATASETS = {
    "market.summary": Dataset(summary, form="rows", ticker=False, units={"exchange": u(TEXT), **INFO_UNITS}, keys=("exchange",), row_currency="currency", cross_currency=CROSS_CURRENCY,
                              coverage="the benchmark quotes Yahoo shows for the region, one row per exchange"),
    "market.sector": Domain(domain(yf.Sector), ticker=False, units=DOMAIN_UNITS, coverage="the part of the sector --dataset names, as Yahoo lists it",
                            notes=(REGION,), possible=("names_null_outside_us",)),
    "market.industry": Domain(domain(yf.Industry), ticker=False, units=DOMAIN_UNITS, coverage="the part of the industry --dataset names, as Yahoo lists it",
                              notes=(REGION,), possible=("names_null_outside_us",)),
}
