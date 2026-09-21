# Holdout expectation — ASML investor presentation (`presentationinvestorrela.htm`)

Sealed 2026-09-22 from the original response bytes, before the rewrite ran against this document. Image list and text were read with a plain regex pass; no `sec` module was imported.

Property under test: an image-centric document. 20,278 bytes of HTML holding **19 `<img>` elements**, **0 tables**, **0 `<th>`**, **0 `<style>`**, **0 `<h1>`–`<h6>`** and 19 `<font>` tags. The content of the slides — the charts and the figures on them — exists only inside the JPEGs.

**The expected result is an honest report that the document cannot be navigated as text, not an extraction.**

## What must hold

- `open` reports `format: html`, `status: parsed`, and a warning naming the limitation: image content is not extracted. `known_extraction_limits` is non-empty and includes that fact. An empty list here would assert completeness the extraction does not have.
- `links --kind image` returns all **19** images, in document order, from `presentationinvestorrela001.jpg` through `presentationinvestorrela019.jpg`, each resolved against the filing directory `https://www.sec.gov/Archives/edgar/data/937966/000162828026025147/`. This is the only route to the actual evidence, so it must be complete and it must not depend on any heading being detected.
- `outline --kind table` is empty because there are no tables. That is correct and must be reported as an empty result rather than an error.
- `outline --kind emphasis` may be empty or nearly so. An empty navigation layer here is the true observation.

## The text that does exist

About 14,000 characters of slide furniture are extractable and must not be mistaken for the content:

- The exhibit banner `EX-99.2 3 presentationinvestorrela.htm EX-99.2`
- The title block `ASML 2026 first-quarter results`, `Veldhoven, the Netherlands April 15, 2026`
- `ASML reports €8.8 billion total net sales and €2.8 billion net income in Q1 2026`
- `ASML now expects 2026 total net sales to be between €36 billion and €40 billion, with a gross margin between 51% and 53%`
- Per-slide furniture: `Page 2April 15, 2026 Public`, and the agenda bullets `Investor key messages`, `Business summary`, `Outlook`, `Financial statements`

`€` arrives as `&#8364;` and `•` as `&#8226;` in the original; both must appear as the actual characters in the reading text, and `&nbsp;` runs must not be counted as content.

A correct answer to "what does the Q1 revenue chart show" names the image URL and says the figure is in an image that text extraction cannot establish. A correct answer to "what were Q1 net sales" cites €8.8 billion from the title block, because that sentence is genuinely in the text.
