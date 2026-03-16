# Known Issues and Future Improvements

This document tracks known issues, limitations, and planned improvements identified during extraction system development.

**Last Updated**: 2026-03-16

---

## 1. Metric ID Mismatch Between Gold Standard and System

**Status**: Resolved
**Severity**: High (affects recall measurements)
**Discovered**: 2026-01-01 during VAL-1 validation
**Resolved**: 2026-03-16

### Problem

The gold standard CSV uses different metric IDs than the extraction system generates:

| Gold Standard ID | System-Generated ID | Example Values |
|------------------|--------------------|--------------------|
| `cm_active_customers_total` | `cm_customers_period_end` | Slack paid customers |
| `cm_active_customers_total` | `cm_active_customers_total` | Farfetch active consumers |

This caused apparent "false negatives" in recall calculation when the system correctly extracts values but assigns them different metric IDs.

### Resolution

The gold standard CSV (`data/gold_standard/golden_set_251218.csv`) was updated to align all metric IDs with the system taxonomy in `config/metric_keywords.yaml`. Fresh validation confirms no remaining ID mismatches:

- **Slack**: 97.9% recall (1 FN — extraction gap, not ID mismatch)
- **Samsara**: 100% recall
- **Farfetch**: 0% recall (URL issue — see Issue #6; not ID mismatch)
- **Snowflake**: 31% recall (extraction coverage gap, not ID mismatch)

The alias infrastructure in `src/extraction/keyword_config.py` remains in place but is correctly unused — no aliases are needed since the gold standard now uses canonical IDs.

---

## 2. Low Farfetch Recall (12.5%)

**Status**: Partially Diagnosed
**Severity**: Medium
**Discovered**: 2026-01-01

### Problem

Only 1 of 8 non-chart Farfetch gold standard values matched during validation.

### Contributing Factors

1. ~~**Metric ID mismatch** (see Issue #1)~~ — resolved; gold standard IDs now aligned
2. **URL issue**: `sec_html_url` for Farfetch resolves to a directory index (see Issue #6), so no segments are extracted
3. **Value normalization differences**: Gold uses exact values, system may normalize differently
4. **Missing patterns**: Some keywords may not trigger candidate generation

### CAC Payback Period (FIXED)

The CAC payback period value "six" (months) was not being extracted:
- Pattern `\bpayback\s+period\s+(?:on|for)\s+cac\b` added to catch this variant
- Spelled-out number support added to handle "six"
- Now correctly generates candidate for `cm_cac_payback_period: six`

### Remaining Gaps

- Farfetch recall is blocked by the directory index bug (Issue #6); re-evaluate after that is fixed
- Review Active Consumers, Number of Orders, Take Rate patterns once document fetch is working

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

| Issue | Status | Priority | Effort | Impact |
|-------|--------|----------|--------|--------|
| Metric ID Mismatch | **Resolved** | — | — | Recall measurements now accurate |
| Low Farfetch Recall | Open | Medium | Medium | Blocked by Issue #6 |
| Gold Standard Methodology | Open | Low | Low | Process improvement |
| Spelled-Out Number Limits | Open | Low | High | Edge case coverage |
| Revenue Synonym Gating | Monitor | N/A | N/A | Working as designed |
| FilingFetcher Directory Index | **Resolved** | — | — | Re-fetch cloud filings to get actual documents |

---

---

## 6. FilingFetcher Downloads Directory Index Instead of Primary Document

**Status**: Resolved
**Severity**: Medium — blocked candidate generation for newly fetched filings
**Discovered**: 2026-03-16 during cloud deployment pilot
**Resolved**: 2026-03-16

### Symptom

`fetch_curated_sample.py` reported success and marked filings as `html_fetched_at` in the DB, but the saved `primary.htm` was the SEC EDGAR directory listing page (~16KB) rather than the actual S-1/F-1 document (typically 500KB–5MB).

Downstream effect: `run_extraction_pipeline.py` extracted 0 metrics. `generate_review_candidates.py` found no filings to process because `source_segments` was never populated.

### Root Cause

The `sec_html_url` stored in the `filings` table is a directory URL ending in `/`:
```
https://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/
```
`FilingFetcher` had two bugs: (1) `sec_client` defaulted to `None`, and (2) the URL resolution block was guarded by `if self.sec_client:`, so it was silently skipped when no client was provided. The fetcher downloaded the directory listing directly.

### Fix

Two changes in `src/filing_fetcher/filing_fetcher.py`:
1. Line 81: `sec_client` parameter now defaults to a new `SECClient(user_agent=user_agent)` instead of `None`
2. Line 295: Removed the `if self.sec_client:` guard — resolution runs unconditionally when URL ends with `/`

### Cached File Audit

`scripts/audit_fetched_filings.py` found 78 filings recorded as fetched in the DB but no files present on local disk. These were fetched on the cloud deployment (Render). No locally cached directory-listing files were found, so no cleanup is needed locally. **Re-fetch all 78 filings** on the cloud environment to get actual filing documents instead of directory pages.

---

## Change Log

- **2026-01-01**: Initial document created after VAL-1 validation
- **2026-01-01**: CAC payback period issue resolved (moved to "FIXED" section)
- **2026-03-16**: Added Issue #6 — FilingFetcher directory index bug
- **2026-03-16**: Issue #6 resolved — default SECClient creation + removed null guard; 78 cloud-fetched files need re-fetch
- **2026-03-16**: Issue #1 resolved — gold standard CSV updated to align with system taxonomy; no metric ID mismatches remain
