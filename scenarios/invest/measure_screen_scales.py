"""Measure Yahoo's scale for each rate field of the screener, the evidence behind invest/yahoo/screen.py SCALES.

Two readings per field, against the live screener:
- counts: the same field screened over a percent-point band (20..30) and the matching ratio band (0.2..0.3); Yahoo's total for the band on its own scale is many times the other's, because a 20-30% margin is common and a 0.2-0.3% one rare (bands differ by field family);
- counterpart: where the info response carries the same measurement (quarterlyrevenuegrowth.quarterly and revenueGrowth), a few returned symbols' info values, as ratios, must fall inside the band read on that scale.
A field is `percent` or `ratio` when the counts differ by at least RATIO_MIN and no counterpart contradicts them; otherwise it stays unmeasured, and the CLI refuses it unless --source-units is given.

usage: uv run --no-project --exclude-newer 2026-09-13T13:10:00Z --with "yfinance[repair]==1.7.0" python scenarios/invest/measure_screen_scales.py
writes scenarios/invest/screen-scales.json; copy its `scales` into SCALES by hand after reading the evidence.
"""
import csv
import datetime as dt
import json
from pathlib import Path
import subprocess
import time

import yfinance as yf

OUT = Path(__file__).with_name("screen-scales.json")
CLI = Path(__file__).resolve().parents[2] / ".claude/skills/invest/scripts/cli.py"
RATIO_MIN = 5
# (percent band, ratio band) per family: each band is where values of that family commonly sit on its own scale.
BANDS = {"growth": ((20, 30), (0.2, 0.3)), "margin": ((20, 30), (0.2, 0.3)), "return": ((10, 20), (0.1, 0.2)), "held": ((20, 40), (0.2, 0.4)),
         "short": ((2, 4), (0.02, 0.04)), "yield": ((2, 4), (0.02, 0.04)), "debtequity": ((50, 100), (0.5, 1.0)), "change": ((1, 3), (0.01, 0.03)),
         "expense": ((0.3, 0.8), (0.003, 0.008)), "turnover": ((20, 50), (0.2, 0.5))}
# Query field -> the info field carrying the same measurement, and the scale of that info field's raw value.
COUNTERPARTS = {
    "quarterlyrevenuegrowth.quarterly": ("revenueGrowth", "ratio"), "returnonequity.lasttwelvemonths": ("returnOnEquity", "ratio"),
    "returnonassets.lasttwelvemonths": ("returnOnAssets", "ratio"), "grossprofitmargin.lasttwelvemonths": ("grossMargins", "ratio"),
    "netincomemargin.lasttwelvemonths": ("profitMargins", "ratio"), "ebitdamargin.lasttwelvemonths": ("ebitdaMargins", "ratio"),
    "pctheldinsider": ("heldPercentInsiders", "ratio"), "pctheldinst": ("heldPercentInstitutions", "ratio"),
    "short_percentage_of_float.value": ("shortPercentOfFloat", "ratio"), "short_percentage_of_shares_outstanding.value": ("sharesPercentSharesOut", "ratio"),
    "forward_dividend_yield": ("dividendYield", "percent"), "totaldebtequity.lasttwelvemonths": ("debtToEquity", "percent"),
    "percentchange": ("regularMarketChangePercent", "percent"), "fiftytwowkpercentchange": ("fiftyTwoWeekChangePercent", "percent"),
}
UNIVERSES = {"equity": (yf.EquityQuery, ["region", "us"]), "etf": (yf.ETFQuery, ["region", "us"])}


def family(field):
    for name, words in (("growth", ("growth",)), ("margin", ("margin",)), ("return", ("return",)), ("held", ("pctheld",)), ("short", ("short_",)),
                        ("yield", ("yield",)), ("debtequity", ("debtequity",)), ("change", ("percentchange", "pricechange")),
                        ("expense", ("expenseratio",)), ("turnover", ("turnover",))):
        if any(w in field for w in words):
            return name
    return None


