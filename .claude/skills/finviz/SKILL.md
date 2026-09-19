---
name: finviz
description: Read publicly accessible Finviz data through a self-describing CLI: stock screening with Finviz filters and signals, company and ETF snapshots, statements, earnings history and estimates, dividends, revenue breakdown, short interest, options, SEC filing lists, price bars, sector and industry groups, market maps and bubbles, futures, forex and crypto quotes, earnings, dividend and economic calendars, news, Market Pulse and insider trades. Use when the user names Finviz — 핀비즈, 핀비즈에서, finviz 스크리너, 핀비즈 맵 — or supplies a finviz.com URL, and for follow-up questions continuing that work. Not the default for source-unspecified price, screening or financial-statement questions (yfinance covers those), not for Finviz account changes or Elite-only data, not for reading SEC originals or external articles, and not for writing Finviz-related code.
---

# Finviz through one CLI

Run the installed skill's locked CLI from any working directory:

```bash
uv run -q --frozen --project "${CLAUDE_SKILL_DIR}" python "${CLAUDE_SKILL_DIR}/scripts/finviz.py" --help
```

If the host leaves `${CLAUDE_SKILL_DIR}` literal, replace it with the absolute directory containing this SKILL.md. In zsh, expanding one variable containing a whole command does not split it into an executable and arguments; invoke the command directly or use a shell function that forwards `"$@"`. `--help` lists the groups, `GROUP LEAF --help` a command's own arguments, and `schema GROUP LEAF` its full contract: defaults, output shape, which arguments narrow it and what each exit code means. Those own the arguments and the recovery instructions, so read them there rather than guessing a flag.

## Which surface the question needs

A question that starts from conditions is `screen run`, and the values it accepts come from `screen filters`, `screen signals` and `screen columns`. One company's current figures are `stock snapshot`; reported results, expectations and their revisions are `stock statement`, `stock earnings` and `stock forecast`. Aggregates by sector, industry or country are `groups` and `market map`. A URL the user pasted is `open`. Several sections of one company's overview — snapshot, profile, ratings, news, insiders, ownership — are readings of a single page, not separate sources.

## Meaning comes from the source

A stock page shows `EPS next Y` twice, once as a next-year EPS amount and once as a growth rate, and the tooltip behind `EPS Q/Q` says year-over-year growth; an ETF repeats `Tags` seven times. A label alone never identifies a measure, so read the returned definition, unit and value together, keep repeated labels as separate records, and leave an unverified definition unresolved rather than supplying the familiar one. Table cells are source strings: `4827.02B`, `-0.70%` and `7,372.00` keep their units and signs, and the statement API publishes no scale, so do not restate them as bare numbers or a currency amount you inferred.

## Scope travels with the observation

Receiving rows does not establish that a filter, sort, page or date was applied: an unknown filter such as `cap_bogus` still returns twenty rows with HTTP 200, and an unknown bubble universe silently answers with every listed stock. Results with tracked selectors carry `conditions` marked `confirmed`, `not_applied` or `unverified` with the source's own echo as evidence; collection results carry `coverage` with received and shown counts and the source's total when it states one. These fields are optional: their absence does not confirm a selector or establish completeness. The custom screener view has no filter controls, so filters stay `unverified` there; run the same filters on the overview view to confirm them. A page sequence can change while it is being collected, so a finished multi-page run is not a single-moment census of the market. A record that looks anomalous, such as an estimate mean that drops for a week and recovers, is still the source's record: report it as observed and leave its cause open rather than dismissing it or supplying a reason the data does not contain.

## Time belongs to each observation

`observed_at` is when this CLI received the response, and a section extracted from an earlier observation carries that earlier time. A quote's `as_of`, a statement's period end, an earnings date flagged `isEarningDateEstimate` and a price bar's epoch date answer different questions, so combine them by role rather than by recency. The map's `value` is its size weight and a bubble's `size` is the field you chose; neither is the market capitalisation on the snapshot, so do not treat one as the other because both describe size.

## Follow the evidence the question needs

News lists locate articles on other hosts: `url` is where the claim lives, and only `finviz.com/news/...` pages are readable with `news article`. Market Pulse is a source-generated explanation of a move, a lead rather than independent evidence. Filing lists and revenue breakdowns carry the original SEC URLs; the original document is the sec skill's job, and prices or statements from a source other than Finviz are yfinance's.

## What a default answer covers

Each command answers with what one look at that screen shows — the newest headlines, the strikes around the money, the filter catalogue without its option lists — and `coverage` reports `received` against `shown` whenever that left something out. So a default answer is a window, not an inventory: forty of today's headlines is not "today's news", and the whole of anything is asked for, not assumed. `too_large` is a budget condition rather than an empty or missing result; the response is already saved under its `id`, the message names the narrowing that fits, and `read` returns any part of it without asking Finviz again.
