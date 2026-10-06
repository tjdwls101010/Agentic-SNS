---
name: invest
description: Read structured Yahoo Finance market and company data through a CLI built for analysis. Use for current or historical prices, dividends and splits, financial statements, valuation, analyst estimates, ownership, ETF and fund holdings, options, screening, markets and economic or company calendars — including 주가, 시세, 재무제표, 실적 추정, ETF 구성, 옵션 체인 and 종목 스크리닝 even when Yahoo is not named. Not for original SEC filing text, full news articles, Finviz-specific data, trade execution, or generic Python programming.
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
---

# Investment research data

Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …` on one line. `--help` maps the commands; `<command> --help` gives that command's kinds, arguments, receipt, failures and exit codes. Each call prints a short JSON receipt and saves the whole result as a file the receipt names.

The numbers Yahoo carries come from these commands: prices, statements, estimates, holders, fund data, options, screens and calendars.

## Turning a result into an answer

Compute from the file the receipt names (`file.path`), reading it with your own Python: the inline rows, or the first and last rows of a trimmed receipt, are there to check a result, not to stand for it. Values arrive on one scale — a rate is a ratio (0.0245 is 2.45%), a multiple is a multiple — and `units` names each column's unit, so convert nothing; a value whose unit is `unverified` is not one to compute with.

The receipt also says what the numbers cannot show, because the data looks the same either way; carry it into the answer:

- A last bar marked provisional or unknown is the price so far, not a close.
- A list covers only what its `coverage` says (the largest holders, Yahoo's recent insider transactions, a first page, the rows a screen matched), so something absent from it is not evidence that it did not happen.
- A screen condition holds for the returned rows only as far as `conditions` confirms it; one the rows could not show is unverified, not applied.
- A target that failed or was not attempted is named with the code the receipt gives, and the answer says what is missing without it; it is neither filled in nor given a reason the receipt does not state.
- Money is in the currency the receipt names for its role: `currency` for quote values, `financial_currency` for statement values. When the two differ, as for an ADR, a ratio that mixes them is wrong by the exchange rate.