def total(kind, field, band):
    cls, region = UNIVERSES[kind]
    query = cls("and", [cls("eq", region), cls("btwn", [field, band[0], band[1]])])
    for attempt in range(3):
        try:
            response = yf.screen(query, size=5, count=5, sortField="ticker", sortAsc=False)
            return response.get("total"), [q.get("symbol") for q in response.get("quotes") or []], response.get("quotes") or []
        except Exception as exc:
            if attempt == 2:
                return f"error: {exc}", [], []
            time.sleep(5)


def counterpart(field, symbols, rows, band, scale):
    """Whether the returned symbols' own values of the same measurement, read as ratios, fall inside the band read on `scale`."""
    info_field, info_scale = COUNTERPARTS[field]
    low, high = (band[0] / 100, band[1] / 100) if scale == "percent" else band
    checked = []
    for symbol, row in list(zip(symbols, rows))[:3]:
        value = row.get(info_field)
        if value is None:
            try:
                value = yf.Ticker(symbol).get_info().get(info_field)
            except Exception:
                value = None
            time.sleep(0.5)
        if value is None:
            continue
        ratio = value / 100 if info_scale == "percent" else value
        checked.append({"symbol": symbol, info_field: value, "inside": low - 1e-9 <= ratio <= high + 1e-9})
    return checked


def measure(kind, field):
    name = family(field)
    if name is None:
        return {"field": field, "verdict": "unmeasured", "reason": "no band for this field family"}
    percent_band, ratio_band = BANDS[name]
    as_percent, percent_symbols, percent_rows = total(kind, field, percent_band)
    time.sleep(0.5)
    as_ratio, ratio_symbols, ratio_rows = total(kind, field, ratio_band)
    time.sleep(0.5)
    found = {"field": field, "type": kind, "percent_band": percent_band, "total_in_percent_band": as_percent, "ratio_band": ratio_band,
             "total_in_ratio_band": as_ratio}
    if not (isinstance(as_percent, int) and isinstance(as_ratio, int)):
        return {**found, "verdict": "unmeasured", "reason": "a screen failed"}
    if as_percent >= RATIO_MIN * max(as_ratio, 1) and as_percent >= RATIO_MIN:
        verdict = "percent"
    elif as_ratio >= RATIO_MIN * max(as_percent, 1) and as_ratio >= RATIO_MIN:
        verdict = "ratio"
    else:
        return {**found, "verdict": "unmeasured", "reason": "the two bands' totals do not differ enough"}
    if field in COUNTERPARTS:
        symbols, rows, band = (percent_symbols, percent_rows, percent_band) if verdict == "percent" else (ratio_symbols, ratio_rows, ratio_band)
        found["counterpart"] = counterpart(field, symbols, rows, band, verdict)
        if found["counterpart"] and not all(c["inside"] for c in found["counterpart"]):
            return {**found, "verdict": "unmeasured", "reason": "a returned symbol's own value contradicts the counts"}
    return {**found, "verdict": verdict}


def rate_fields(kind):
    """The fields the CLI itself treats as rates (input_unit ratio), read from its own `screen fields` result file."""
    proc = subprocess.run(["uv", "run", "--quiet", str(CLI), "screen", "fields", "--type", kind], capture_output=True, text=True, timeout=300)
    receipt = json.loads(proc.stdout)
    with open(receipt["file"]["path"], newline="", encoding="utf-8") as handle:
        return sorted(row["field"] for row in csv.DictReader(handle) if row["input_unit"] == "ratio")


def main():
    yf.config.debug.hide_exceptions = False
    results = []
    for kind in UNIVERSES:
        for field in rate_fields(kind):
            results.append(measure(kind, field))
            print(json.dumps(results[-1]), flush=True)
    scales = {}
    for r in results:
        if r["verdict"] in ("percent", "ratio"):
            if scales.get(r["field"], r["verdict"]) != r["verdict"]:
                scales[r["field"]] = "conflict"
            else:
                scales[r["field"]] = r["verdict"]
    OUT.write_text(json.dumps({"measured_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "yfinance": yf.__version__,
                               "scales": {k: v for k, v in sorted(scales.items()) if v != "conflict"}, "evidence": results}, indent=1) + "\n")


if __name__ == "__main__":
    main()
