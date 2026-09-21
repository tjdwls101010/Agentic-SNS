# Scenario 3 reference — how MRVL describes supply constraints

Recorded 2026-09-22 at stage 0, before the rewrite existed, by reading the three originals with `lxml` directly. The scenario asks a model with only SKILL.md to answer "how does MRVL describe supply constraints" from these three accessions; this file is what its answer is compared against.

Accessions, given to the model in full and not abbreviated:

| accession | primary document | period |
|---|---|---|
| `0001835632-25-000197` | `mrvl-20251101.htm` | quarter ended 2025-11-01 |
| `0001835632-26-000019` | `mrvl-20260502.htm` | quarter ended 2026-05-02 |
| `0001835632-26-000025` | `mrvl-20260801.htm` | quarter ended 2026-08-01 |

## The sentence that changes

The one risk-factor sentence stating the company's own current condition is the answer, and it is different in each filing:

- `0001835632-25-000197` — "We have in the past including in the first few quarters of fiscal 2023, and may in the future, experience a number of industry-wide supply constraints." Followed by: "During the first few quarters of fiscal 2023, supply shortages in the semiconductor industry of multi-layer complex substrates, IC packaging capacity, and specific wafer process node constraints resulted in increased lead times, inability to meet demand, and increased costs."
- `0001835632-26-000019` — "We have in the past and may in the future, experienced a number of industry-wide supply constraints." The fiscal-2023 elaboration is **gone**.
- `0001835632-26-000025` — "**We are currently in a supply constrained environment.**" This is a present-tense statement about the company's own position, not a historical or hypothetical one.

A correct answer reports this progression: historical with a named episode → historical, generalized → present and current.

## The new section in the most recent filing

`0001835632-26-000025` adds a Management's Discussion section headed **`Supply Constraints`**, which the two earlier filings do not have. Its opening paragraph:

> The ability of each of our manufacturing partners to provide us with materials and services is limited by its available capacity and existing obligations. Currently, the demand for our products is strong, and availability of our partners' to provide sufficient capacity, including advanced process node wafers, to meet customer demand is constrained. With certain exceptions our partners are not obligated to perform services or supply products to us for any specific period, in any specific quantities, or at any specific price, except as may be provided in a particular purchase order.

An answer that cites only the risk-factor boilerplate and misses this section has found the words but not the disclosure.

## Boilerplate present in all three, which is not the answer

These sentences are identical or near-identical across all three filings. An answer built on them cannot distinguish the periods and therefore does not answer the question:

- "risks related to the extension of lead time due to supply chain disruptions, component shortages that impact the costs and production of our products…" (forward-looking-statements list)
- "Moreover, if any of our third-party manufacturing partners or other suppliers are unable to secure the necessary raw materials…"
- "In particular, as we and others in our industry transition to smaller geometries, our manufacturing partners may be supply constrained or may charge premiums for these advanced technologies…"
- "Because we rely on outside manufacturing partners, we have a reduced ability to directly control product delivery schedules and quality assurance…"
- "natural disasters or other events, including droughts or other water shortages…"

## Note on 0001835632-26-000025

This is also the MRVL tuning fixture (`tests/sec/fixtures/documents/mrvl.html.gz`), so the scenario's third document is not held out. The other two accessions were read once here and are not stored as fixtures; the scenario fetches them live.
