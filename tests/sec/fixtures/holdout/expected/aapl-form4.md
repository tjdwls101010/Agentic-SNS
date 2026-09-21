# Holdout expectation — Apple Form 4 XML (`form4.xml`, accession 0001140361-26-037020)

Sealed 2026-09-22 from the original response bytes, before the rewrite ran against this document. Values were read from the raw XML; no `sec` module was imported.

Property under test: an XML record document, where the evidence is the path and the attribute rather than prose. 9,257 bytes, `content-type: text/xml`.

## What must be reported

`open` reports `format: xml`, `status: parsed`. The reader returns path-addressed items, not a prose stream; `read` on this snapshot must carry `path`, `parent` and `attributes` rather than a joined paragraph.

Identity:

- `/ownershipDocument[1]/documentType[1]` = `4`
- `/ownershipDocument[1]/periodOfReport[1]` = `2026-09-15`
- `/ownershipDocument[1]/issuer[1]/issuerCik[1]` = `0000320193`, `issuerName[1]` = `Apple Inc.`, `issuerTradingSymbol[1]` = `AAPL`
- `/ownershipDocument[1]/reportingOwner[1]/reportingOwnerId[1]/rptOwnerCik[1]` = `0001780525`, `rptOwnerName[1]` = `Newstead Jennifer`
- `/ownershipDocument[1]/reportingOwner[1]/reportingOwnerRelationship[1]/officerTitle[1]` = `SVP, GC and Government Affairs`

## The distinguishing requirement

There are **three** `nonDerivativeTransaction` elements, all dated `2026-09-15`, all with `securityTitle/value` = `Common Stock`. They are distinguishable only by their repeated-record index:

| index | transactionShares/value | transactionPricePerShare/value | transactionCode | sharesOwnedFollowingTransaction/value |
|---|---|---|---|---|
| 1 | 1438 | 330.19 | (disposition) | 32914 |
| 2 | 30104 | — | (acquisition) | 63018 |
| 3 | 16228 | 331.34 | (disposition) | 46790 |

A read that returns `Common Stock` three times without the index, or that reports one `sharesOwnedFollowingTransaction` for the filing, fails. The final holding after the last reported transaction is **46,790**, not 32,914 and not the sum of the three.

## Footnotes

`<footnoteId id="F1"/>`, `id="F2"` and `id="F3"` are empty elements carrying only an attribute. Their `id` must appear in `attributes`; an extractor that reads element text only loses the link between a value and its footnote, and the values above then look unqualified when they are not.

- Transaction 1's `securityTitle` references `F1`.
- Transaction 2's `transactionShares` references `F2`.
- Transaction 3's `securityTitle` references `F3`.

**Correction, made when the seal was lifted on 2026-09-22.** The table above enumerates only the non-derivative transactions. The filing also has a `derivativeTable` holding one entry, whose `sharesOwnedFollowingTransaction/value` is **180624** — restricted stock units, a different security from the common stock above. Any check that gathers every path containing `sharesOwnedFollowingTransaction` finds four values, not three, and that is correct. The statement that the common-stock holding after the last reported transaction is 46,790 stands.

`<issuerForeignTradingSymbol></issuerForeignTradingSymbol>` and `<rptOwnerStreet2></rptOwnerStreet2>` are present and empty. Empty is a reported fact here; the element must remain addressable rather than be dropped as blank.
