# WORKER PROMPT: Task G8 - Implement Richness Score Formula

```
===============================================================================
TASK ID:       G8
TASK NAME:     Implement composite richness score formula in SegmentEnricher
WORKSTREAM:    Core Enrichment Logic (Stream B)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream B, lines 554-598
STATUS:        ✅ COMPLETE (2025-12-17)
COMMIT:        3cdd3ab
TIME ESTIMATE: 2 hours (implementation 60 min, tests 60 min)
ACTUAL TIME:   ~1.5 hours
RISK LEVEL:    Low
PARALLEL WITH: G9 (clustering utilities)
===============================================================================
```

## Objective

Implement the composite richness score formula (0-10 scale) in SegmentEnricher that combines all enrichment signals to identify "goldmine" segments. This is the capstone of Stream B—the richness score enables segment prioritization for human review and pipeline filtering.

**Business Rationale**: The richness score creates a single metric for identifying high-value segments. Segments scoring ≥6.0 are "goldmines"—sections with dense metrics, temporal trends, cohort analysis, definitions, and/or visual content. Analysts can sort by richness score to find the most valuable disclosures first.

**Current Behavior**: The SegmentEnricher (G4-G7) computes individual flags (metric_density, contains_temporal_trend, contains_cohort_breakdown, image_count) but the `richness_score` field remains `None` for all segments.

**Desired Behavior**: After G8, every enriched segment will have a computed `richness_score` (0.0-10.0) based on the formula below. Goldmine segments (score ≥6.0) can be identified and prioritized.

## Prerequisites

- **G4 Complete**: SegmentEnricher class with `_compute_metric_density()`, `_compute_distinct_metric_count()`
- **G5 Complete**: `_detect_temporal_trends()` method implemented
- **G6 Complete**: `_detect_cohort_breakdowns()` method implemented
- **G7 Complete**: `_detect_images()` method implemented (sets `image_count`)
- **G1 Complete**: SourceSegment has `richness_score: Optional[float] = None` field

Verify prerequisites:
```bash
# Confirm all G4-G7 methods exist
grep -n "def _compute_metric_density" src/extraction/segment_enricher.py
grep -n "def _detect_temporal_trends" src/extraction/segment_enricher.py
grep -n "def _detect_cohort_breakdowns" src/extraction/segment_enricher.py
grep -n "def _detect_images" src/extraction/segment_enricher.py
grep -n "richness_score" src/extraction/models.py

# Verify SourceSegment has all required fields
grep -n "contains_definition_flag" src/extraction/models.py
```

