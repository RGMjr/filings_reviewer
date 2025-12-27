# WORKER PROMPT: Task GR-10 - Re-run Validation After Phase 0/1

> **ARCHIVED**: 2025-12-25
> **STATUS**: 🔴 BLOCKED - Validation attempted but blocked by code integration issues
> **RESULTS**: See `docs/analysis/GR-10_VALIDATION_RESULTS.md`
> **BLOCKER**: GR-11 must fix API mismatches before re-extraction can complete
> **NEXT STEPS**: Complete GR-11, then re-run GR-10 validation

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-10
TASK NAME:     Validate goldmine improvements against ground truth
WORKSTREAM:    Validation
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 1 Critical Accuracy
STATUS:        🔴 BLOCKED (code integration issues discovered 2025-12-25)
TIME ESTIMATE: 1.5 hours (run script 30 min, analysis 45 min, documentation 15 min)
RISK LEVEL:    NONE (validation only, read-only operation)
TASK SIZE:     S (30 min - 2 hours)
DEPENDS ON:    GR-1, GR-2, GR-3 (minimum), GR-4 through GR-9 (for full validation)
UNLOCKS:       GR-18 (final validation)
BLOCKS:        None (but blocked BY GR-11)
PARALLEL WITH: GR-16, GR-17 (labeling tasks)
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Re-run goldmine validation against ground truth labels to quantify the improvement from Phase 0/1 tasks (threshold change, pattern additions, tiered selection).

**Business Rationale**: After implementing threshold changes, new patterns, and scoring improvements, we need to measure the actual recall/precision impact. This validates that our changes achieved the targeted 58-62% recall (Phase 0) or 70-75% recall (Phase 1 complete).

**Current Behavior**: Baseline validation shows 52% recall with 95% precision (documented in GI-8_validation_results.md).

**Desired Behavior**: Validation shows improved recall (target: 70-75%) with acceptable precision (≥85%).

## Prerequisites

- GR-1 complete (threshold lowered to 5.5)
- GR-2 complete (subscriber patterns added)
- GR-3 complete (usage definition boost)
- Preferably all Phase 1 tasks complete (GR-4 through GR-9) for comprehensive validation

## Files to Use

1. **`scripts/rerun_goldmine_validation.py`** - Validation script (may need creation if doesn't exist)
2. **`tests/fixtures/goldmine_labels.json`** - Ground truth labels for validation
3. **`docs/archive/2025-12-goldmine-analysis/GI-8_validation_results.md`** - Baseline to compare against

## Files to Create

1. **`docs/analysis/GR-10_VALIDATION_RESULTS.md`** - Results documentation

## Implementation Requirements

### Core Functionality

1. **Run Validation Script**
   - Execute validation against all labeled filings in goldmine_labels.json
   - Collect per-filing and aggregate metrics
   - Compare richness scores before/after improvements

2. **Metrics to Collect**
   - Recall: True positives / (True positives + False negatives)
   - Precision: True positives / (True positives + False positives)
   - F1 Score: 2 * (Precision * Recall) / (Precision + Recall)
   - Per-filing breakdown showing:
     - Expected goldmines (from labels)
     - Detected goldmines (from enricher)
     - True positives (correctly detected)
     - False negatives (missed)
     - False positives (incorrectly detected)

3. **Before/After Comparison**
   - Compare against GI-8 baseline (52% recall, 95% precision)
   - Calculate improvement in percentage points
   - Document segments that moved from FN to TP

4. **Example Segment Analysis**
   - Identify 3-5 specific segments that were previously missed (FN) and are now detected (TP)
   - Document why they're now detected (which pattern/threshold change helped)
   - Identify any new false positives introduced

### Error Handling

- If validation script doesn't exist, create minimal script to run validation
- If goldmine_labels.json is missing entries, document gaps
- Handle filings that may not be in database gracefully

## Test Requirements

### This is a validation task, not a code change task

- No new tests required
- Run existing test suite to ensure no regressions
- Document validation results in analysis file

## Acceptance Criteria

- [ ] Validation script runs successfully on all labeled filings
- [ ] Per-filing metrics collected and documented
- [ ] Aggregate recall/precision calculated
- [ ] Comparison to GI-8 baseline documented
- [ ] 3-5 example segments showing FN→TP transition analyzed
- [ ] Any new false positives identified and documented
- [ ] Results written to `docs/analysis/GR-10_VALIDATION_RESULTS.md`
- [ ] All existing tests still pass

## Do NOT

- Modify enricher code (this is validation only)
- Change goldmine_labels.json (that's GR-16/GR-17)
- Modify threshold or patterns (those tasks are complete)
- Skip documenting results even if they don't meet targets

## Verification Commands

```bash
# Run validation script
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python3 scripts/rerun_goldmine_validation.py

# If script doesn't exist, check for similar scripts
ls -la scripts/*goldmine* scripts/*validation*

# Verify labels file exists
cat tests/fixtures/goldmine_labels.json | python3 -m json.tool | head -50

# Ensure no regressions
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v --tb=short
```

## Expected Impact

**Before GR-10** (Baseline from GI-8):
- Recall: 52%
- Precision: 95%
- Vivint Solar: 0 goldmines detected

**After GR-10** (Expected targets):
- Recall: 58-62% (Phase 0 only) or 70-75% (Phase 0+1)
- Precision: ≥85% (acceptable tradeoff)
- Vivint Solar: 1+ goldmines detected
- Improvement: +6-23 percentage points recall

## Deliverables

Create `docs/analysis/GR-10_VALIDATION_RESULTS.md` with:

```markdown
# GR-10 Validation Results

**Date**: YYYY-MM-DD
**Phase Validated**: [Phase 0 only | Phase 0 + Phase 1]

## Summary

| Metric | Baseline (GI-8) | Current | Change |
|--------|-----------------|---------|--------|
| Recall | 52% | XX% | +XXpp |
| Precision | 95% | XX% | XXpp |
| F1 Score | XX% | XX% | +XXpp |

## Per-Filing Results

| Filing | Expected | Detected | TP | FN | FP | Recall |
|--------|----------|----------|----|----|----|----|
| Slack | X | X | X | X | X | XX% |
| ...    | | | | | | |

## Example Improvements

### Segment 1: [Filing Name]
- **Previously**: FN (not detected, score X.X)
- **Now**: TP (detected, score Y.Y)
- **Reason**: [which pattern/threshold helped]

## New False Positives (if any)

[Document any segments incorrectly detected]

## Recommendations

[Next steps based on results]
```

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4
