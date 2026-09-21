# SEC document originals

`provenance.json` maps the original document names to SEC URLs and SHA256 values of the exact original response bytes. Microsoft and Apple HTML are stored as standard gzip files to keep repository storage small; `storage` names the physical file and `compression: "gzip"` specifies decoding. Gzip uses compression level 9 with mtime=0 and no embedded filename. The original names and `sha256` fields remain unchanged; decompress before comparing that hash or passing bytes to SourceDocument. `stored_sha256` verifies the compressed file itself. No runtime parser support for gzip is needed or added.

`fixture_bytes` in `tests/sec/test_documents.py` reads the manifest and decompresses with Python's standard-library gzip. The other originals remain uncompressed. SEC response bytes are never normalized or regenerated; the HTML's XML declaration, ASML's DOCUMENT wrapper and old SGML boundaries are preserved exactly.

Microsoft, Apple, ASML and Form4 were obtained through the existing identified and paced SEC transport (Microsoft was supplied by root). The old 1995 complete submission was copied verbatim from the local edgartools original; its SEC-HEADER identifies the accession and CIK, but this work did not independently re-fetch that historical source. Paths in copied_verbatim_from record development provenance and are not runtime dependencies.

`expected.json` and `microsoft-expected.json` contain independently inspected original-source facts: Microsoft risk-tail wording, Apple years/units/values/spans, ASML's 12 actual image URLs, Form4 ownership paths and old submission types. Constructed edge cases are inline in the test module: test_synthetic_* cases and the explicitly marked test_review_* regression group are synthetic, not purported SEC originals.

## Tuning documents added for the grid rewrite (2026-09-22)

`nbis.html` is the NBIS 6-K EX-99.2 quarterly financial statements (accession `0001104659-26-094844`, 1,602,539 bytes). It is the document the grid model was designed against: 2,913 `&#8203;` layout cells, 79 tables, and a statement of changes in equity (`table-7`) in which two half-year periods are stacked vertically so that no single column meaning holds for the whole table.

`mrvl.html` is the Marvell 10-Q for the quarter ended 2026-08-01 (accession `0001835632-26-000025`, 2,026,559 bytes). It has no `&#8203;` at all, which is what makes it the counterweight to NBIS in the same tuning set.

Both are stored gzipped exactly as Microsoft and Apple are; `sha256` is the original response bytes and `stored_sha256` the gzip file.

## Holdout

`../holdout/` holds five documents that this rewrite was **not** run against while it was being built, one per property named in the plan: a 10-K from a different generator, a foreign private issuer's 20-F, a pre-HTML SGML submission, an XML record document, and an image-centric exhibit. `../holdout/expected/*.md` records what each one must produce, written by reading the originals with `lxml` and regular expressions before the rewrite existed. `../scenarios/` records the same kind of pre-registered answer for the model scenarios.
