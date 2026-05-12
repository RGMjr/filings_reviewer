---
id: 574
source: gh
slug: datadog-section-classification-toc-anchor-gap
title: "section_classification: TOC-anchor heading markup detects 0 whitelisted sections, paraphrase path inert"
status: resolved
severity: medium
autonomy: n/a
estimated: —
touches:
  - src/extraction_v2/stages/ingestion.py
  - tests/unit/extraction_v2/test_ingestion.py
discovered: 2026-05-08
updated: 2026-05-08
gh_issue: 574
pr_refs:
  - 589
  - 614
note: "Root cause is the 50-char MIN_PARAGRAPH_CHARS floor in ingestion (not section_classification). Datadog's bare-heading <P>s carry an `<a name>` anchor target but text below the floor, and get filtered before Stage 2 sees them. Fix retains short paragraphs that carry an anchor target."
---

### Problem

Phase-1 smoke eval (run_id `20260508T1743`) revealed Datadog's S-1 (filing 1539) is the only filing of 5 in the gold corpus where `section_classification` detects **zero** whitelisted sections (MDA, Business, Risk Factors). Detected map: `{COVER: 0, FINANCIALS: 3}`. As a result, the LLM paraphrase-recall path was completely inert — `paraphrase_segs=0` versus the other 4 filings' 604–891 paraphrase candidates.

### Root cause (verified 2026-05-08)

The fragment originally hypothesized TOC-anchor markup in `<TD>` cells. **Re-investigation against the cached gold HTML showed a different cause** in ingestion, not section_classification:

- Datadog's section-START headings are plain `<P>` elements containing an `<a name="...">` anchor target. Examples (`data/gold_standard/Datadog,_Inc_/filing.html`): line 2408 `<P ... ALIGN="center"><B><A NAME="toc745413_2"></A>RISK FACTORS </B></P>` (text length 12); lines 6036–6037 split MD&A across two short `<P>`s (39 + 45 chars).
- All three are below `IngestionStage.DEFAULT_MIN_PARAGRAPH_CHARS = 50` and are dropped at `_extract_paragraph_segments_with_elements` line 590 — **before** they reach Stage 2. `SECTION_PATTERNS` and `_is_section_heading()` work correctly; the segments they would match are already gone.
- Working filings (e.g., Maplebear) survive because the full title is in one paragraph (85 chars), comfortably above the floor.

Not a smoke-gate blocker (catastrophic-regression check passed), but a systematic gap that hurts Tier-1 recall on Datadog-style filings and likely contributes to gh-575 (LTV-per-customer 0-recall).

### Fix

Retain short paragraphs (below `MIN_PARAGRAPH_CHARS`) when they contain an `<a name>` or `<a id>` anchor target — the standard SEC section-anchor signal. `<a href>` (link) does NOT count, to keep TOC entries from flooding through. Purely additive change: long paragraphs unaffected.

Verification on filing 1539 post-fix: `section_classification` detects `risk_factors: 1`, `mda: 1`, `business: 1` (was zero).

### Resolution

Fixed by PR #589 (merged 2026-05-09). Added `_has_anchor_target()` predicate to `IngestionStage` that retains short paragraphs carrying an `<a name>` or `<a id>` anchor target, allowing Datadog-style section headings below `MIN_PARAGRAPH_CHARS` to survive ingestion and reach `section_classification`. Smoke-eval verification: confirmed post-fix that filing 1539 now detects `risk_factors: 1`, `mda: 1`, `business: 1` (was all zero).

Bookkeeping closed by PR #614.
