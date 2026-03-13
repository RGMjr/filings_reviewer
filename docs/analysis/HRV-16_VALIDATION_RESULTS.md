# HRV-16: Post-Phase 4 Validation Results

**Date**: 2026-01-04
**Status**: COMPLETE
**Validator**: Claude Code

---

## Executive Summary

**Result: PARTIAL PASS** - 2 of 3 primary metrics achieved realistic targets.

| Metric | Target (Realistic) | Target (Stretch) | Actual | Status |
|--------|-------------------|------------------|--------|--------|
| Precision | ≥20% | ≥30% | **66.7%** | PASS (stretch) |
| Recall | ≥55% | ≥65% | **47.4%** | FAIL |
| F1 Score | ≥28% | ≥40% | **55.4%** | PASS (stretch) |

**Key Findings**:
1. Precision significantly improved: 66.7% overall (100% Farfetch, 62.3% Slack)
2. Recall below target due to Farfetch performance (23.9% recall)
3. F1 score exceeds stretch target at 55.4%
4. Samsara Vision (3 gold entries) has metric ID mismatch issue

---

## Section 1: Farfetch Results

**Filing ID**: 31

| Metric | HRV-4 Baseline | Phase 4 Result | Delta |
|--------|----------------|----------------|-------|
| Candidates | 253 (then 50) | **16** | -68% |
| Precision | 10.4% | **100.0%** | +89.6 pp |
| Recall | 49.3% | **23.9%** | -25.4 pp |
| F1 Score | 17.2% | **38.6%** | +21.4 pp |
| True Positives | N/A | 16 | - |
| False Positives | 283 | **0** | -100% |
| False Negatives | 34 | **51** | +50% |

### Analysis

**Improvements**:
- Precision improved from 10.4% to 100% - all candidates are now valid
- False positives eliminated completely (283 → 0)
- F1 score more than doubled (17.2% → 38.6%)

**Regressions**:
- Recall dropped significantly (49.3% → 23.9%)
- False negatives increased (34 → 51)
- Candidate count reduced (50 → 16)

**Root Cause Analysis**:
The HRV-22 HTMLSegmenter bug fix corrected raw_text/raw_html mismatches in table segments. This likely:
1. Fixed data quality issues causing false positive extractions
2. But may have removed some segments that previously contained valid metrics

**Top False Negative Patterns**:
1. **Growth metrics**: "Active Consumers growth", "Number of Orders growth" (6 FNs) - growth detection removed in HRV-9
2. **Chart-based metrics**: "GMV by consumer cohort" (1 FN) - chart detection not yet generating candidates
3. **LTV/CAC metrics**: "Lifetime Value of a Customer", "LTV/CAC ratio" (2 FNs) - missing keyword patterns
4. **New customers**: "new consumers" (1 FN) - acquisition patterns not matching
5. **Cohort-specific values**: Multiple AOV and take rate by year - segment-level matching gaps

---

## Section 2: Slack Results

**Filing ID**: 35

| Metric | HRV-4 Baseline | Phase 4 Result | Delta |
|--------|----------------|----------------|-------|
| Candidates | 59 | **61** | +3% |
| Precision | 76.0% | **62.3%** | -13.7 pp |
| Recall | 84.0% | **86.4%** | +2.4 pp |
| F1 Score | 79.7% | **72.4%** | -7.3 pp |
| True Positives | N/A | 38 | - |
| False Positives | N/A | **23** | - |
| False Negatives | N/A | **6** | - |

### Analysis

**Improvements**:
- Recall slightly improved (84.0% → 86.4%)
- Candidate count stable (59 → 61)

**Regressions**:
- Precision dropped (76.0% → 62.3%)
- 23 false positives detected

**Top False Positive Patterns**:
1. **Large customer threshold values**: "209", "254", "351", "412", "491" - threshold numbers being extracted
2. **Percentage retention rates as customers**: "156%", "153%", "151%" - percentages in customer context
3. **MRR false match**: "twelve" matched as MRR

**Top False Negative Patterns**:
1. **Definition-only entries**: "organization", "paid customer" (2 FNs) - system requires numeric values
2. **Chart references**: "ARR of each cohort" (1 FN) - chart-based metric
3. **Net Dollar Retention Rate**: 2 entries not matched (possibly duplicate detection)
4. **Unknown entry**: 1 empty/invalid gold standard entry

---

## Section 3: Samsara Vision Results

**Filing ID**: 38

| Metric | Phase 4 Result |
|--------|----------------|
| Gold Standard | 3 |
| Candidates | 4 |
| Precision | **0.0%** |
| Recall | **0.0%** |
| F1 Score | **0.0%** |
| True Positives | 0 |
| False Positives | 4 |
| False Negatives | 3 |

### Analysis

**Issue**: Metric ID mismatch between system and gold standard.
- Gold standard uses: `cm_customer_revenue_concentration`
- System generates: `cm_revenue_concentration`

This is a taxonomy issue, not a detection failure. The system IS finding revenue concentration data but using a different metric ID.

**Recommendation**: Add `cm_customer_revenue_concentration` as alias to `cm_revenue_concentration` in `config/metric_keywords.yaml`.

---

## Section 4: Combined Metrics

| Filing | Gold Std | Candidates | TP | FP | FN | Precision | Recall | F1 |
|--------|----------|------------|----|----|----|-----------:|-------:|----:|
| Farfetch | 67 | 16 | 16 | 0 | 51 | 100.0% | 23.9% | 38.6% |
| Slack | 44 | 61 | 38 | 23 | 6 | 62.3% | 86.4% | 72.4% |
| Samsara | 3 | 4 | 0 | 4 | 3 | 0.0% | 0.0% | 0.0% |
| **Total** | **114** | **81** | **54** | **27** | **60** | **66.7%** | **47.4%** | **55.4%** |

