---
name: yfinance
description: Read structured Yahoo Finance market and company data through a self-describing CLI. Use for current or historical prices, dividends and splits, financial statements, valuation measures, analyst estimates, ownership, ETF and fund holdings, options, stock/fund screening, markets and economic or company calendars — including 주가, 시세, 재무제표, 실적 추정, ETF 구성, 옵션 체인 and 종목 스크리닝 even when yfinance is not named. Supplies data for comparisons and analysis. Not for original SEC filing text, full news articles, trade execution, continuous streaming, or generic Python programming.
---

# Yahoo Finance data

## Execute and discover

Use the installed skill's locked environment from any working directory:

```bash
uv run --frozen --project "${CLAUDE_SKILL_DIR}/Scripts" python "${CLAUDE_SKILL_DIR}/Scripts/yfinance_cli.py" --help
```

If the host does not substitute `${CLAUDE_SKILL_DIR}`, replace it with the absolute directory containing this SKILL.md. In zsh, expanding one variable that holds a whole command does not split it into an executable and arguments; invoke the command directly or use a shell function that forwards `"$@"`.

## When a result is short

`partial` means part of what you asked for is missing: rows cut to fit the budget, or targets that failed while others succeeded. Rows that were cut are saved and reachable; a failed target is not. Either complete it or state the limitation in your answer — never describe a partial result as the whole.

`too_large` is a size condition, not an empty result, and it carries no partial table to summarize; the response is already saved under its `id`, so recovering it costs no new request.

Recover in a way that keeps the question: the same targets, fields and range, read from the store the `fix` names. A recovery that drops a target turns a comparison into a single-instrument question, and a narrower request answers a different question — say so if you take one. After rate limiting, stop rather than trying the remaining targets. State the coverage and limitations that affect the user's conclusion.

