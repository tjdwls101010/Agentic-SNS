# Holdout expectation — Novo Nordisk 20-F (`nvo-20251231.htm`)

Sealed 2026-09-22 from the original response bytes, before the rewrite ran against this document. Source facts were read with `lxml` directly; no `sec` module was imported.

Property under test: a foreign private issuer's annual report, whose practice differs from a domestic 10-K. The original has **0 `&#8203;`**, **0 `<th>`**, **0 `<style>`**, **0 `<h1>`–`<h6>`** and **107 tables**.

## The decisive fact

**Every `ITEM n` section heading in this document sits inside a table cell.** There is no `ITEM` heading in body prose anywhere in the file. Most of them are repeated page headers: `ITEM 4 INFORMATION ON THE COMPANY` occurs 7 times, `ITEM 6 DIRECTORS, EXECUTIVE MANAGEMENT AND EMPLOYEES` 6 times, `ITEM 5 OPERATING AND FINANCIAL REVIEW AND PROSPECTS` 5 times, `ITEM 10 ADDITIONAL INFORMATION` 3 times.

So the navigation layer, which is defined as emphasis outside tables, returns **no `ITEM` heading at all** for this document. That is the expected result, not a failure. What must hold instead:

1. `outline --kind emphasis` returning no section heading is itself reportable — the response says the navigation layer is empty rather than implying the document has no sections.
2. `outline --kind emphasis --all --in-tables only` reaches those headings, and each occurrence carries its own `table_id` and row so the repeated ones stay distinguishable. Grouping the 7 occurrences of `ITEM 4 INFORMATION ON THE COMPANY` into one item is correct; collapsing them to a single position is not.
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
