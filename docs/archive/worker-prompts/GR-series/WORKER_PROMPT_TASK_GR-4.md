# WORKER PROMPT: Task GR-4 - Formalize Tiered Threshold System

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-4
TASK NAME:     Formalize tiered threshold system with helper method
WORKSTREAM:    Architecture
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 1 Critical Accuracy
STATUS:        🟠 PARTIAL (thresholds exist in pipeline, need formalization)
TIME ESTIMATE: 2 hours (design 30 min, implementation 60 min, testing 30 min)
RISK LEVEL:    LOW (refactoring/formalization only, no behavior change)
TASK SIZE:     S (30 min - 2 hours)
DEPENDS ON:    None
UNLOCKS:       None (GR-5 already complete)
BLOCKS:        None
PARALLEL WITH: GR-1, GR-2, GR-6, GR-7, GR-8, GR-9
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Formalize the tiered threshold constants by moving them to segment_enricher.py and adding a helper method for tier classification.

**Business Rationale**: The tiered thresholds (6.0/4.0/3.0) currently exist in extraction_pipeline.py (lines 317-320). Moving them to segment_enricher.py creates better separation of concerns: the enricher owns scoring logic, the pipeline owns selection logic. This also enables easier testing and configuration.

**Current Behavior**: Threshold constants are defined in extraction_pipeline.py. Tier classification requires knowing these magic numbers.

**Desired Behavior**: Threshold constants are centralized in segment_enricher.py with a `classify_tier()` helper method that returns the tier (1, 2, 3, or None) for a given richness score.

## Prerequisites

- None (standalone refactoring task)
- Understanding that GR-5 (pipeline integration) is already complete - no pipeline changes needed

## Files to Modify

1. **`src/extraction/segment_enricher.py`** - Add TIER constants and `classify_tier()` helper method
2. **`tests/unit/extraction/test_segment_enricher.py`** - Add tier classification tests

## Files to Read (Context Only)

- `src/extraction/extraction_pipeline.py` lines 300-394 - See existing `_select_segments_tiered()` implementation
- `src/extraction/models.py` - Optional: see if goldmine_tier field would be useful (NOT required to add)

## Implementation Requirements

### Core Functionality

1. **Add Tier Threshold Constants**
   ```python
   # Add after GOLDMINE_THRESHOLD
   TIER1_THRESHOLD: float = 6.0   # High-value goldmines → LLM extraction
   TIER2_THRESHOLD: float = 4.0   # Medium-value → rule-based extraction
   TIER3_THRESHOLD: float = 3.0   # Low-value → manual review flagging
   ```

2. **Add Helper Method**
   ```python
   @staticmethod
   def classify_tier(richness_score: float) -> int | None:
       """
       Classify a richness score into a tier.

       Args:
           richness_score: The segment's richness score (0.0-10.0)

       Returns:
           1 for high-value (≥6.0), 2 for medium (≥4.0),
           3 for low (≥3.0), None for below threshold
       """
   ```

3. **Method Behavior**
   - Score ≥ 6.0 → return 1
   - Score ≥ 4.0 and < 6.0 → return 2
   - Score ≥ 3.0 and < 4.0 → return 3
   - Score < 3.0 → return None

### Error Handling

- Handle NaN/Inf inputs gracefully (return None)
- Handle negative scores (return None)

### Backward Compatibility

- **No changes to extraction_pipeline.py** - it can continue using its own constants
- **No changes to SourceSegment model** - goldmine_tier field is optional future work
- The helper method is purely additive

## Test Requirements

### Coverage Target: ≥ 90% for new classify_tier method

### Test Categories (8+ tests)

1. **Tier Classification** (4 tests)
   - Score 7.0 → tier 1
   - Score 5.0 → tier 2
   - Score 3.5 → tier 3
   - Score 2.0 → None

2. **Boundary Cases** (4 tests)
   - Score exactly 6.0 → tier 1
   - Score exactly 4.0 → tier 2
   - Score exactly 3.0 → tier 3
   - Score 2.999 → None

3. **Edge Cases** (2+ tests)
   - Score 0.0 → None
   - Score 10.0 → tier 1
   - Negative score → None
   - NaN → None (if implemented)

## Acceptance Criteria

- [ ] TIER1_THRESHOLD, TIER2_THRESHOLD, TIER3_THRESHOLD constants added to segment_enricher.py
- [ ] `classify_tier()` static method implemented
- [ ] Method returns correct tier for all score ranges
- [ ] 8+ unit tests covering tier classification
- [ ] All existing tests pass
- [ ] No changes to extraction_pipeline.py
- [ ] `pytest tests/unit/extraction/test_segment_enricher.py -v` passes

## Do NOT

- Modify `extraction_pipeline.py` (GR-5 is already complete)
- Add goldmine_tier field to SourceSegment model (optional future work)
- Change the existing `GOLDMINE_THRESHOLD` constant (GR-1 handles that)
- Change any scoring logic

## Verification Commands

```bash
# Run unit tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v -k "tier" --tb=short

# Verify constants exist
grep -n "TIER.*THRESHOLD" src/extraction/segment_enricher.py

# Verify method exists
grep -n "def classify_tier" src/extraction/segment_enricher.py

# Verify no pipeline changes
git diff src/extraction/extraction_pipeline.py  # Should be empty
```

## Expected Impact

**Before GR-4**:
- Tier thresholds scattered in extraction_pipeline.py
- No single source of truth for tier definitions
- Tier classification requires knowledge of magic numbers

**After GR-4**:
- Tier thresholds centralized in segment_enricher.py
- Single source of truth for tier definitions
- Easy tier classification via `SegmentEnricher.classify_tier(score)`
- Better testability and maintainability

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4
