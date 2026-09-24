---
name: finviz
description: Read publicly accessible Finviz data through a self-describing CLI: the stock screener and its filters, a company's or ETF's overview, earnings, estimates, statements, options, filings and holdings, sector and industry groups, market maps and bubbles, futures, forex and crypto, calendars, news, Market Pulse and insider trades. Use when the user names Finviz — 핀비즈, 핀비즈에서, finviz 스크리너, 핀비즈 맵 — or supplies a finviz.com URL, and for follow-up questions continuing that work. Not the default for source-unspecified price, screening or financial-statement questions (yfinance covers those), not for Finviz account changes or Elite-only data, not for reading SEC originals or external articles, and not for writing or designing code that parses or calls Finviz.
---

# Finviz through one CLI

```bash
uv run -q --frozen --project "${CLAUDE_SKILL_DIR}" python "${CLAUDE_SKILL_DIR}/scripts/finviz.py" --help
```

If the host leaves `${CLAUDE_SKILL_DIR}` literal, use the absolute directory containing this SKILL.md. In zsh a variable holding a whole command does not split into a program and its arguments; call the command directly or define a shell function that forwards `"$@"`. `--help` lists the groups and `GROUP LEAF --help` a command's arguments; `schema` describes the result envelope every command shares, and `schema GROUP LEAF` one command's collections, order, default window and units. Read arguments, output and recovery there.

## Which request answers the question

A few measures across several stocks are one screener request: `screen run --tickers A,B,C` with a `--view` returns them as rows; a page holds 20 rows and filters still apply, so check that every ticker came back. Many measures of a few stocks are cheaper as their overviews, one request each with every snapshot metric and its definition, than as several screener views. A result with an `id` is a saved observation: `read ID` with that command's own selectors (another `--filter`, `--fields`, `--start` or `--section`) selects from it again without asking Finviz.

## Meaning comes from the source

A label does not identify a measure. Read each value with the definition and unit the result returns (a snapshot row's `definition`, the `units` in schema), and leave open what the source does not state rather than filling it from what you know, such as whether "next year" is fiscal and when a company's fiscal year ends, which EPS basis a figure uses, what a growth rate is measured against or what a return includes; PEG, for instance, has several conventions and Finviz does not say which it uses. When you add a cause or a fact the result does not carry, mark it as yours: the reader takes everything unmarked as what Finviz reported. A screener filter is likewise the source's bucket, such as "+Large (over $10bln)", not the user's threshold: report the bucket you applied and say where it differs from what was asked.

## Time belongs to each value

`observed_at` is when this CLI received the response. A quote's `as_of`, a statement's period end, a headline's `date` and an estimate's `estimateDate` are the source's own times: state each value with the time that belongs to it, and report a `last_close` with the quote time its result gives (`as_of` or `last_time`), or as undated where there is none, never as a live price.
