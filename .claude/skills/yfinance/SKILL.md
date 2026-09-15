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

If the host does not substitute `${CLAUDE_SKILL_DIR}`, replace it with the absolute directory containing this SKILL.md. Start with the CLI's data groups, then read the selected command's help or scoped `schema`. They own arguments, defaults, output fields, condition syntax and recovery. List available fields and identifiers where the command offers discovery; reuse returned symbols, expirations and sector keys in subsequent calls. The interface supplies the information needed to query without reconstructing Python calls or reading the library's source.

In zsh, expanding one variable containing a whole command does not split it into an executable and arguments. Invoke the command directly or use a shell function that forwards `"$@"`.

## Select the target and data

A company-name search returns candidates. Use the exchange, instrument type and identifying fields to choose the intended security; an equity, its depositary receipt and a similarly named fund are different targets. Ask when the remaining ambiguity would change the answer. Screening returns matches to particular conditions, not an independently verified census of a market.

Keep returned symbols unchanged when reporting as well as querying: adding or removing punctuation can identify a different instrument.

Choose datasets from the question: a statement supplies reported results, analyst estimates describe expectations, and a calendar describes events. Combine the calls the question needs rather than fetching every available dataset. Returned news and filing entries locate sources; use the appropriate reader when the answer requires the article or original filing itself.

## Interpret periods, units and adjustments

A financial period end, an announcement date, a price's market timestamp and the time this CLI observed a response answer different questions. Preserve those roles when combining results; an observation time does not make every returned value current. Calendars can match different date fields, and a latest valuation column is not another completed reporting period. The selected command describes its actual date boundaries and coverage.

Interpret prices using the applied adjustment and repair conditions. Adjusted prices and cash distributions can overlap economically, so adding dividends to an already adjusted return can count them twice. Repair is a transformation with its own limitations, not proof that a value equals the original trade. Keep exchange timezones, currencies and source units when comparing instruments. A financial statement can contain monetary amounts, per-share figures and ratios together; one currency label does not make every row a currency amount.

## Interpret coverage and failure

Separate the requested scope, the observed response and the selected output: the document-level request records what was asked, and a result's context reports what was actually applied to that target and rows returned before and after `--limit`. A populated result can coexist with failed or unattempted targets. Empty returns and null values are observations of missing usable data, not proof of no trading, no holdings or no event; do not replace them with zero. Preserve reported upstream information loss instead of inferring the missing distinction.

Use errors and their recovery instructions to decide whether to correct an argument, narrow the requested output, or stop after a provider restriction. A size error supplies no partial dataset to summarize as complete. A remote offset continues a query, not an immutable snapshot: results can move between calls, and an unknown remaining count is not zero. State the coverage and limitations that affect the user's conclusion.
