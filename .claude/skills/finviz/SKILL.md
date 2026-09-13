---
name: finviz
description: Read publicly accessible Finviz data for stock screening, company research and market exploration. Use when the user names Finviz or supplies a finviz.com URL, including follow-up questions continuing that work. Not a default for source-unspecified finance or screening requests, account changes, or developing Finviz-related code.
---

# Finviz data

Run the installed skill's locked CLI from any working directory:

```bash
uv run --isolated --frozen --project "${CLAUDE_SKILL_DIR}" python "${CLAUDE_SKILL_DIR}/scripts/finviz.py" --help
```

If the host leaves `${CLAUDE_SKILL_DIR}` literal, replace it with the absolute directory containing this SKILL.md. Command help, `catalog` and `schema` supply arguments, available data and result semantics; errors carry their recovery instructions. Large results remain in the observation store and expose IDs and pointers for further reading.

## Meaning comes from the source

Finviz uses `EPS next Y` for both a next-year EPS amount and a next-year EPS growth rate; the tooltip behind `EPS Q/Q` describes year-over-year growth. A display name alone therefore cannot identify the measure. Interpret the returned definition, unit and period together, and leave an unverified definition unresolved rather than supplying the familiar one.

## Scope travels with the observation

Receiving a result does not establish that every requested filter, ordering or date was applied. Use the returned application evidence and collection coverage when comparing results, and distinguish locally derived conditions or rankings from the original query. A page sequence can change while it is being collected, so finishing its pagination does not establish a single-moment census of the market.

## Time belongs to each observation

Choose a new query or saved-result reading according to whether the question concerns the present or the material already obtained. Collection time does not replace a market timestamp, reporting period or estimated event date. Map size weights and separately retrieved current market capitalizations likewise need their own source bases; do not treat one as the other merely because both describe size.

## Follow the evidence the question needs

A Finviz news listing locates an article; Market Pulse supplies a source-generated explanation rather than independently establishing why a price moved. Follow through to the body when the claim requires it. External articles and SEC originals remain links for the appropriate reader. The numerical map and bubble interfaces supply data; visual inspection, when relevant to a different question, uses the host's existing browser capabilities.
