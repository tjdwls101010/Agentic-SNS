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

Discover in three steps: `--help` for the groups, `schema GROUP` for its commands, `schema GROUP LEAF` for that command's arguments, default window, units, known limits and gotchas. The interface owns all of that. Nothing here repeats it, because a copy of it here would go on asserting the old contract after the command changed.

Reuse returned symbols, expirations and keys exactly as they came back, in your answer as well as in the next call: adding or removing punctuation in a symbol names a different instrument.


## Numbers arrive without their units

The library has already turned every value into a float, so nothing in a number says what it measures, and a label can be actively wrong about it. Before reporting a figure, read that field's contract in `schema GROUP LEAF` under `units`, which states the scale (a ratio like 0.0452, or a percent like 4.52), the kind, and whether the value is the reciprocal of its own label.

These are not rare. The same measurement appears on both scales in different commands and occasionally inside one result, and a whole family of fund multiples arrives inverted, so a price-to-earnings figure below 1 is an earnings yield rather than an impossible multiple. Do not settle the question from the magnitude — plausible-looking numbers are exactly where this goes wrong. Where `units` says nothing about a field, say what the source called it rather than converting it.

The currency a price is quoted in and the currency a company reports its statements in are different fields and often different currencies. A ratio built from one of each is wrong by the exchange rate, which for a Japanese reporter quoted in dollars is about a hundredfold. One statement also mixes measurements: a tax rate sits in the same column as an amount in the trillions.

## Times answer different questions

A result separates the time the source put on the data, the time this CLI received the response, and — when reading a saved observation — how long ago that was. They are not interchangeable: after a close the source's time can be hours behind the observation, so a value observed a minute ago is not a current price. Receiving something recently never makes it current.

A fiscal period end, an announcement date and a market timestamp answer different questions too, and one row can mix them: a holdings row can carry a position filed months ago valued at today's price. A trailing or "current" column is a rolling snapshot, not a completed reporting period. Keep exchange timezones as returned.

## Values arrive already transformed

The adjustment applied decides what a closing price means, so adding dividends to an already adjusted return counts them twice. Repair is a transformation with its own limits, not evidence that a value equals the original trade. Where the source has already collapsed a distinction — a zero turned into a null upstream — that information is gone, and a null there cannot be restored or read as a zero.

## The default answer is a window, not everything

Every command returns one screen by default and `coverage` states what that cost: how many rows arrived, how many were printed, and which end a limit kept. Read it rather than assuming the rows you can see are all there were.

The status distinguishes the two ways a result can be short. `ok` means this command's own default window, which is the contract and is usually enough. `partial` means the range **you** asked for did not fit the budget and was cut — then either read the rest or state the limitation in your answer. Never describe a `partial` window as the whole period.

A successful call is not evidence that a condition was applied. Where the response carries evidence, `conditions` reports each one as confirmed, not applied, or unverified; read that rather than assuming an argument took effect because rows came back. For the same reason, describe a named preset by the query the result carries, not by its name — a preset's name is not a statement of what it screens for.

An empty return and a null are observations of nothing usable, not measurements of zero, and they do not prove the thing does not exist. Between pages the source can change, so an offset continues a query rather than reading a fixed snapshot.

## When you are blocked

Every response is saved before anything is selected from it, so a result that was too large is not lost: the `id` reaches it and `read` returns it in slices without paying for the request again. `too_large` is a size condition, never an empty result, and it never carries a partial table to summarize.

The `fix` on an error names a narrowing that actually works for that command, and where the source stated its own constraint the fix names the argument and value to change. Follow it as written, including every target and store it names — a recovery that quietly drops one target turns a comparison into a single-instrument question. After rate limiting, stop rather than trying the remaining targets. State the coverage and limitations that affect the user's conclusion.
