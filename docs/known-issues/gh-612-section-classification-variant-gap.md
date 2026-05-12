---
id: 612
source: gh
slug: section-classification-variant-gap
title: "section_classification: heading-markup variant still produces zero whitelisted sections on ~11% of corpus (post-gh-574)"
status: open
severity: medium
autonomy: skip
estimated: —
touches:
  - src/extraction_v2/stages/ingestion.py
  - src/extraction_v2/stages/section_classification.py
  - tests/unit/extraction_v2/test_ingestion.py
discovered: 2026-05-11
updated: 2026-05-11
gh_issue: 612
note: gh-574 fix caught Datadog/Chewy anchor-name heading shape but ~11% of Phase-2 corpus still hits 0 whitelisted sections; affected filings 209382, 215071, 833, 10273, 192171, 207445
---

### Problem

During Phase-2 gate run `20260511T1416live`, 6 of 55 filings (≈11%) returned 0 paraphrase segments because `section_classification` detected no whitelisted sections (MDA, Business, Risk Factors). All 6 wrapped pipeline in 3–7 seconds vs. the typical 9–15 min, confirming the paraphrase path was inert.

Affected filings: 209382 (12 MB, `{COVER: 0}`), 215071 (4.5 MB, `{COVER: 0, FINANCIALS: 1}`), 833, 10273, 192171, 207445.

The gh-574 fix (retain short paragraphs with `<a name>` anchor targets) addressed the Datadog/Chewy heading shape but missed at least one other variant. Impact: these filings only contribute keyword-baseline signal, structurally biasing Phase-2 gate comparison — paraphrase classifier cannot contribute additional positives on filings whose paraphrase path never runs.

### Next Steps

- Inspect HTML structure of the affected filings around MD&A / Risk Factors / Business section starts; identify the variant heading markup.
- Extend `SECTION_PATTERNS` or `_is_section_heading()` to cover the variants.
- Add a diagnostic that flags filings where ingestion produced ≥1000 segments but section_classification detected zero whitelisted sections, so operators see this before paying for a gate run.
