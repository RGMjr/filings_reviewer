---
autonomy: review
discovered: '2026-04-20'
estimated: S
id: 59
note: New classifier patterns; FP risk
severity: low
slug: 8-k-section-classifier-produces-only-cover-financials-labels
source: legacy
status: resolved
title: 8-K Section Classifier Produces Only `COVER` / `FINANCIALS` Labels
touches:
- src/extraction_v2/classifier*.py
- tests/unit/extraction_v2/*classifier*
updated: '2026-04-27'
---

### Problem

`SectionClassificationStage.SECTION_PATTERNS` (`src/extraction_v2/stages/section_classification.py:104-138`) only knows S-1/10-K structural headings (`Item 1A`, `Item 7`, `Item 8`, etc.). 8-K earnings exhibits use narrative patterns like "Financial Highlights", "Key Business Metrics", "Q4 Highlights", "Results of Operations" that none of the existing patterns match. Phase 0 run: every segment on Chewy / DoorDash / Robinhood / Snowflake 8-Ks was classified as `COVER` or `FINANCIALS`. Candidate generation and value binding still produced correct facts, but sections-aware downstream logic (FP rules keyed on `section_type`, reviewer UI navigation, section-scoped metric scoring) is blind on 8-Ks.

### Next Steps

1. Add a new `SectionType` variant — e.g. `EARNINGS_HIGHLIGHTS` — or piggyback on `BUSINESS` if the existing type taxonomy already carries the right semantics.
2. Add pattern list entries for common 8-K headings: `Financial Highlights`, `Key Business Metrics`, `Q[1-4]\s*\d{4}\s*Highlights`, `Results of Operations`, `Business Highlights`.
3. Validate against the Phase 0 candidate set (Chewy, DoorDash, Robinhood, Snowflake 8-Ks) — expect >=30% of segments to land on non-COVER sections.
4. Audit existing FP rules for section-gated behavior that might fire differently once 8-K segments are correctly typed.

### Resolution

Extended `SectionClassificationStage.SECTION_PATTERNS` to recognize 8-K
earnings-exhibit headings, mapping to existing `KEY_METRICS`,
`FINANCIAL_OVERVIEW`, `GUIDANCE`, and `MDA` variants. No new `SectionType`
needed — existing presentation-slide types carry the right semantics. FP
rules in `false_positive_filter.py` only branch on transcript /
presentation types, so 8-K reclassification doesn't shift FP behavior.

Patterns added: `Results of Operations` (MDA); `Key Business Metrics`,
`Key Operating Metrics`, `Business Highlights`, `Operating Highlights`,
`Q[1-4] \d{4} Highlights` (KEY_METRICS); `Financial Highlights`
(FINANCIAL_OVERVIEW); `FY \d{4} Outlook`, `Q[1-4] \d{4} (Outlook|Guidance)`
(GUIDANCE).