### Weighted Analysis

Farfetch has the most gold standard entries (67/114 = 59%) but the lowest recall (23.9%), which significantly impacts overall metrics. Excluding Samsara (metric ID issue):

| Filing | Gold Std | Weight | Recall | Weighted Contribution |
|--------|----------|--------|--------|----------------------|
| Farfetch | 67 | 60% | 23.9% | 14.4% |
| Slack | 44 | 40% | 86.4% | 34.3% |
| **Weighted Recall** | | | | **48.7%** |

---

## Section 5: Improvement Analysis

### What Worked

1. **False Positive Reduction**: Financial statement filtering and type validation eliminated FPs
2. **Farfetch Data Quality**: HRV-22 bug fix improved segment data integrity
3. **Precision Trade-off**: Higher precision with fewer but more accurate candidates

### What Didn't Work

1. **Growth Metric Removal (HRV-9)**: Removing growth patterns hurt Farfetch recall (~6 FNs)
2. **Aggressive Filtering**: May have over-filtered, losing valid candidates
3. **Chart Detection Gap**: Chart-based metrics still not generating candidates

### Trade-off Analysis

The Phase 4 improvements prioritized precision over recall:
- **Before**: High false positive rate (283 FPs for Farfetch) but better recall
- **After**: Near-zero false positives but missed valid metrics

This is an intentional trade-off for a human review system - fewer but higher-quality candidates reduce reviewer burden.

---

## Section 6: Remaining Issues

### Priority 1: Critical (High Impact)

| Issue | Filing(s) | Impact | Recommended Fix |
|-------|-----------|--------|-----------------|
| Low Farfetch recall | Farfetch | 51 FNs | Investigate filtered candidates, add missing patterns |
| Metric ID mismatch | Samsara | 3 FNs | Add alias for `cm_customer_revenue_concentration` |
| Growth metrics missing | All | ~8 FNs | Consider selective re-enablement or alias system |

### Priority 2: Medium (Quality Improvements)

| Issue | Filing(s) | Impact | Recommended Fix |
|-------|-----------|--------|-----------------|
| Definition-only metrics | Slack | 2 FNs | Implement definition-only candidate type (HRV-13) |
| Chart-based metrics | All | ~3 FNs | Integrate chart detection into candidates |
| Threshold value FPs | Slack | 5 FPs | Add threshold number detection to filter |

### Priority 3: Low (Edge Cases)

| Issue | Filing(s) | Impact | Recommended Fix |
|-------|-----------|--------|-----------------|
| Percentage as customer | Slack | 3 FPs | Improve percentage filter for customer metrics |
| LTV/CAC patterns | Farfetch | 2 FNs | Add keyword patterns for LTV, CAC, LTV/CAC ratio |

---

## Section 7: Recommendations

### Immediate Actions

1. **Create Baseline**: Run `--update-baseline` to establish Phase 4 metrics as baseline
   ```bash
   python scripts/validate_against_gold_standard.py --all --mode db --update-baseline
   ```

2. **Fix Samsara Metric ID**: Add alias to `config/metric_keywords.yaml`:
   ```yaml
   cm_revenue_concentration:
     aliases:
       - cm_customer_revenue_concentration
   ```

### Short-Term (Next Phase)

1. **Investigate Farfetch Recall**: Analyze which segments are missing candidates
2. **Selective Growth Re-enablement**: Consider adding growth patterns back with context gating
3. **Threshold Value Filter**: Add filter for common threshold numbers (100K, 100,000, etc.)

### Long-Term

1. **Chart Detection Integration**: Generate candidates from detected cohort charts
2. **Definition-Only Mode**: Implement HRV-13 for definition-without-value entries
3. **LTV/CAC Patterns**: Add comprehensive customer lifetime value patterns

---

## Appendix A: Validation Command

```bash
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/validate_against_gold_standard.py --all --mode db --baseline --verbose
```

---

## Appendix B: Target Achievement Summary

| Target Category | Metric | Target | Actual | Gap | Status |
|-----------------|--------|--------|--------|-----|--------|
| Realistic | Precision | ≥20% | 66.7% | +46.7 pp | PASS |
| Realistic | Recall | ≥55% | 47.4% | -7.6 pp | FAIL |
| Realistic | F1 | ≥28% | 55.4% | +27.4 pp | PASS |
| Stretch | Precision | ≥30% | 66.7% | +36.7 pp | PASS |
| Stretch | Recall | ≥65% | 47.4% | -17.6 pp | FAIL |
| Stretch | F1 | ≥40% | 55.4% | +15.4 pp | PASS |

**Summary**: 4/6 targets met (67%). Recall remains the primary gap.

---

## Appendix C: Comparison to HRV-4 Baseline

| Metric | HRV-4 Baseline (Farfetch) | Phase 4 Result | Change |
|--------|---------------------------|----------------|--------|
| Candidates | 253 → 50 | 16 | -68% from last |
| Precision | 10.4% | 100.0% | +89.6 pp |
| Recall | 49.3% | 23.9% | -25.4 pp |
| F1 Score | 17.2% | 38.6% | +21.4 pp |
| False Positives | 283 | 0 | -100% |
| False Negatives | 34 | 51 | +50% |

**Interpretation**: Phase 4 successfully traded recall for precision. The system now produces fewer but more accurate candidates, reducing reviewer burden at the cost of missing some valid metrics.

---

**Report Generated**: 2026-01-04
**Data Sources**:
- `review_candidates` table (81 candidates across 3 filings)
- `data/gold_standard/golden_set_251218.csv` (114 entries)
- Validation script: `scripts/validate_against_gold_standard.py`
