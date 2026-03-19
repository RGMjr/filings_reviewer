# Known Issues and Future Improvements

This document tracks known issues, limitations, and planned improvements identified during extraction system development.

**Last Updated**: 2026-01-01

---

## 1. Metric ID Mismatch Between Gold Standard and System

**Status**: Needs Investigation
**Severity**: High (affects recall measurements)
**Discovered**: 2026-01-01 during VAL-1 validation

### Problem

The gold standard CSV uses different metric IDs than the extraction system generates:

| Gold Standard ID | System-Generated ID | Example Values |
|------------------|--------------------|--------------------|
| `cm_active_customers_total` | `cm_customers_period_end` | Slack paid customers |
| `cm_active_customers_total` | `cm_active_customers_total` | Farfetch active consumers |

This causes apparent "false negatives" in recall calculation when the system correctly extracts values but assigns them different metric IDs.

### Impact

- **Slack recall**: Likely understated due to ID mismatch
- **Farfetch recall**: 12.5% (1/8) - lower than expected
- **Comparison script**: Cannot match candidates to gold values

### Root Cause

The gold standard was created using different metric taxonomy than the extraction system's `config/metric_keywords.yaml` definitions.

### Recommended Fix

1. Audit gold standard metric IDs against `config/metric_keywords.yaml`
2. Either:
   - Update gold standard IDs to match system taxonomy, OR
   - Add metric ID aliases to comparison script
3. Re-run validation after alignment

---

## 2. Low Farfetch Recall (12.5%)

**Status**: Partially Diagnosed
**Severity**: Medium
**Discovered**: 2026-01-01

### Problem

Only 1 of 8 non-chart Farfetch gold standard values matched during validation.

### Contributing Factors

1. **Metric ID mismatch** (see Issue #1)
2. **Value normalization differences**: Gold uses exact values, system may normalize differently
3. **Missing patterns**: Some keywords may not trigger candidate generation

### CAC Payback Period (FIXED)

The CAC payback period value "six" (months) was not being extracted:
- Pattern `\bpayback\s+period\s+(?:on|for)\s+cac\b` added to catch this variant
- Spelled-out number support added to handle "six"
- Now correctly generates candidate for `cm_cac_payback_period: six`

### Remaining Gaps

- Investigate which values remain unmatched after fixing metric ID mismatch
- Review Active Consumers, Number of Orders, Take Rate patterns

---

## 3. Gold Standard Methodology Questions

**Status**: Needs Discussion
**Severity**: Low (process improvement)

### Questions Raised

1. **Metric taxonomy alignment**: Should gold standard use same IDs as extraction system?
2. **Chart value handling**: Current approach marks chart values as "chart" - should they be in separate file?
3. **Value normalization**: Gold uses various formats (800,500 vs 800500) - should normalize?
4. **Metric scope**: What exactly counts as "Active Customers" vs "Paid Customers"?

### Recommendation

Create a gold standard specification document that defines:
- Approved metric IDs (aligned with `config/metric_keywords.yaml`)
- Value normalization rules
- Chart vs text-extractable classification criteria

---

## 4. Spelled-Out Number Parsing Limitations

**Status**: Known Limitation
**Severity**: Low (edge case)

### Current Support

The system correctly parses:
- Simple numbers: "six", "twenty", "ninety"
- Teen numbers: "eleven", "fifteen", "nineteen"
- Compound numbers: "twenty-one", "forty-five"
- Magnitude words: "five million", "two billion"
- Hundreds: "hundred", "one hundred", "two hundred"

### Not Supported

Complex numbers like:
- "one hundred twenty-three" (compound hundreds)
- "two thousand five hundred" (multi-magnitude)
- "four hundred and fifty" (with "and")

### Rationale

These complex spelled-out numbers are rare in SEC filings - companies typically use numeric format for precision. The current implementation handles the common cases (e.g., "six months" for CAC payback period).

---

## 5. Revenue Synonym Context Gating

**Status**: Working as Designed
**Severity**: N/A (architectural decision)

### Background

Revenue-related metrics (GMV, TCV, ACV, Bookings, Billings) only generate review candidates when cohort/per-customer context is present. This is intentional to reduce false positives.

### Current Behavior

- ARR/MRR: Always generate candidates (inherently customer-related)
- GMV/TCV/ACV/Bookings/Billings: Require context keywords within 1500 chars
- Context keywords: cohort, vintage, per customer, per user, by account, etc.

### Potential Issue

Some valid per-customer GMV values may not have context keywords nearby, causing them to be missed.

### Monitoring

Review rejection rates for revenue synonyms to determine if context gating is too strict.

---

## Summary

| Issue | Priority | Effort | Impact |
|-------|----------|--------|--------|
| Metric ID Mismatch | High | Medium | Fixes recall measurements |
| Low Farfetch Recall | Medium | Medium | Improves coverage |
| Gold Standard Methodology | Low | Low | Process improvement |
| Spelled-Out Number Limits | Low | High | Edge case coverage |
| Revenue Synonym Gating | Monitor | N/A | Working as designed |

---

---

## 6. FilingFetcher Downloads Directory Index Instead of Primary Document

**Status**: Open
**Severity**: Medium — blocks candidate generation for newly fetched filings
**Discovered**: 2026-03-16 during cloud deployment pilot

### Symptom

`fetch_curated_sample.py` reports success and marks filings as `html_fetched_at` in the DB, but the saved `primary.htm` is the SEC EDGAR directory listing page (~16KB) rather than the actual S-1/F-1 document (typically 500KB–5MB).

Downstream effect: `run_extraction_pipeline.py` extracts 0 metrics. `generate_review_candidates.py` finds no filings to process because `source_segments` is never populated.

### Root Cause

The `sec_html_url` stored in the `filings` table is a directory URL ending in `/`:
```
https://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/
```
`FilingFetcher` fetches this URL directly and saves the response as `primary.htm` without resolving the actual primary document from the index.

### Fix

`FilingFetcher` should detect when `sec_html_url` ends with `/`, fetch the index, parse the document table to find the primary `.htm` file, and download that instead. The SEC EDGAR index lists each document with its type — the primary filing document is the one typed `S-1`, `S-1/A`, `F-1`, etc.

---

## Change Log

- **2026-01-01**: Initial document created after VAL-1 validation
- **2026-01-01**: CAC payback period issue resolved (moved to "FIXED" section)
- **2026-03-16**: Added Issue #6 — FilingFetcher directory index bug
