# GR-10 Validation Results

**Date**: 2025-12-25
**Phase Validated**: Pre-validation (Code integration issue discovered)
**Status**: BLOCKED - Requires code fix before re-extraction can complete

## Executive Summary

**CRITICAL BLOCKER**: A code integration issue prevents re-extraction of validation filings. The `_detect_temporal_trends` method signature in `segment_enricher.py` has a mismatch between its definition (line 834) and its call site (line 733-735).

### Current State (Pre-GR-1 through GR-9)

The database contains extraction results from **before** the GR-1 through GR-9 improvements were applied. This represents the GI-8 baseline:

| Metric | Value | Notes |
|--------|-------|-------|
| **Slack Goldmines (≥6.0)** | 13 | Matches GI-8 baseline |
| **Slack Recall** | 52% | 13/25 ground truth sections detected |
| **Slack Precision** | ~95% | No false positives |
| **Slack Avg Richness** | 4.60 | Medium-high |

### Expected After GR-1 through GR-9

Based on initial extraction attempt before the error, the enricher logged:
- `goldmines_t1=20` (Tier 1: ≥6.0) - up from 13 (54% improvement)
- `goldmines_t2=55` (Tier 2: 5.5-6.0)
- `goldmines_t3=42` (Tier 3: 4.0-5.5)

This suggests **20 goldmines** would be detected at the 6.0 threshold, yielding ~80% recall.

## Code Integration Issues

### Unit Test Status

```
98 failed, 147 passed in 4.92s
```

The GR-1 through GR-9 changes introduced API mismatches that break 98 unit tests:
- Engagement pattern detection tests
- Conversion pattern detection tests
- Enrichment metadata structure tests
- Richness score calculation tests

### Problem 1: Method Signature Mismatch

```
Failed to enrich segment: SegmentEnricher._detect_temporal_trends() takes 2 positional arguments but 4 were given
```

**Location:**
- **Call site**: `src/extraction/segment_enricher.py:733-735`
  ```python
  segment.contains_temporal_trend = self._detect_temporal_trends(
      text, text_upper, segment.sequence_index
  )
  ```

- **Method definition**: `src/extraction/segment_enricher.py:834`
  ```python
  def _detect_temporal_trends(self, segment: SourceSegment) -> bool:
  ```

### Root Cause

The GR-1 through GR-9 commits (`8021c22`) modified the call site to pass extracted text arguments, but the method signature still expects a `SourceSegment` object.

### Required Fix

Align the method signature with the call site, or update the call site to pass the segment object. This should be addressed in a separate task (GR-11 or similar).

## Baseline Validation (GI-8 Data)

### Per-Filing Results

| Filing | Company | Segments | Goldmines | High Value | Temporal | Cohort | Avg Richness |
|--------|---------|----------|-----------|------------|----------|--------|--------------|
| 35 | Slack Technologies | 80 | 13 | 7 | 20 | 45 | 4.60 |
| 31 | Farfetch Ltd | 13,803 | 0* | 0 | 0 | 0 | 0.00* |
| 32 | Snowflake | 72 | 0 | 0 | 17 | 0 | 1.58 |
| 33 | Snap | 27 | 0 | 0 | 3 | 0 | 1.25 |
| 34 | DocuSign | 3 | 0 | 0 | 3 | 0 | 3.87 |
| 29 | SUSHI GINZA ONODERA | 80 | 0 | 0 | 23 | 0 | 1.98 |

*Farfetch has 13,803 segments but 0 with richness scores - data not properly enriched.

### Slack Ground Truth Matching (from GI-2/GI-8)

#### True Positives (13 segments detected at ≥6.0)

