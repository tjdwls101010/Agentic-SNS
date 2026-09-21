# Holdout expectation — Apple 1996 complete submission (`0000320193-96-000023.txt`)

Sealed 2026-09-22 from the original response bytes, before the rewrite ran against this document. Boundaries and fields were read with a plain regex pass over the original text; no `sec` module was imported.

Property under test: a pre-HTML complete submission, where document boundaries are SGML tags and the file is wrapped in a PEM privacy-enhanced message. 271,212 bytes, `content-type: text/plain`.

## What must be recovered

`open` reports `format: sgml`, `status: parsed`, and **exactly 7 documents** in submission order. **No document has a `<FILENAME>`**; a parser that requires one fails this filing, which is precisely the regression this holdout exists to catch.

| sequence | type | description | body characters | first words of `<TEXT>` |
|---|---|---|---|---|
| 1 | `10-K` | *(none)* | 196,626 | `______… UNITED STATES SECURIT…` |
| 2 | `EX-10` | *(none)* | 36,753 | `EXHIBIT 10.A.5 APPLE COMPUTER, INC. 1990 STOCK OPTION PLAN` |
| 3 | `EX-10` | *(none)* | 22,670 | `EXHIBIT 10.A.6 APPLE COMPUTER, INC. EMPLOYEE STOCK PURCHASE PLAN` |
| 4 | `EX-10` | *(none)* | 10,282 | `EXHIBIT 10.A.40 August 19, 1996 Mr. Gerald F. Forsyth` |
| 5 | `EX-11` | *(none)* | 1,592 | `<TABLE> <CAPTION> EXHIBIT 11 … COMPUTATION OF EARNINGS (LOSS) PER COMMON SHARE` |
| 6 | `EX-21` | *(none)* | 536 | `EXHIBIT 21 SUBSIDIARIES OF APPLE COMPUTER, INC*` |
| 7 | `EX-27` | `ART. 5 FDS FOR FY95 FORM 10-K` | 1,034 | `<TABLE> <S> <C> <ARTICLE> 5 <MULTIPLIER> 1,000,000` |

The body is the text between the `<TEXT>` line and the `</TEXT>` line, both excluded. When these counts were first recorded the span measured also included the closing tag and the blank lines after it, which made each one 10 to 18 characters longer; the numbers above are the same documents under the stated definition.

`description` is absent on six of seven documents and present on the last. A missing `<DESCRIPTION>` must be `null`, not an empty document or a dropped row.

Three sequences appear with the same `TYPE` (`EX-10` at 2, 3, 4). They must stay three separate documents; keying by type would collapse them.

## Boundaries

- 7 `<DOCUMENT>` opens and 7 `</DOCUMENT>` closes; every document terminates. Nothing may be silently discarded.
- The submission metadata (`<TYPE>`, `<SEQUENCE>`, `<DESCRIPTION>`) is read **before** each `<TEXT>`; `<TEXT>` bodies in documents 5 and 7 themselves contain `<TABLE>`, `<S>`, `<C>`, `<ARTICLE>` and other angle-bracket tokens, and document 7's body ends with `<EPS-DILUTED>` lines. None of those may be mistaken for submission metadata.
- The file opens with `-----BEGIN PRIVACY-ENHANCED MESSAGE-----` and six lines of PEM headers before `<SEC-DOCUMENT>`, and closes with `</SEC-DOCUMENT>` then `-----END PRIVACY-ENHANCED MESSAGE-----`. The text outside the document boundaries is preserved as its own blocks, not dropped.
- Offsets are character offsets into the decoded text. The original is Latin-1-decodable and contains no multi-byte sequences, so a byte/character confusion would not show up here; the offsets recorded above are byte-equal by coincidence and must not be relied on as proof.

## Content reachability

- `find "Net sales"` reaches the selected-financial-data line in document 1: `Net sales $9,833 $11,062 $ 9,189 $ 7,977 $ 7,086`, immediately followed by `Net income (loss) $(816) $ 424 $ 310 $ 87 $ 530`. The parenthesized loss `$(816)` must survive normalization unchanged.
- `find "SUBSIDIARIES OF"` reaches document 6 and not document 1.
- Reading document 7 reaches `<TOTAL-ASSETS> 5,364` and `<EPS-PRIMARY> (6.59)`.

An answer that attributes an exhibit's statement to the 10-K, or the reverse, fails this holdout regardless of whether the numbers are right.