**Note**: If G7 is not yet complete, coordinate with that task or implement G8 with a temporary fallback (`image_count = 0` if `_detect_images` doesn't exist yet).

## Files to Modify

1. **`src/extraction/segment_enricher.py`** - Add `_compute_richness_score()` method and call it from `_enrich_segment()`
2. **`tests/unit/extraction/test_segment_enricher.py`** - Add test class `TestRichnessScore` with 15+ test methods

## Files to Read (Context Only)

- `src/extraction/segment_enricher.py` - Current implementation (~290 lines as of G6/G7)
- `tests/unit/extraction/test_segment_enricher.py` - Existing test patterns (50+ tests as of G7)
- `docs/GOLDMINE_IMPROVEMENT_PLAN.md` - Richness score specification (lines 970-1015)
- `src/extraction/models.py` - SourceSegment with all flag fields

## Implementation Requirements

### Core Functionality

1. **`_compute_richness_score()` Method**
   - Input: `segment: SourceSegment`
   - Output: `float` (richness score 0.0-10.0)
   - Sets `segment.richness_score` directly (mutation pattern matches other methods)

2. **Richness Score Formula (0-10 scale)**

   The formula awards points across 6 categories:

   | Component | Points | Calculation |
   |-----------|--------|-------------|
   | Base confidence | 0-3.0 | `classifier_confidence * 3.0` |
   | Metric density | 0-2.0 | `min(distinct_metric_count * 0.5, 2.0)` |
   | Temporal trends | 1.0 | `1.0 if contains_temporal_trend else 0` |
   | Cohort breakdowns | 1.5 | `1.5 if contains_cohort_breakdown else 0` |
   | Definitions | 1.0 | `1.0 if contains_definition_flag else 0` |
   | Images | 0-1.5 | `min(image_count * 0.5, 1.5)` |

   **Maximum theoretical score**: 3.0 + 2.0 + 1.0 + 1.5 + 1.0 + 1.5 = **10.0**

3. **Score Capping**
   - Final score MUST be capped at 10.0 (use `min(score, 10.0)`)
   - Round to 2 decimal places

4. **Goldmine Threshold**
   - Segments with `richness_score >= 6.0` are considered "goldmines"
   - Log goldmine statistics at INFO level after batch enrichment

5. **Integration with `_enrich_segment()`**
   - Add call to `_compute_richness_score(segment)` as the LAST step in `_enrich_segment()`
   - Must come after all other enrichments since it depends on their outputs
   - Order: metric density → distinct count → temporal → cohort → images → **richness score**

6. **Update `enrich_batch()` Logging**
   - After enrichment, log count of goldmine segments (score ≥6.0)
   - Log average richness score of goldmines
   - Example: `"Found 5 goldmine segments (avg richness: 7.2)"`

### Edge Case Handling

- **None classifier_confidence**: Treat as `0.0`
- **None metric_density**: Treat as `0.0` (distinct_metric_count will be `0`)
- **None image_count**: Treat as `0` (if G7 not complete yet)
- **All flags False**: Score will be `classifier_confidence * 3.0` (just base score)
- **Maximum inputs**: Score should be exactly `10.0` (not higher)

### Performance Requirements

- Score computation is O(1) - just arithmetic on precomputed fields
- No additional regex or parsing needed
- Complete in <1ms per segment

## Test Requirements

### Coverage Target: **95%+** for richness score code paths

### Test Categories (15+ tests required)

1. **Base Confidence Tests** (3-4 tests)
   - `classifier_confidence=0.0` -> base score = 0.0
   - `classifier_confidence=0.5` -> base score = 1.5
   - `classifier_confidence=1.0` -> base score = 3.0
   - `classifier_confidence=None` -> base score = 0.0

2. **Metric Density Component Tests** (3-4 tests)
   - 0 metrics -> density bonus = 0.0
   - 1 metric -> density bonus = 0.5
   - 4 metrics -> density bonus = 2.0 (capped)
   - 10 metrics -> density bonus = 2.0 (capped at max)

3. **Boolean Flag Component Tests** (3-4 tests)
   - `contains_temporal_trend=True` -> +1.0
   - `contains_cohort_breakdown=True` -> +1.5
   - `contains_definition_flag=True` -> +1.0
   - All flags False -> no bonuses

4. **Image Component Tests** (2-3 tests)
   - `image_count=0` -> image bonus = 0.0
   - `image_count=1` -> image bonus = 0.5
   - `image_count=3` -> image bonus = 1.5 (capped)
   - `image_count=5` -> image bonus = 1.5 (capped at max)

5. **Composite Score Tests** (3-4 tests)
   - Empty segment -> score = 0.0
   - Typical goldmine segment -> score ≥6.0
   - Maximum everything -> score = 10.0 exactly (not higher)
   - Real-world example from Farfetch filing characteristics

6. **Goldmine Threshold Tests** (2-3 tests)
   - Score of 5.9 -> NOT a goldmine
   - Score of 6.0 -> IS a goldmine
   - Score of 8.5 -> IS a goldmine

7. **Integration Tests** (2 tests)
   - Full `enrich_batch()` flow computes richness_score
   - Goldmine logging outputs correctly

### Known Edge Cases to Test

- All inputs at minimum (0/False/None) -> score = 0.0
- All inputs at maximum -> score = 10.0 exactly
- Partial inputs (some fields None, others populated)
- Floating point precision (ensure consistent rounding)

## Acceptance Criteria

- [ ] `_compute_richness_score()` method implemented with docstring
- [ ] Formula matches specification exactly (6 components)
- [ ] Score capped at 10.0 maximum
- [ ] Score rounded to 2 decimal places
- [ ] Goldmine threshold is 6.0
- [ ] Integrated into `_enrich_segment()` as LAST step
- [ ] `enrich_batch()` logs goldmine statistics
- [ ] **15+ unit tests** in `TestRichnessScore` class
- [ ] **Test coverage >= 95%** for new code
- [ ] All existing tests still pass (50+ tests from G4-G7)
- [ ] `mypy src/extraction/segment_enricher.py --strict` passes
- [ ] No changes to `src/extraction/models.py` (field already exists from G1)

## Do NOT

- Modify `src/extraction/models.py` (G1 already added the field)
- Modify `src/extraction/extraction_pipeline.py` (G11 will integrate)
- Add database operations (enricher is in-memory only)
- Import new external dependencies
- Modify existing G4-G7 tests (add new test class instead)
- Change the formula weights without updating the plan document

## Verification Commands

```bash
# Run all enricher tests (should include new richness score tests)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v

# Check coverage for segment_enricher module (target: 95%+)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py \
  --cov=src/extraction/segment_enricher --cov-report=term-missing

# Type safety check
mypy src/extraction/segment_enricher.py --strict

# Verify no conflicts with G4-G7 implementation
git diff src/extraction/segment_enricher.py  # Review changes

# Quick smoke test (manual)
python3 -c "
from src.extraction.segment_enricher import SegmentEnricher
from src.extraction.models import SourceSegment

enricher = SegmentEnricher()
seg = SourceSegment(
    filing_id=1,
    segment_type='paragraph',
    raw_text='As of December 31, 2015, 2016 and 2017, we had 0.8 million, 1.0 million and 1.4 million Active Consumers. We define Active Consumers as...',
    candidate_metric_ids=['cm_active_customers_total', 'cm_new_customers_acquired'],
    contains_definition_flag=True,
    classifier_confidence=0.85,
)
enricher.enrich_batch([seg])
print(f'richness_score: {seg.richness_score}')  # Should be >= 6.0
print(f'Is goldmine: {seg.richness_score >= 6.0}')  # Should be True
"
```

## Expected Impact

**Before G8**:
- `richness_score` is always `None`
- No single metric for segment quality/value
- Cannot identify goldmine sections systematically

**After G8**:
- Every segment has computed richness score (0.0-10.0)
- Goldmine segments (score ≥6.0) can be identified automatically
- Pipeline can filter/prioritize by richness score
- Analysts can sort segments by value

**Expected Goldmine Distribution** (based on Farfetch filing analysis):
- ~5-10% of segments should score ≥6.0 (goldmines)
- ~20-30% should score 3.0-6.0 (moderate value)
- ~60-70% should score <3.0 (low value/boilerplate)

## Example Implementation Reference

**Note**: This is for reference only - design your own solution.

<details>
<summary>Expand to see example structure</summary>

```python
# Example showing structure only - NOT meant to be copied directly

class SegmentEnricher:
    GOLDMINE_THRESHOLD: float = 6.0  # Score threshold for "goldmine" segments

    def _compute_richness_score(self, segment: SourceSegment) -> float:
        """
        Compute composite richness score (0-10).

        Formula components:
        - Base confidence: 0-3 points (classifier_confidence * 3.0)
        - Metric density: 0-2 points (min(distinct_metric_count * 0.5, 2.0))
        - Temporal trends: 1 point if contains_temporal_trend
        - Cohort breakdowns: 1.5 points if contains_cohort_breakdown
        - Definitions: 1 point if contains_definition_flag
        - Images: 0-1.5 points (min(image_count * 0.5, 1.5))

        Args:
            segment: Enriched segment with all fields populated

        Returns:
            Richness score (0.0-10.0)
        """
        score = 0.0

        # Base confidence (max 3.0)
        confidence = segment.classifier_confidence or 0.0
        score += confidence * 3.0

        # Metric density bonus (max 2.0)
        metric_count = segment.distinct_metric_count or 0
        score += min(metric_count * 0.5, 2.0)

        # Boolean flag bonuses
        if segment.contains_temporal_trend:
            score += 1.0
        if segment.contains_cohort_breakdown:
            score += 1.5
        if segment.contains_definition_flag:
            score += 1.0

        # Image bonus (max 1.5)
        image_count = segment.image_count or 0
        score += min(image_count * 0.5, 1.5)

        # Cap at 10.0 and round
        return round(min(score, 10.0), 2)

    def _enrich_segment(self, segment: SourceSegment) -> None:
        # ... existing G4-G7 code ...

        # G8: Compute richness score (MUST be last)
        segment.richness_score = self._compute_richness_score(segment)

    def enrich_batch(self, segments: List[SourceSegment]) -> List[SourceSegment]:
        # ... existing enrichment loop ...

        # Log goldmine statistics
        goldmines = [s for s in segments if (s.richness_score or 0) >= self.GOLDMINE_THRESHOLD]
        if goldmines:
            avg_richness = sum(s.richness_score or 0 for s in goldmines) / len(goldmines)
            logger.info(f"Found {len(goldmines)} goldmine segments (avg richness: {avg_richness:.1f})")

        return segments
```
</details>

## Post-Completion Tasks

After implementation is verified:

1. **Update GOLDMINE_IMPROVEMENT_PLAN.md**:
   - Change G8 status from `PENDING` to `COMPLETE (YYYY-MM-DD)`
   - Add commit hash to the task entry
   - Verify G9 (clustering utilities) can now proceed

2. **Clean up any temporary files** created during development

3. **Commit with message**:
   ```
   G8: Implement richness score formula in SegmentEnricher

   Add _compute_richness_score() method with 6-component formula:
   - Base confidence (0-3 points)
   - Metric density (0-2 points)
   - Temporal trends (1 point)
   - Cohort breakdowns (1.5 points)
   - Definitions (1 point)
   - Images (0-1.5 points)

   Goldmine threshold: score >= 6.0
   Includes 15+ unit tests with 95%+ coverage.
   ```

4. **Push to main branch**

## Reference

- **Issue source**: GOLDMINE_IMPROVEMENT_PLAN.md Task G8
- **Dependencies**: G4 (complete), G5 (complete), G6 (complete), G7 (must be complete)
- **Enables**: G9 (clustering utilities), G11 (pipeline integration)
- **Parallel with**: G9 (can start concurrently once G8 is complete)

---

## Completion Summary (2025-12-17)

### Implementation Details

**Files Modified:**
- `src/extraction/segment_enricher.py` - Added `_compute_richness_score()` method and `GOLDMINE_THRESHOLD` constant
- `tests/unit/extraction/test_segment_enricher.py` - Added `TestRichnessScore` class with 19 tests

**Implementation Approach:**
- Added `GOLDMINE_THRESHOLD = 6.0` class constant
- Implemented `_compute_richness_score()` with exact formula from specification
- Integrated as LAST step in `_enrich_segment()` (after G4-G7 enrichments)
- Added goldmine statistics logging in `enrich_batch()`

**Test Coverage:**
- 19 unit tests in `TestRichnessScore` class covering:
  - Base confidence component (4 tests)
  - Metric density component (4 tests)
  - Boolean flag components (4 tests)
  - Image component (3 tests)
  - Composite score tests (4 tests)
  - Goldmine threshold tests (3 tests)
  - Integration tests (2 tests)
  - Edge cases (2 tests)
- Coverage: 98% for segment_enricher.py
- All 119 tests pass

**Verification:**
- `mypy src/extraction/segment_enricher.py --strict` passes with no issues
- Smoke test confirms correct scoring behavior

**Deviations from Spec:** None - implementation matches specification exactly.

---

**Last Updated**: 2025-12-17
**Format Version**: 2.0