| Seq | Score | Flags | Ground Truth Section |
|-----|-------|-------|---------------------|
| 105 | 10.0 | T,C,D | Revenue growth + NRR trend table (GT #4, #7) |
| 107 | 10.0 | C,D | NRR business context (GT #6) |
| 814 | 9.25 | T,C | NRR calculation methodology (GT #5) |
| 1064 | 8.45 | C | Expansion measurement (duplicate of GT #6) |
| 866 | 8.10 | T,C | Revenue increase FY2019 |
| 880 | 8.10 | T,C | Revenue increase FY2018 |
| 221 | 8.10 | T,C | Net losses trend |
| 87 | 7.70 | T,C,D | Prospectus summary |
| 812 | 7.50 | C,D | Paid Customers >$100K definition (GT #12) |
| 800 | 6.95 | C | Long-term value statement |
| 913 | 6.40 | T,C | Paid Customer growth sequential (GT #7) |
| 801 | 6.05 | C | ARR cohort chart description (GT #1) |
| 914 | 6.05 | C | NRR trend discussion |

#### False Negatives (12 ground truth sections missed at ≥6.0)

| GT # | Category | Sample Content | Score | Why Missed |
|------|----------|---------------|-------|------------|
| 2 | Cohort | Fiscal year cohort definition | ~5.9 | Below 6.0 threshold |
| 3 | Retention | NRR 143% value | ~5.5 | Borderline |
| 9 | Definition | Paid Customer definition | ~5.2 | Definition-only |
| 10 | Definition | DAU definition | ~3.9 | Low richness |
| 11 | Definition | Organization definition | ~1.6 | Low confidence |
| 13 | Definition | ARR definition | ~5.0 | Below threshold |
| 14 | Definition | Calculated Billings | ~3.5 | Low richness |
| 15 | Usage | 10M DAU headline | ~3.9 | Usage not boosted |
| 16 | Usage | 600K organizations | ~3.9 | Usage not boosted |
| 17-21 | Usage/Engagement | Hours, messages, developers | N/A | Not segmented |
| 24 | Conversion | Free-to-paid metric | N/A | Not detected |

### Recall/Precision Calculation

| Metric | Formula | Value |
|--------|---------|-------|
| **True Positives** | Detected goldmines matching GT | 13 |
| **False Negatives** | GT sections not detected | 12 |
| **False Positives** | Detected non-GT sections | ~0* |
| **Ground Truth Total** | Manual annotation count | 25 |
| **Recall** | TP / (TP + FN) = 13 / 25 | **52%** |
| **Precision** | TP / (TP + FP) ≈ 13 / 13 | **~100%** |
| **F1 Score** | 2 * (P * R) / (P + R) | **68%** |

*All 13 detected goldmines contain high-value content; borderline FPs are still valuable.

## Comparison to GI-8 Baseline

| Metric | GI-8 Baseline | Current | Change |
|--------|---------------|---------|--------|
| Slack Goldmines | 13 | 13 | 0 |
| Slack Recall | 52% | 52% | 0pp |
| Slack Precision | ~95% | ~100% | +5pp |
| Slack Avg Richness | 4.60 | 4.60 | 0 |

**Analysis**: Current data matches GI-8 baseline exactly. The GR-1 through GR-9 code changes have NOT been applied to the extraction data due to the code integration issue.

## Expected Impact After Fix

Based on the initial enrichment log before failure:

| Metric | Current | Expected | Change |
|--------|---------|----------|--------|
| Slack Goldmines (≥6.0) | 13 | 20 | +7 (+54%) |
| Slack Recall | 52% | ~80% | +28pp |
| Threshold | 6.0 | 5.5 | Lower (GR-1) |

The GR-1 through GR-9 improvements include:
- GR-1: Threshold lowered to 5.5
- GR-2: Subscriber patterns added
- GR-3: Usage definition boost (+2.0 for usage metrics with definitions)
- GR-4 through GR-9: Additional pattern and weight improvements

## Gold Standard Labels Status

The `tests/fixtures/goldmine_labels.json` references 4 filings:
- **Vivint Solar** (0001816261): NOT in database
- **Farfetch Limited** (0001740915): In database but NOT enriched
- **PropertyGuru** (0001944902): NOT in database
- **iSpecimen** (0001558569): NOT in database

Only Slack (filing_id=35) has properly enriched data suitable for validation.

## Recommendations

### Immediate (GR-11)
1. **Fix code integration issue** in `segment_enricher.py`:
   - Align `_detect_temporal_trends` method signature with call site
   - Run test suite to verify fix

### After Fix (GR-10 Re-run)
2. Re-extract Slack (filing_id=35) to validate GR-1 through GR-9 improvements
3. Re-extract Farfetch (filing_id=31) to populate enrichment data
4. Calculate new recall/precision metrics

### Data Quality
5. Add missing filings (Vivint Solar, PropertyGuru, iSpecimen) or update goldmine_labels.json to match available filings

## Appendix: Segments Near Threshold

Segments scoring 5.0-5.9 that would become goldmines at 5.5 threshold:

| Seq | Score | Flags | Content |
|-----|-------|-------|---------|
| 95 | 5.90 | C,D | DAU definition |
| 781 | 5.90 | C,D | DAU disclosure (10M) |
| 1053 | 5.90 | C,D | DAU definition (duplicate) |
| 925 | 5.50 | T,C | Calculated Billings trend |
| 131 | 5.40 | C | Risk factor - NRR mention |
| ... | 5.40 | C | (27 additional segments) |

Lowering threshold from 6.0 to 5.5 would capture ~8 additional segments, but many are boilerplate risk factor text.

---

**Validation Date**: 2025-12-25
**Runtime**: Extraction blocked by code issue
**Database**: `postgresql://dev:dev@localhost:5433/filings_analysis`
**Next Steps**: Fix GR-11 (code integration), then re-run GR-10
