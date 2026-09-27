---
name: yfinance
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
description: Read structured Yahoo Finance market and company data through a self-describing CLI. Use for current or historical prices, dividends and splits, financial statements, valuation measures, analyst estimates, ownership, ETF and fund holdings, options, stock/fund screening, markets and economic or company calendars — including 주가, 시세, 재무제표, 실적 추정, ETF 구성, 옵션 체인 and 종목 스크리닝 even when yfinance is not named. Supplies data for comparisons and analysis. Not for original SEC filing text, full news articles, trade execution, continuous streaming, or generic Python programming.
---

# Yahoo Finance data

Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …` on one line. `--help` gives the commands, their arguments and the exit codes, `schema` what results, fields and units mean, and each error's `fix` how to recover.
