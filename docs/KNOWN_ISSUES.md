# Known Issues and Future Improvements

This document tracks known issues, limitations, and planned improvements identified during extraction system development.

**Last Updated**: 2026-03-17

---

## 2. Low Farfetch Recall (12.5%)

**Status**: Partially Diagnosed
**Severity**: Medium
**Discovered**: 2026-01-01

### Problem

Only 1 of 8 non-chart Farfetch gold standard values matched during validation.

### Contributing Factors

1. ~~**Metric ID mismatch** (see Issue #1)~~ — resolved; gold standard IDs now aligned
2. ~~**URL issue**: `sec_html_url` for Farfetch resolves to a directory index (see Issue #6)~~ — resolved; re-fetch 78 cloud-stored filings on Render
3. **Value normalization differences**: Gold uses exact values, system may normalize differently
4. **Missing patterns**: Some keywords may not trigger candidate generation

### CAC Payback Period (FIXED)

The CAC payback period value "six" (months) was not being extracted:
- Pattern `\bpayback\s+period\s+(?:on|for)\s+cac\b` added to catch this variant
- Spelled-out number support added to handle "six"
- Now correctly generates candidate for `cm_cac_payback_period: six`

### Remaining Gaps

- Re-evaluate Farfetch recall after cloud re-fetch of 78 filings is complete
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
| Low Farfetch Recall | Open | Medium | Medium | Blocked pending cloud re-fetch |
| Gold Standard Methodology | Open | Low | Low | Process improvement |
| Spelled-Out Number Limits | Open | Low | High | Edge case coverage |
| Revenue Synonym Gating | Monitor | N/A | N/A | Working as designed |

---

## Archive (Resolved Issues)

### Issue #1: Metric ID Mismatch Between Gold Standard and System

**Status**: ✅ Resolved (2026-03-16)

Gold standard CSV (`data/gold_standard/golden_set_251218.csv`) aligned to system taxonomy in `config/metric_keywords.yaml`. No remaining ID mismatches. See git log (2026-03-16) for full resolution details.

### Issue #6: FilingFetcher Downloads Directory Index Instead of Primary Document

**Status**: ✅ Resolved (2026-03-16)

`FilingFetcher` defaulted `sec_client` to `None` and guarded URL resolution behind `if self.sec_client:`, causing directory-index pages to be saved instead of actual filings. Fixed in `src/filing_fetcher/filing_fetcher.py` (lines 81, 295). 78 cloud-fetched filings need re-fetching on Render. See git log (2026-03-16) for full details.

---

## Change Log

- **2026-01-01**: Initial document created after VAL-1 validation
- **2026-01-01**: CAC payback period issue resolved (moved to "FIXED" section)
- **2026-03-16**: Added Issue #6 — FilingFetcher directory index bug
- **2026-03-16**: Issue #6 resolved — default SECClient creation + removed null guard; 78 cloud-fetched files need re-fetch
- **2026-03-16**: Issue #1 resolved — gold standard CSV updated to align with system taxonomy; no metric ID mismatches remain
- **2026-03-17**: Archived resolved Issues #1 and #6; updated Farfetch contributing factors to reflect resolutions
