---
id: 574
source: gh
slug: datadog-section-classification-toc-anchor-gap
title: "section_classification: TOC-anchor heading markup detects 0 whitelisted sections, paraphrase path inert"
status: open
severity: medium
autonomy: skip
estimated: —
touches:
  - src/extraction_v2/stages/section_classification.py
  - tests/unit/extraction_v2/stages/test_section_classification.py
discovered: 2026-05-08
updated: 2026-05-08
gh_issue: 574
note: Datadog S-1 and similar TOC-anchor-wrapped markup match no SECTION_PATTERNS; paraphrase recall path completely inert
---

### Problem

Phase-1 smoke eval (run_id `20260508T1743`) revealed Datadog's S-1 (filing 1539) is the only filing of 5 in the gold corpus where `section_classification` detects **zero** whitelisted sections (MDA, Business, Risk Factors). Detected map: `{COVER: 0, FINANCIALS: 3}`. As a result, the LLM paraphrase-recall path was completely inert — `paraphrase_segs=0` versus the other 4 filings' 604–891 paraphrase candidates.

The other 4 gold filings (1545, 1550, 191794, 1146) all match `MDA: 1`, meaning the heading-pattern regex finds the start of MD&A and propagates the section tag forward. Datadog's HTML wraps heading text inside `<TD><P><A HREF="#anchor">RISK FACTORS</A></P></TD>` table cells — `_is_section_heading()` and the anchored regexes in `SECTION_PATTERNS` don't match the resulting segment text shape.

Not a smoke-gate blocker (catastrophic-regression check passed), but a systematic gap that hurts Tier-1 recall on Datadog-style filings and likely contributes to gh-575 (LTV-per-customer 0-recall).

### Next Steps

- Inspect the `segment.text` values around Datadog's MD&A / Risk Factors anchors after ingestion to see what shape they take.
- Either extend `SECTION_PATTERNS` to cover the variants observed, or relax `_is_section_heading()` to admit TOC-anchor segment shapes.
- Re-run Phase-1 smoke eval; confirm Datadog `paraphrase_segs > 0`.
