---
name: invest
description: Read structured Yahoo Finance market and company data through a CLI built for analysis, and what a company says in its own SEC filings. Use for current or historical prices, dividends and splits, financial statements, valuation, analyst estimates, ownership, ETF and fund holdings, options, screening, markets and economic or company calendars, and for how management reads its results, its outlook, its industry, customers, suppliers and partners — including 주가, 시세, 재무제표, 실적 추정, ETF 구성, 옵션 체인, 종목 스크리닝, 경영진의 실적 해석, 회사 전망, 산업 시각, 고객·공급사 관계 and 10-K·10-Q·8-K·6-K·20-F 원문 even when Yahoo is not named. Not for filings Yahoo does not list, full news articles, Finviz-specific data, trade execution, or generic Python programming.
allowed-tools: Bash(uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" *)
---

# Investment research data

Run `uv run "${CLAUDE_SKILL_DIR}/scripts/cli.py" <command> …` on one line. `--help` maps the commands; `<command> --help` gives that command's kinds, arguments, receipt, failures and exit codes. Each call prints a short JSON receipt and saves the whole result as a file the receipt names.

Numbers Yahoo carries come from the data commands. What the company itself says, and numbers Yahoo does not carry (segment figures, guidance, customer concentration), come from its filings.

## Turning a result into an answer

Compute from the file the receipt names (`file.path`), reading it with your own Python: the inline rows, or the first and last rows of a trimmed receipt, are there to check a result, not to stand for it. Values arrive on one scale — a rate is a ratio (0.0245 is 2.45%), a multiple is a multiple — and `units` names each column's unit, so convert nothing; a value whose unit is `unverified` is not one to compute with.

The receipt also says what the numbers cannot show, because the data looks the same either way; carry it into the answer:

- A last bar marked provisional or unknown is the price so far, not a close: keep it where the question asks for the latest data, and label it as such.
- A list covers only what its `coverage` says (the largest holders, Yahoo's recent insider transactions, a first page, the rows a screen matched), so something absent from it is not evidence that it did not happen.
- A condition the call asked for (a date range, a screen query) holds for the returned rows only as far as `conditions` confirms it: rows it names as outside the request are left out of the answer or named, and a condition the rows could not show is unverified, not applied.
- A target that failed or was not attempted is named with the code the receipt gives, and the answer says what is missing without it; it is neither filled in nor given a reason the receipt does not state.
- Money is in the currency the receipt names for its role: `currency` for quote values, `financial_currency` for statement values. When the two differ, as for an ADR, a ratio that mixes them is wrong by the exchange rate.

## What a company says in its filings

`company filings SYMBOL` lists the filings Yahoo currently has; in its result file each filing's `exhibits` maps a document type to Yahoo's copy of the SEC original. Titles are generic ("Corporate Changes & Voting Matters" for most 8-Ks), so choose by type, date and exhibits. Management's own account sits in an earnings 8-K's EX-99.1 (at some companies also a CFO commentary as EX-99.2), a 10-Q's or 10-K's MD&A and Risk Factors, a 10-K's Item 1, and a foreign issuer's 6-K exhibits and 20-F. When a short main document only refers to its exhibits, open the exhibit. A filing missing from the list is not proof it was never filed.

`filing URL…` saves a document as a text file and prints its map (`filing --help` describes both). Read the map, then the lines the question needs with Read (offset and limit) or `grep -n`. A 10-K or 20-F runs 200–600K characters, so reading one whole spends most of a context on text the question does not need; a 10K-character press release is worth reading whole.

Cite the original document (its source URL, form or exhibit, and filing date) and its section or table. A line number is a place in the local file only.
