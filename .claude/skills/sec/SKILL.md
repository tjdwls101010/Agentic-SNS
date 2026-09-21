---
name: sec
description: Read original SEC EDGAR company filings and exhibits, identify companies and reporting periods, and follow evidence through text, tables and images. Use for SEC·EDGAR·미국 공시, company filing forms such as 10-K, 10-Q, 8-K, 6-K, 20-F or Form 4, SEC filing URLs, and for the text inside them — risk factors, management's discussion, financial statement tables and their footnotes, exhibits and their images, including 미국 기업의 연차보고서·분기보고서 원문, 위험요인 원문, 재무제표 표와 주석, 지분변동표 — even when EDGAR is not named. Use it when the question asks where a number came from and only the filing says so. Not for structured price or financial-statement series, which yfinance covers; not for SEC rules or enforcement, general news, Korean DART filings, or sec meaning seconds.
---

# SEC

## Running it

Resolve this skill's installed directory and use its locked environment, including when the working directory is another project:

```bash
uv run -q --isolated --frozen --project "${CLAUDE_SKILL_DIR}/Scripts" python "${CLAUDE_SKILL_DIR}/Scripts/sec.py" --help
```

If the host does not substitute `${CLAUDE_SKILL_DIR}`, replace it with the absolute directory containing this SKILL.md. In zsh, expanding one variable that holds a whole command does not split it into an executable and arguments; invoke the command directly, or use a shell function that forwards `"$@"`.

`--help` and `schema` own the arguments, output fields, exit codes and recovery instructions. `schema COMMAND` describes one command, including the errors that command can return and what to do about each. `doctor` reports whether a requester identity is configured, without printing it.

## Choosing the document

A full-text search hit is one document, not one filing: exhibits are searched directly, and one hit can carry several filers, each with its own URL under its own CIK. The accession prefix identifies whoever transmitted the filing, which is often a filing agent rather than the issuer. Take the CIK from the filer entry, not from the accession.

A short primary report often incorporates by reference the exhibit that actually contains the evidence — an earnings release, a financial-statements exhibit, an agreement. A foreign issuer's 20-F may incorporate its whole annual report from a document that is not in the filing at all. When a filing's own text points elsewhere, follow it and say which document the answer came from.

## Reading what the filing lays out

A table arrives as a grid of its original row and column numbers. Consecutive pipes are empty cells in the original, not missing data.

**Nothing decides which row is a header, and you should not assume one.** The measured filings declare no `<th>` at all — where a filing does declare one it arrives on the cell, but most do not, so which row labels the columns is yours to read off the grid. One statement can restart partway down: NBIS's statement of changes in equity puts the six months to June 2025 in rows 1–13 and starts again for June 2026 at row 15, under a second copy of the labels. Fixing one meaning for a column over a whole table is wrong for half of that one.

Merged cells arrive as spans, where `colspan` is what the document said and `w` is how many surviving columns the merge still covers. A value's units and qualifications usually sit in the rows above it or in a footnote beside it, both of which `table` returns.

`emphasis` is an observation of what the document did to make a passage stand out — the fraction in bold, its size against the document's own body text, its alignment — not a promise of a section boundary. Where the navigation layer comes back empty or thin, that is itself the observation: drop to `--all`. Some filings put every section heading inside a table cell, and then the headings are reachable only that way.

## Reading around a match

`find` gives a position and, for a match inside a table, the table, row and column it landed in. Read around it before treating it as the section you wanted: the same words appear in a contents page, in a repeated page header and in the section itself, and the response keeps those apart by position.

A position locates the saved copy, not the SEC page. Cite the returned original URL, and where the filing declares no anchor, identify the section or the phrase rather than inventing a fragment.

## What an incomplete read means

`scope_complete` says the range you selected came back whole. `known_extraction_limits` is a different question: it names what this extraction could not do, and an empty list means no known limit rather than a guarantee. Neither one says the original contains nothing relevant.

Text extraction cannot establish what a chart shows. `links --kind image` gives the actual image URLs for inspection with a viewer, and that route does not depend on any heading being detected — for an image-centric exhibit it is the only route to the content.

Search totals can be lower bounds, and a timed-out or window-capped search is not exhaustive even when the page looks complete. Full-text search covers 2001 onward, so a missing hit says nothing about an older filing; `filings` for the company does.
