---
name: sec
description: Read original SEC EDGAR company filings and exhibits, identify companies and reporting periods, and follow evidence through text, tables and images. Use for SEC·EDGAR·미국 공시, company filing forms such as 10-K, 10-Q, 8-K, 20-F or Form 4, and SEC filing URLs. Not for SEC rules or enforcement, current stock prices, general news, or sec meaning seconds.
---

# SEC

## Purpose and entry point

Find the right EDGAR source and read as much of it as the question needs. The CLI handles identified HTTPS access, saved documents and navigation; it does not need Aside or a SEC login.

Resolve this skill's installed directory and use its locked environment, including when the working directory is another project:

```bash
uv run --isolated --frozen --project "${CLAUDE_SKILL_DIR}/Scripts" python "${CLAUDE_SKILL_DIR}/Scripts/sec.py" --help
```

If the host does not substitute `${CLAUDE_SKILL_DIR}`, replace it with the absolute directory containing this SKILL.md. Command help and `schema` own the arguments, output fields and recovery instructions. Their settings diagnosis is the place to resolve access problems; another account's identity is not a substitute for the configured requester.

## Choose the company and period

A name match is a candidate, not an identity. Resolve ambiguous names using the returned CIK and identifying evidence; an exhibit may mention a company that did not submit it, and a search hit may have several filers. Keep those roles separate when choosing the source.

Submission date answers when a filing arrived. Report date describes its reported period, not every date or comparison inside it. A request for the latest annual report and one for results during a particular fiscal year can therefore select different documents. Confirm the period in the passage or table being cited. An amendment is a separate filing and can change only part of an earlier report; read the relevant original when the amendment relies on it.

Full-text search coverage and a company's filing history are different. A missing search hit does not establish that an older filing is unavailable. Use the supplied filing identifier or original URL when that is stronger evidence than a name or keyword search.

## Follow evidence through a filing

Choose the next source from what the question needs: a filing's document list distinguishes the primary report from exhibits, while a body-search result may point directly to an exhibit. Earnings releases, agreements and presentations can carry the evidence that a short primary report only incorporates by reference. Preserve the document's identity when following that link.

Use actual contents links and anchors where available; detected headings are navigation hints, not promised section boundaries. Repeated labels can belong to a contents page or to comparative material. Read around a match before treating it as the requested section, and follow the returned continuation when the relevant passage extends beyond the excerpt.

## Read text, tables and images

Navigate with the returned snapshot and positions so searches and excerpts address the same saved text. Internal positions locate that copy; only a verified source anchor locates the SEC page. Cite the returned original URL and, when no source anchor is available, identify the section or search phrase rather than inventing a fragment.

A table value needs its row, column header, unit and qualifying footnotes. Merged cells and nearby prose can supply that context; an isolated numeric match cannot. Long cells continue just as prose does. Follow their remaining range before claiming to have read the entire cell or table.

Text extraction cannot establish what a chart shows. Image and PDF links expose the actual source for visual inspection with an available viewer; use that when the answer depends on the visual. XML paths and repeated-record context distinguish transactions that share the same tag names. In a submission text file, retain the document boundaries so an exhibit's statement is not attributed to another document.

## What an incomplete read means

A completed selected range says what was returned, not that the document was fully extracted. Missing contents, unsupported media, decoding uncertainty, parsing failure and access failure have different implications. Preserve the reported limitation; none establishes that the original contains no relevant information.

Search totals can be lower bounds, and a timed-out or capped search is not exhaustive even if the displayed page is complete. Received pages are saved observations; a later remote page can reflect a changed index. Use their observation times and duplicate handling to describe coverage without claiming an unseen result set was frozen.
