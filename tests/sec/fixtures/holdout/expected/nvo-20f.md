# Holdout expectation — Novo Nordisk 20-F (`nvo-20251231.htm`)

Sealed 2026-09-22 from the original response bytes, before the rewrite ran against this document. Source facts were read with `lxml` directly; no `sec` module was imported.

Property under test: a foreign private issuer's annual report, whose practice differs from a domestic 10-K. The original has **0 `&#8203;`**, **0 `<th>`**, **0 `<style>`**, **0 `<h1>`–`<h6>`** and **107 tables**.

## The decisive fact

**Correction, made when the seal was lifted on 2026-09-22.** This section originally claimed that every `ITEM n` heading in this document sits inside a table cell and that the navigation layer would therefore return none of them. That claim was wrong, and the error was mine rather than the reader's: the scan I wrote it from was sorted by occurrence count and cut off with `head -30`, which dropped every heading that occurs once — that is, every real section boundary. Re-reading the original directly gives **31 `ITEM` headings in block-level elements outside any table, and 30 inside tables**. The corrected expectation is below; the run against it is recorded in the pull request.

`ITEM 1` through `ITEM 19` each appear once as a body heading outside any table, and again inside tables as repeated running page headers: `ITEM 4 INFORMATION ON THE COMPANY` 7 times, `ITEM 6 DIRECTORS, EXECUTIVE MANAGEMENT AND EMPLOYEES` 6 times, `ITEM 5 OPERATING AND FINANCIAL REVIEW AND PROSPECTS` 5 times, `ITEM 10 ADDITIONAL INFORMATION` 3 times.

What must hold:

1. `outline --kind emphasis` reaches each `ITEM n` section boundary once, from the body heading outside the tables.
2. `outline --kind emphasis --all --in-tables only` reaches the running page headers as well, and each occurrence carries its own `table_id` and row so the repeated ones stay distinguishable. Grouping the 7 occurrences of `ITEM 4 INFORMATION ON THE COMPANY` into one item is correct; collapsing them to a single position is not.
3. `outline --kind emphasis --in-tables only` is rejected with `invalid_argument`, because the navigation layer is defined as outside tables and an empty result there would read as "no emphasis inside tables".

## Reachability

`table-5` (36 rows) is the contents table; its entries name every `ITEM 1`–`ITEM 19` and must be reachable through `outline --kind table` and readable with one `table` call.

## Table reading

`table-63` — major shareholders, 7 rows. Row 1 is the label row; rows 3–6 are data.

| row | class | holder | shares owned | percent of class | percent of total votes |
|---|---|---|---|---|---|
| 3 | A shares | Novo Holdings A/S | 1,074,872,000 | 100.00 | 76.02 |
| 4 | B shares | Novo Holdings A/S | 177,560,500 | 5.24 | 1.26 |
| 5 | B shares | Novo Nordisk A/S and subsidiaries (treasury shares) | 21,375,280 | 0.63 | 0.15 |
| 6 | B shares | Board of Directors and executives | 1,173,813 | 0.03 | 0.01 |

Row 5 carries a footnote marker `*` in a cell of its own between the share count and the percent. The grid keeps it as its own cell.

`table-12` — company identity, 7 rows, two columns of label/value pairs: `Legal name: Novo Nordisk A/S`, `Date of incorporation: 28 November 1931`, `Country of incorporation: Denmark`.

## Scope honesty

This 20-F incorporates the Annual Report by reference: `table-98` maps each Item to page ranges in a document that is not in this file. There is **no** income statement or balance sheet table here. A reading that reports financial-statement figures from this document is wrong; the correct answer names `table-98` and says the statements are incorporated by reference.
