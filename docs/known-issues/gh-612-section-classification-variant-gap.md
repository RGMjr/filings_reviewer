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
updated: 2026-05-14
gh_issue: 612
note: Three additive fixes — element-level id retention, short-heading text retention, company-prefixed MDA pattern + relaxed _is_section_heading. All 6 filings now detect MDA + other whitelisted sections.
---

### Problem

During Phase-2 gate run `20260511T1416live`, 6 of 55 filings (≈11%) returned 0 paraphrase segments because `section_classification` detected no whitelisted sections (MDA, Business, Risk Factors). All 6 wrapped pipeline in 3–7 seconds vs. the typical 9–15 min, confirming the paraphrase path was inert.

Affected filings: 209382 (AgileThought, 12 MB), 215071 (Waldencast, 4.5 MB), 833 (Concrete Pumping), 10273 (Bazaarvoice), 192171 (Diamond Eagle / DraftKings, 7.7 MB), 207445 (Ouster, 4.7 MB).

The gh-574 fix (retain short paragraphs with `<a name>` anchor targets) addressed the Datadog/Chewy heading shape but missed multiple other variants. Impact: these filings only contribute keyword-baseline signal, structurally biasing Phase-2 gate comparison — paraphrase classifier cannot contribute additional positives on filings whose paraphrase path never runs.

### Root cause (verified 2026-05-14)

Three distinct failure modes across the 6 filings:

1. **Element-level `id=` attribute, no nested `<a name>`** (filing 207445): heading wrapped in `<div id="rom156556_4">RISK FACTORS</div>`. gh-574's `_has_anchor_target` only checked for descendant `<a name>` / `<a id>` tags, not the element's own `id` attribute.

2. **Short heading text below `MIN_PARAGRAPH_CHARS` floor with no anchor signal at all** (filings 209382, 833, 10273, 192171): bare paragraphs like `RISK FACTORS` (12 chars) or `Item 1A.Risk Factors` are dropped by ingestion's short-paragraph filter before section_classification ever sees them.

3. **Company-prefixed MDA heading** (filings 215071, 192171): `WALDENCAST'S MANAGEMENT'S DISCUSSION...` or `DRAFTKINGS' MANAGEMENT'S DISCUSSION...` — the heading text survives to section_classification but the `SECTION_PATTERNS` regex for MDA requires text to start with `MANAGEMENT`, so the prefix prevents the match.

4. **Mixed-case heading text** (filing 833 once headings reach section_classification): `_is_section_heading()` rejects segments that aren't predominantly uppercase, so even when the text reaches the section_classification stage, the heading is treated as body text.

### Fix (additive, three changes)

**Fix A** (`src/extraction_v2/stages/ingestion.py`): extend `_has_anchor_target` to also return True when the element itself has a non-empty `id=` attribute, not just nested `<a name>`/`<a id>` descendants.

**Fix B** (`src/extraction_v2/stages/ingestion.py`): add `_SECTION_HEADING_TEXT_RE` matching common section-start strings (RISK FACTORS, ITEM N[A-Z]?, MANAGEMENT'S DISCUSSION, DESCRIPTION OF BUSINESS, PART [I-X]). Short paragraphs whose normalized text matches this regex are retained even without anchor signals.

**Fix C** (`src/extraction_v2/stages/section_classification.py`):
- Add a `SECTION_PATTERNS[SectionType.MDA]` entry for company-prefixed headings: `^[A-Z][A-Z\s&\.,]+'?S?\s*MANAGEMENT.{0,10}S?\s*DISCUSSION`.
- Relax `_is_section_heading()` to also return True when `_detect_section_type(segment.text) != SectionType.UNKNOWN` for short segments — so mixed-case headings whose text matches a section pattern are admitted regardless of capitalization.

All three are additive: long canonical headings (covered by current rules) and the gh-574 Datadog short-anchor case both continue to work. Regression guards in `test_ingestion.py` enforce this.

### Verification (2026-05-14)

Re-ran the V2 pipeline against all 6 affected filings post-fix:

| Filing | Pre-fix sections | Post-fix sections |
|---|---|---|
| 209382 (AgileThought) | `{COVER: 0}` | `{COVER: 0, RISK_FACTORS: 1, MDA: 2, NOTES: 17}` |
| 215071 (Waldencast) | `{COVER: 0, FINANCIALS: 1}` | `{COVER: 0, RISK_FACTORS: 2, MDA: 3, FINANCIALS: 1, NOTES: 4}` |
| 833 (Concrete Pumping) | (zero whitelisted) | `{COVER: 0, RISK_FACTORS: 2, MDA: 3, FINANCIALS: 1, NOTES: 12}` |
| 10273 (Bazaarvoice) | (zero whitelisted) | `{COVER: 0, MDA: 1, FINANCIALS: 1}` |
| 192171 (Diamond Eagle / DraftKings) | (zero whitelisted) | `{COVER: 0, RISK_FACTORS: 2, MDA: 2, BUSINESS: 1, FINANCIALS: 10, NOTES: 79}` |
| 207445 (Ouster) | (zero whitelisted) | `{COVER: 0, RISK_FACTORS: 8, BUSINESS: 9, MDA: 3, FINANCIALS: 8, NOTES: 22, SIGNATURES: 1}` |

All 6 now detect at least MDA (most also detect RISK_FACTORS and BUSINESS). Tier-1 zero-tolerance gate green pre- and post-fix.

### Follow-up

The operator diagnostic (warn if ingestion produced ≥1000 segments AND section_classification detected zero whitelisted sections) is deferred until after the Phase-2 gate v2 PR lands, to avoid a merge conflict on `scripts/run_phase2_quantitative_eval.py` which is being substantially rewritten there.
