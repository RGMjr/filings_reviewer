# WORKER PROMPT: Task GR-1 - Lower Goldmine Threshold to 5.5

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-1
TASK NAME:     Lower goldmine detection threshold from 6.0 to 5.5
WORKSTREAM:    Accuracy Improvement
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 0 Quick Wins
STATUS:        🟡 PENDING
TIME ESTIMATE: 1 hour (investigation 20 min, implementation 5 min, testing 35 min)
RISK LEVEL:    LOW (config constant change, easily reversible)
TASK SIZE:     S (30 min - 2 hours)
DEPENDS ON:    None
UNLOCKS:       GR-10 (validation)
BLOCKS:        None
PARALLEL WITH: GR-2, GR-4, GR-6, GR-7, GR-8, GR-9
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Lower the `GOLDMINE_THRESHOLD` constant from 6.0 to 5.5 to improve recall of goldmine segment detection.

**Business Rationale**: Currently missing 48% of true goldmines due to overly strict threshold. Vivint Solar's highest-scoring segment (5.50) is being excluded despite containing valuable customer metrics. Lowering by 0.5 points captures these near-miss segments.

**Current Behavior**: Segments with richness_score 5.5-5.99 are excluded from goldmine classification, missing valuable metric disclosures.

**Desired Behavior**: Segments scoring ≥5.5 are classified as goldmines, improving recall by 6-10 percentage points.

## Prerequisites

- None (standalone task)

## Files to Modify

1. **`src/extraction/segment_enricher.py`** - Change `GOLDMINE_THRESHOLD` constant from 6.0 to 5.5 (line ~54)
2. **`tests/integration/test_goldmine_detection.py`** - Update any threshold-specific assertions
3. **`tests/unit/extraction/test_segment_enricher.py`** - Update boundary tests for new threshold

## Files to Read (Context Only)

- `docs/GOLDMINE_REMEDIATION_PLAN.md` - Full context on why this change is needed
- `docs/archive/2025-12-goldmine-analysis/GI-8_validation_results.md` - Current validation baseline

## Implementation Requirements

### Core Functionality

1. **Threshold Constant Change**
   - Locate `GOLDMINE_THRESHOLD: float = 6.0` in segment_enricher.py
   - Change value to `5.5`
   - Ensure no other hardcoded 6.0 thresholds exist in the file

2. **Boundary Behavior**
   - Score of exactly 5.5 → is_goldmine = True
   - Score of 5.49 → is_goldmine = False
   - Existing goldmines (≥6.0) remain goldmines

### Error Handling

- No error handling changes needed (threshold comparison is simple)

### Backward Compatibility

- **No breaking changes**: This is a configuration value change
- **Rollback**: Simply change value back to 6.0 if precision drops unacceptably

## Test Requirements

### Coverage Target: Maintain existing coverage for `segment_enricher.py`

### Test Categories (5+ tests)

1. **Threshold Boundary Tests** (3 tests)
   - Score 5.49 → not goldmine
   - Score 5.50 → is goldmine
   - Score 5.51 → is goldmine

2. **Existing Behavior Preservation** (2+ tests)
   - Score 6.0+ → still goldmine
   - Score 0.0 → not goldmine
   - Score 10.0 → is goldmine

### Known Edge Cases to Test

- Exact boundary value (5.5)
- Floating point precision (5.4999999 vs 5.5)

## Acceptance Criteria

- [ ] `GOLDMINE_THRESHOLD` changed to 5.5 in `segment_enricher.py`
- [ ] No other hardcoded 6.0 values remain for threshold comparisons
- [ ] Boundary tests updated to reflect new threshold
- [ ] All existing tests pass
- [ ] `pytest tests/unit/extraction/test_segment_enricher.py -v` passes

## Do NOT

- Modify any other threshold values (MEDIUM_THRESHOLD, DIRECT_HIT_THRESHOLD in extraction_pipeline.py)
- Change the tiered selection logic (that's in GR-5, already complete)
- Add new patterns or scoring bonuses (other tasks handle that)
- Modify extraction_pipeline.py (no changes needed there)

## Verification Commands

```bash
# Run unit tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v --tb=short

# Run integration tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/integration/test_goldmine_detection.py -v --tb=short

# Verify constant change
grep -n "GOLDMINE_THRESHOLD" src/extraction/segment_enricher.py
```

## Expected Impact

**Before GR-1**:
- Goldmine threshold: 6.0
- Recall: ~52% (missing near-threshold segments)
- Vivint Solar: 0 goldmines (max score 5.50)

**After GR-1**:
- Goldmine threshold: 5.5
- Recall: ~58-62% (+6-10pp)
- Vivint Solar: Likely 1+ goldmines detected
- Expected FP rate increase: 5% → ~10% (acceptable)

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4
