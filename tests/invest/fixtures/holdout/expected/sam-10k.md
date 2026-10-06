# Holdout expectation — Boston Beer 10-K (`sam-20251227.htm`)

Sealed 2026-09-22 from the original response bytes, before the rewrite ran against this document. Source facts were read with `lxml` directly; no `sec` module was imported.

Property under test: a 10-K from a generator other than the tuning set. The original has **0 `&#8203;`**, **0 `<font>`**, **0 `<th>`**, **0 `<style>`**, **0 `<h1>`–`<h6>`** and 26,192 inline `style=` attributes across **55 tables**. Every normalization and emphasis rule tuned on NBIS/Apple/MRVL must therefore hold without a ZWSP layout cell anywhere.

## Reachability

`outline --kind emphasis`, following continuations to the end, must reach each of the sixteen body section headings. In this document the heading is **not** its own block: the emphasized run is a truncated prefix (`Item 1A. R`, `Item 7. Management’s Discussion and Analysis of`) inside a `<p>` that continues straight into the section's prose. So a rule that requires emphasis to cover most of the block will not return them, and then the model must be able to descend with `--all` and still find them.

Whichever layer returns it, the following must be reachable and must carry a position that `read` accepts:

- `Item 1. Business`, `Item 1A. Risk Factors`, `Item 1B. Unresolved Staff Comments`, `Item 1C. Cybersecurity`
- `Item 2. Properties`, `Item 3. Legal Proceedings`, `Item 4. Mine Safety Disclosures`
- `Item 5. Market for Registrant's Common Equity…`, `Item 6. [Reserved]`, `Item 7. Management's Discussion and Analysis…`, `Item 7A. Quantitative and Qualitative Disclosures About Market Risk`, `Item 8. Financial Statements and Supplementary Data`
- `Item 9. …`, `Item 9A. Controls and Procedures`, `Item 9B. Other Information`, `Item 9C. …`
- `Item 10.`–`Item 16. Form 10-K Summary`

Each of these appears **twice** in the original: once in the contents table near the front (`Item 1.` alone in one cell, the title in another) and once at the section itself. The contents occurrence is inside a table and the section occurrence is not; both occurrences must remain addressable, and the table one must carry its `table_id`.

## Table reading

`table-10` is the combined statement of operations and comprehensive income: **34 rows**, 13 original columns, context `(in thousands, except per share data)`.

It has the same vertical restart the grid model was designed for — row 23 is `Net income` in the operations statement and row 28 is `Net income` again where the comprehensive-income statement begins. A single column meaning fixed over the whole table would be wrong here, exactly as in NBIS `table-7`.

Values that must be read correctly, with row label and column period paired:

| row | label | FY2025 | FY2024 | FY2023 |
|---|---|---|---|---|
| 4 | Revenue | 2,087,251 | 2,137,802 | 2,133,292 |
| 6 | Net revenue | 1,964,994 | 2,012,926 | 2,008,625 |
| 16 | Operating income | 144,882 | 75,973 | 100,001 |
| 23 | Net income | 108,469 | 59,695 | 76,250 |
| 24 | Net income per common share - basic | 9.90 | 5.07 | 6.23 |
| 33 | Comprehensive income | 108,785 | 59,056 | 76,403 |

Column periods come from rows 1–2: `Year Ended` spans, then `December 27,2025`, `December 28,2024`, `December 30,2023`.

Two structural facts the grid must preserve rather than repair:

- Negative values are split across adjacent cells — row 19 `Other expense, net` is `(1,361` in one cell and `)` in the next. The grid keeps both cells as they are; it must not join them into `(1,361)` and must not drop the lone `)`.
- The currency symbol `$` occupies its own cell, separate from the number.

`table-10` must be returned by one `table` call within the default budget.

## Whole-document

- `open` reports `format: html`, `status: parsed`, and a table list whose entries include `table-10` with its row and folded-column counts.
- `table-0`…`table-4` are cover-page layout tables; their folded size identifies them as such rather than as evidence.
