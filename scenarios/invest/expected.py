"""Expected answers for the large-result scenarios, computed apart from the skill: from yfinance directly, or from the rows a run actually received.

A live run is judged against what that run received, so `compute(scenario, frame)` takes a run's own price rows and returns the answer they imply. The two 2025 scenarios ask about a closed window, so `--reference` also fetches it straight from yfinance (not through the skill) and stores the closes with the time they were read; a later run whose closes differ shows a change at the source, which is recorded apart from the verdict.

usage: uv run --no-project --exclude-newer 2026-09-13T13:10:00Z --with "yfinance[repair]==1.7.0" python scenarios/invest/expected.py --reference
"""
import argparse
import datetime as dt
import json
from pathlib import Path

DOW_2025 = ["AAPL", "AMGN", "AMZN", "AXP", "BA", "CAT", "CRM", "CSCO", "CVX", "DIS", "GS", "HD", "HON", "IBM", "JNJ",
            "JPM", "KO", "MCD", "MMM", "MRK", "MSFT", "NKE", "NVDA", "PG", "SHW", "TRV", "UNH", "V", "VZ", "WMT"]
REFERENCE = Path(__file__).with_name("expected-2025.json")


def closes(frame):
    """{symbol: close series indexed by date} from long rows with columns target, date, close."""
    return {symbol: rows.set_index("date")["close"].sort_index() for symbol, rows in frame.groupby("target")}


def bulk_corr(frame):
    """Pairwise Pearson correlation of daily simple returns over the dates both members share."""
    import itertools
    series = {s: c.pct_change().dropna() for s, c in closes(frame).items()}
    pairs = []
    for a, b in itertools.combinations(sorted(series), 2):
        joined = series[a].to_frame("a").join(series[b].to_frame("b"), how="inner")
        pairs.append({"pair": [a, b], "corr": float(joined["a"].corr(joined["b"])), "n": len(joined)})
    pairs.sort(key=lambda p: p["corr"])
    return {"members": len(series), "pairs": len(pairs), "mean_corr": sum(p["corr"] for p in pairs) / len(pairs),
            "lowest": pairs[0], "highest": pairs[-1], "returns_per_member": {s: len(r) for s, r in series.items()}}


def bulk_dist(frame):
    """Each member's return from its first to its last close in the window, and the largest one-day fall among all members."""
    years, worst = {}, None
    for symbol, close in closes(frame).items():
        years[symbol] = float(close.iloc[-1] / close.iloc[0] - 1)
        daily = close.pct_change().dropna()
        day = daily.idxmin()
        if worst is None or daily.min() < worst["return"]:
            worst = {"target": symbol, "date": str(day)[:10], "return": float(daily.min())}
    ranked = sorted(years.items(), key=lambda item: item[1])
    values = sorted(years.values())
    middle = len(values) // 2
    median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    return {"members": len(years), "median": median, "bottom3": ranked[:3], "top3": ranked[-3:][::-1], "worst_day": worst,
            "first_dates": sorted({str(c.index[0])[:10] for c in closes(frame).values()}),
            "last_dates": sorted({str(c.index[-1])[:10] for c in closes(frame).values()})}


CALCULATORS = {"bulk-corr-2025": bulk_corr, "bulk-dist-2025": bulk_dist}


def compute(scenario, frame):
    return CALCULATORS[scenario](frame)


def reference():
    """Read the 2025 closes straight from yfinance (dividend-unadjusted Close) and store them with the answers they imply."""
    import pandas as pd
    import yfinance as yf
    yf.config.debug.hide_exceptions = False
    read_at = dt.datetime.now(dt.timezone.utc).isoformat()
    rows = []
    for symbol in DOW_2025:
        history = yf.Ticker(symbol).history(start="2025-01-01", end="2026-01-01", interval="1d", auto_adjust=False, actions=False)
        for stamp, close in history["Close"].items():
            rows.append({"target": symbol, "date": stamp.date().isoformat(), "close": float(close)})
    frame = pd.DataFrame(rows)
    found = {"read_at": read_at, "source": "yfinance 1.7.0 Ticker.history(start=2025-01-01, end=2026-01-01, auto_adjust=False) Close",
             "answers": {name: calc(frame) for name, calc in CALCULATORS.items()}}
    by_symbol = {}
    for row in rows:
        by_symbol.setdefault(row["target"], []).append([row["date"], row["close"]])
    head = json.dumps(found, ensure_ascii=False, indent=1)[:-2]  # one line per symbol keeps the 7,500 closes reviewable
    body = ",\n".join(f"  {json.dumps(symbol)}: {json.dumps(values)}" for symbol, values in by_symbol.items())
    REFERENCE.write_text(head + ',\n "closes": {\n' + body + "\n }\n}\n", encoding="utf-8")
    return found


def stored():
    """The stored 2025 closes as long rows (target, date, close), for comparing with what a run received."""
    import pandas as pd
    closes = json.loads(REFERENCE.read_text(encoding="utf-8"))["closes"]
    return pd.DataFrame([{"target": s, "date": d, "close": c} for s, values in closes.items() for d, c in values])


def main():
    parser = argparse.ArgumentParser(description="Expected answers for the large-result scenarios; see the module docstring.")
    parser.add_argument("--reference", action="store_true", help=f"Fetch the 2025 closes from yfinance and write {REFERENCE.name}.")
    args = parser.parse_args()
    if args.reference:
        found = reference()
        print(json.dumps(found["answers"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
