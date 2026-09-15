---
name: finviz
description: Read publicly accessible Finviz data through a self-describing CLI: stock screening with Finviz filters and signals, company and ETF snapshots, statements, earnings history and estimates, dividends, revenue breakdown, short interest, options, SEC filing lists, price bars, sector and industry groups, market maps and bubbles, futures, forex and crypto quotes, earnings, dividend and economic calendars, news, Market Pulse and insider trades. Use when the user names Finviz — 핀비즈, 핀비즈에서, finviz 스크리너, 핀비즈 맵 — or supplies a finviz.com URL, and for follow-up questions continuing that work. Not the default for source-unspecified price, screening or financial-statement questions (yfinance covers those), not for Finviz account changes or Elite-only data, not for reading SEC originals or external articles, and not for writing Finviz-related code.
---

# Finviz through one CLI

Run the installed skill's locked CLI from any working directory:

```bash
uv run -q --frozen --project "${CLAUDE_SKILL_DIR}" python "${CLAUDE_SKILL_DIR}/scripts/finviz.py" --help
```

If the host leaves `${CLAUDE_SKILL_DIR}` literal, replace it with the absolute directory containing this SKILL.md. `--help` lists the groups, `GROUP LEAF --help` lists every argument with its default, and `schema GROUP LEAF` gives the output keys, the arguments that narrow a result and the exit codes; none of that is repeated here because a second copy is a second thing that can go stale. Every fetched response is saved under the `id` in its result, so `read ID --pointer /data` re-reads it in slices without another request, and every error carries a `fix` naming the next step.

## Which surface the question needs

A question that starts from conditions is `screen run`; the values it accepts come from `screen filters`, `screen signals` and `screen columns`, which take `--filter TEXT` because the filter list alone is 87 controls. One company's current figures are `stock snapshot`; reported results, expectations and their revisions are `stock statement`, `stock earnings` and `stock forecast`; aggregates by sector, industry or country are `groups` and `market map`; a URL the user pasted is `open`. Size changes the choice: `stock earnings --dataset revisions` holds thousands of estimate records, so narrow with `--fiscal-period` or `--limit` instead of reading it whole, and a screen that spans pages goes to a file with `--pages N --out rows.jsonl` while stdout keeps the summary and the next `--start`.

## Meaning comes from the source

A stock page shows `EPS next Y` twice, once as a next-year EPS amount and once as a growth rate, and the tooltip behind `EPS Q/Q` says year-over-year growth; an ETF repeats `Tags` seven times. A label alone never identifies a measure, so read the returned definition, unit and value together, keep repeated labels as separate records, and leave an unverified definition unresolved rather than supplying the familiar one. Table cells are source strings: `4827.02B`, `-0.70%` and `7,372.00` keep their units and signs, and the statement API publishes no scale, so do not restate them as bare numbers or a currency amount you inferred.

## Scope travels with the observation

Receiving rows does not establish that a filter, sort, page or date was applied: an unknown filter such as `cap_bogus` still returns twenty rows with HTTP 200. Each result carries `conditions` marked `confirmed`, `not_applied` or `unverified` with the page's own evidence, and `coverage` with what was received, what is shown after `--limit`, `--fields` or `--filter`, and the source's own total when it states one. The custom screener view has no filter controls, so filters stay `unverified` there; run the same filters on the overview view to confirm them. A page sequence can change while it is being collected, so a finished `--pages` run is not a single-moment census of the market.

## Time belongs to each observation

`observed_at` is when this CLI received the response. A quote's `as_of`, a statement's period end, an earnings date flagged `isEarningDateEstimate` and a price bar's epoch date answer different questions, so combine them by role rather than by recency. The map's `value` is its size weight and a bubble's `size` is the field you chose; neither is the market capitalisation on the snapshot, so do not treat one as the other because both describe size.

## Follow the evidence the question needs

News lists locate articles on other hosts: `url` is where the claim lives, and only `finviz.com/news/...` pages are readable with `news article`. Market Pulse is a source-generated explanation of a move, a lead rather than independent evidence. Filing lists and revenue breakdowns carry the original SEC URLs; the original document is the sec skill's job, and prices or statements from a source other than Finviz are yfinance's.

## When a result is too large

`too_large` is not a failure. The response is already saved under its `id`, and the fix names both the arguments that narrow this command and the `read` slice that reaches the rest without another request.
