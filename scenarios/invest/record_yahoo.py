"""Record what Yahoo answers to the requests the invest CLI makes, as replayable fixtures for tests/invest.

Each case runs the real CLI against the network through recording/sitecustomize.py and writes tests/invest/fixtures/yahoo/<case>.json: the provenance (when, which yfinance, the command) and the routes the test transport replays, with the parameters that change on every call (the crumb, computed timestamps) left out so a replay matches on what the request asks for. Run it only to add or refresh a fixture; the tests read the files, never the network.

usage: python3 scenarios/invest/record_yahoo.py [CASE ...]   (default: every case)
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / ".claude/skills/invest/scripts/cli.py"
OUT = REPO / "tests/invest/fixtures/yahoo"
VOLATILE = {"crumb", "period1", "period2", "corsDomain", "lang", "region", "formatted"}

CASES = {
    "quote-ko": ["quote", "KO"], "quote-tm": ["quote", "TM"], "quote-gspc": ["quote", "^GSPC"], "quote-xyzqq": ["quote", "XYZQQ"],
    "quote-twtr": ["quote", "TWTR"],
    "history-aapl": ["history", "AAPL", "--start", "2026-09-28", "--end", "2026-10-03", "--adjust", "none"],
    "history-arm-2021": ["history", "ARM", "--start", "2021-01-01", "--end", "2022-01-01"],
    "history-xyzqq": ["history", "XYZQQ", "--period", "5d"],
    "history-intraday-reach": ["history", "AAPL", "--period", "1y", "--interval", "1m"],
    "history-actions-ko": ["history", "KO", "--start", "2025-01-01", "--end", "2026-01-01", "--actions"],
    "company-profile-aapl": ["company", "profile", "AAPL"], "company-shares-aapl": ["company", "shares", "AAPL", "--start", "2026-01-01", "--end", "2026-03-01"],
    "company-news-aapl": ["company", "news", "AAPL", "--limit", "50"], "company-filings-aapl": ["company", "filings", "AAPL"],
    "financials-income-tm": ["financials", "income", "TM"], "financials-balance-ko": ["financials", "balance", "KO", "--frequency", "quarterly"],
    "financials-cashflow-aapl": ["financials", "cashflow", "AAPL", "--frequency", "trailing"], "financials-valuation-tm": ["financials", "valuation", "TM"],
    **{f"analysts-{k}-aapl": ["analysts", k, "AAPL"] for k in ("targets", "recommendations", "upgrades", "eps-estimate", "revenue-estimate", "eps-history",
                                                               "revisions", "trend", "growth")},
    "analysts-eps-estimate-tm": ["analysts", "eps-estimate", "TM"],
    **{f"holders-{k}-aapl": ["holders", k, "AAPL"] for k in ("major", "institutional", "funds", "insider-purchases", "insider-transactions", "insider-roster")},
    **{f"fund-{k}-qqq": ["fund", k, "QQQ"] for k in ("overview", "description", "holdings", "asset-classes", "sectors", "equity", "operations")},
    "fund-holdings-aapl": ["fund", "holdings", "AAPL"],
    "options-expirations-aapl": ["options", "expirations", "AAPL"], "options-chain-aapl": ["options", "chain", "AAPL"],
    "screen-fields": ["screen", "fields"], "screen-values": ["screen", "values", "--field", "region"], "screen-presets": ["screen", "presets"],
    "screen-run-growth": ["screen", "run", "--query", '{"operator":"AND","operands":[{"operator":"EQ","operands":["region","us"]},{"operator":"GT","operands":["intradaymarketcap",10000000000]},{"operator":"GT","operands":["quarterlyrevenuegrowth.quarterly",0.2]}]}', "--limit", "25"],
    "screen-run-preset": ["screen", "run", "--preset", "day_gainers", "--limit", "25"],
    "market-summary": ["market", "summary"], "market-sector-overview": ["market", "sector", "technology"],
    "market-sector-companies": ["market", "sector", "technology", "--dataset", "top-companies"], "market-sector-etfs": ["market", "sector", "technology", "--dataset", "top-etfs"],
    "market-industry-performing": ["market", "industry", "semiconductors", "--dataset", "top-performing"],
    "market-industry-research": ["market", "industry", "semiconductors", "--dataset", "research-reports"],
    "calendar-earnings-day": ["calendar", "earnings", "--start", "2026-10-01", "--end", "2026-10-01"],
    "calendar-earnings-aapl": ["calendar", "earnings", "AAPL", "--limit", "25"],
    "calendar-economic": ["calendar", "economic", "--start", "2026-10-05", "--end", "2026-10-09", "--limit", "25"],
    "calendar-ipo": ["calendar", "ipo", "--start", "2026-10-05", "--end", "2026-10-09"],
    "calendar-splits": ["calendar", "splits", "--start", "2026-10-05", "--end", "2026-10-09", "--limit", "25"],
    "search-quotes": ["search", "apple"], "search-news": ["search", "apple", "--dataset", "news"],
}


def tables_only(text):
    """An HTML page cut to its tables, which is all yfinance reads from it; a whole Yahoo page is close to a megabyte."""
    tables = re.findall(r"<table.*?</table>", text, re.S)
    return "<html><body>" + "".join(tables) + "</body></html>" if tables else text


def route(entry):
    found = {"path": entry["path"], "params": {k: v for k, v in entry["params"].items() if k not in VOLATILE}, "status": entry["status"]}
    if entry["body"]:
        found["body"] = entry["body"]
    if "json" in entry["content_type"]:
        try:
            found["json"] = json.loads(entry["text"])
            return found
        except ValueError:
            pass
    found["text"] = tables_only(entry["text"]) if "html" in entry["content_type"] else entry["text"]
    return found


def record(name, argv):
    with tempfile.TemporaryDirectory(prefix="invest record ") as work:
        log = Path(work) / "log.jsonl"
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).with_name("recording")), INVEST_RECORD=str(log), INVEST_DATA=str(Path(work) / "data"),
                   YF_TEST_CACHE=str(Path(work) / "cache"))
        proc = subprocess.run(["uv", "run", "--quiet", str(CLI), *argv], capture_output=True, text=True, env=env, timeout=600)
        entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
    fixture = {"provenance": {"recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "yfinance": "1.7.0",
                              "argv": argv},
               "routes": [route(e) for e in entries]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return proc.returncode, len(entries)


def main():
    parser = argparse.ArgumentParser(description="Record Yahoo's answers to the invest CLI's requests as test fixtures; see the module docstring.")
    parser.add_argument("cases", nargs="*", help=f"Case names (default: all {len(CASES)}).")
    args = parser.parse_args()
    unknown = sorted(set(args.cases) - set(CASES))
    if unknown:
        parser.error(f"unknown cases {unknown}")
    for name in args.cases or CASES:
        code, count = record(name, CASES[name])
        print(f"{name}: exit {code}, {count} requests", file=sys.stderr)


if __name__ == "__main__":
    main()
