"""The assembled info response that prices quote and company profile both select from."""
from yfinance_skill.yahoo.datasets import PERCENT, RATE

# 성진: 여기 있는 것은 전부 값만 보고는 판정할 수 없는 스케일이다. marketCap이 통화라는 것처럼 이름이 이미 말하는
# 사실은 싣지 않는다 — 그런 항목이 표를 키우면 정작 판정 불가능한 항목이 그 안에 묻힌다.
# 첫 세 줄이 같은 리프 안의 100배 충돌이다(실측 AAPL: dividendYield 0.32 = 0.32%인데
# trailingAnnualDividendYield 0.0031 = 0.31%, fiftyTwoWeekChangePercent 31.26 옆에 52WeekChange 0.3126).
INFO_UNITS = {"dividendYield": PERCENT, "fiveYearAvgDividendYield": PERCENT, "trailingAnnualDividendYield": RATE,
              "fiftyTwoWeekChangePercent": PERCENT, "52WeekChange": RATE, "SandP52WeekChange": RATE,
              "regularMarketChangePercent": PERCENT, "postMarketChangePercent": PERCENT, "debtToEquity": PERCENT,
              "payoutRatio": RATE, "heldPercentInsiders": RATE, "heldPercentInstitutions": RATE,
              "profitMargins": RATE, "grossMargins": RATE, "operatingMargins": RATE, "ebitdaMargins": RATE,
              "revenueGrowth": RATE, "earningsGrowth": RATE, "earningsQuarterlyGrowth": RATE,
              "returnOnAssets": RATE, "returnOnEquity": RATE,
              "shortPercentOfFloat": RATE, "sharesPercentSharesOut": RATE}

CURRENCY_SPLIT = "currency prices this instrument's quote; financialCurrency is what its financial statements are reported in. They differ for foreign listings and ADRs (TM quotes in USD and reports in JPY), so a ratio mixing a price with a statement figure is wrong by the exchange rate."
QUOTE_TIME = "regularMarketTime is when the market last priced this instrument; observed_at is when this CLI received the response. After the close they differ by hours."

# 성진: quote가 싣는 시각 필드. 원천이 말하는 시각과 CLI 관측시각은 장 마감 후 몇 시간 벌어진다.
SOURCE_TIME_FIELDS = ("regularMarketTime", "postMarketTime")


def info_time(info):
    if not isinstance(info, dict):
        return None
    for field in SOURCE_TIME_FIELDS:
        value = info.get(field)
        if value:
            return value
    return None


def info(ticker, args, context, warnings):
    """quote and profile are two sides of one assembled response, so they share this fetch and --from."""
    data = ticker.get_info()
    context.update(currency=data.get("currency"), financial_currency=data.get("financialCurrency"))
    return data
