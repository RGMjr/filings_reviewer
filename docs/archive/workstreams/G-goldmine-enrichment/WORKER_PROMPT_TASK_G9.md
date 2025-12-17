# WORKER PROMPT: Task G9 - Add Clustering Utilities

```
===============================================================================
TASK ID:       G9
TASK NAME:     Add goldmine clustering and summary utilities to SegmentEnricher
WORKSTREAM:    Core Enrichment Logic (Stream B)
SOURCE:        GOLDMINE_IMPROVEMENT_PLAN.md - Stream B, lines 601-666
STATUS:        ✅ COMPLETE (2025-12-17)
TIME ESTIMATE: 1-2 hours (implementation 45 min, tests 45 min)
ACTUAL TIME:   ~1 hour
RISK LEVEL:    Low
PARALLEL WITH: G10 (independent module)
===============================================================================
```

## Objective

Implement clustering utilities that group adjacent high-richness ("goldmine") segments into logical regions, plus a summary function to generate statistics for each cluster.

**Business Rationale**: SEC filings often contain dense regions with multiple related metrics in adjacent paragraphs (e.g., the "Active Consumers" section in Farfetch). Clustering enables the pipeline to identify and prioritize these goldmine regions as a unit, improving extraction quality by providing section-level context.

**Current Behavior**: Segments are enriched individually with richness scores, but there's no mechanism to identify when multiple adjacent high-richness segments form a logical cluster.

**Desired Behavior**: Two utility functions allow the pipeline to:
1. Group adjacent goldmine segments into clusters (respecting a configurable gap threshold)
2. Generate summary statistics for each cluster to support pipeline prioritization

## Prerequisites

- **G8 (Richness Score Formula)**: ✅ COMPLETE (2025-12-17, commit 3cdd3ab) - clustering depends on `richness_score` field being populated
- G4-G7 complete: ✅ Metric density, temporal, cohort, and image detection working

**Verification**: G8 is complete. The `_compute_richness_score` method exists and goldmine threshold is set:
```bash
# Confirm G8 complete - should show method at line ~445
grep -n "def _compute_richness_score" src/extraction/segment_enricher.py
# Confirm GOLDMINE_THRESHOLD constant exists
grep -n "GOLDMINE_THRESHOLD" src/extraction/segment_enricher.py
```

## Files to Modify

1. **`src/extraction/segment_enricher.py`** - Add clustering utilities (module-level functions or class methods)
2. **`tests/unit/extraction/test_segment_enricher.py`** - Add comprehensive tests for clustering

## Files to Read (Context Only)

- `src/extraction/models.py` - SourceSegment dataclass fields
- `docs/GOLDMINE_IMPROVEMENT_PLAN.md` - Reference implementation in Stream B section

## Implementation Requirements

### Core Functionality

1. **`cluster_goldmine_segments()` Function**
   - Signature: `cluster_goldmine_segments(segments: List[SourceSegment], richness_threshold: float = 6.0, max_gap: int = 3) -> List[List[SourceSegment]]`
   - Groups adjacent segments that meet or exceed `richness_threshold` into clusters
   - Segments must be sorted by `sequence_index` before clustering
   - Adjacent means: `segment[n+1].sequence_index - segment[n].sequence_index <= max_gap`
   - If gap exceeds `max_gap`, start a new cluster
   - Empty input returns empty list
   - Segments below threshold are excluded from clusters

2. **`summarize_cluster()` Function**
   - Signature: `summarize_cluster(cluster: List[SourceSegment]) -> dict`
   - Returns dictionary with cluster statistics
   - Required keys:
     - `start_sequence`: int - first segment's sequence_index
     - `end_sequence`: int - last segment's sequence_index
     - `segment_count`: int - number of segments in cluster
     - `section_heading`: Optional[str] - first segment's section_heading
     - `avg_richness`: float - mean richness_score (rounded to 2 decimals)
     - `unique_metrics`: int - count of distinct metric IDs across all segments
     - `has_definition`: bool - any segment has `contains_definition_flag=True`
     - `has_cohorts`: bool - any segment has `contains_cohort_breakdown=True`
     - `has_temporal`: bool - any segment has `contains_temporal_trend=True`
     - `has_images`: bool - any segment has `image_count > 0`
   - Empty input returns empty dict

3. **Design Decision**: Implement as module-level functions (not class methods)
   - Rationale: Clustering operates on enriched segment lists, not individual segments
   - Keep SegmentEnricher class focused on single-segment enrichment
   - Functions are stateless and easier to test

### Error Handling

- **Empty inputs**: Return empty list/dict (no exception)
- **Segments with None richness_score**: Treat as 0.0 for threshold comparison
- **Segments with None sequence_index**: Log warning, skip segment (don't crash)
- **No exceptions should propagate** from these utility functions

### Performance Requirements

- O(n log n) for sorting + O(n) for clustering = O(n log n) overall
- No external library dependencies beyond standard library
- Use `statistics.mean()` for average calculation (already imported in module)

## Test Requirements

### Coverage Target: **≥ 95%** for new clustering functions

### Test Categories (12+ tests recommended)

1. **Cluster Function Tests** (6-8 tests)
   - Empty segment list returns empty clusters
   - Single goldmine segment returns single cluster with one segment
   - Two adjacent goldmine segments form one cluster
   - Two goldmine segments with gap > max_gap form two clusters
   - Segments below threshold are excluded
   - Gap exactly at max_gap threshold (boundary test)
   - Mixed high/low richness segments
   - Unsorted input is sorted correctly

2. **Summary Function Tests** (4-6 tests)
   - Empty cluster returns empty dict
   - Single-segment cluster summary is correct
   - Multi-segment cluster aggregates statistics correctly
   - Cluster with definition flag detected
   - Cluster with mixed boolean flags
   - Handles None richness_score in average calculation

3. **Edge Cases** (2-3 tests)
   - Segments with None sequence_index are skipped
   - Large gap values work correctly
   - Custom threshold values work (e.g., threshold=8.0)

### Known Edge Cases to Test

- Segment with `richness_score=6.0` (exactly at default threshold) should be included
- Segment with `richness_score=5.99` should be excluded
- Consecutive sequence indices (gap=1) within same cluster
- Non-consecutive but within max_gap (e.g., indices 1, 3, 5 with max_gap=3)

## Acceptance Criteria

- [ ] `cluster_goldmine_segments()` implemented with correct signature
- [ ] `summarize_cluster()` implemented returning all required keys
- [ ] Functions are module-level (not class methods on SegmentEnricher)
- [ ] **12+ unit tests** covering all categories
- [ ] **Test coverage ≥ 95%** for clustering functions
- [ ] All new tests pass
- [ ] All existing tests still pass (regression)
- [ ] `mypy src/extraction/segment_enricher.py --strict` passes
- [ ] NO changes to `_enrich_segment()` or other enrichment methods
- [ ] Functions handle empty inputs gracefully (return empty, no exceptions)

## Do NOT

- Modify the `SegmentEnricher` class internals (enrichment methods)
- Change the `_compute_richness_score()` formula (G8 scope)
- Add database dependencies (clustering is in-memory only)
- Change signatures of existing functions
- Add external dependencies (use standard library only)

## Verification Commands

```bash
# Run all segment enricher tests (includes existing + new)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v

# Run only clustering tests (after adding)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v -k "cluster"

# Check coverage for segment_enricher module
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py \
  --cov=src/extraction/segment_enricher --cov-report=term-missing

# Type safety check
mypy src/extraction/segment_enricher.py --strict

# Verify no file conflicts
git diff src/extraction/segment_enricher.py  # Review changes
```

## Integration Plan (Post-G9)

**G11 (Pipeline Integration)** will call these utilities after enrichment:
```python
# In extraction_pipeline.py (G11 scope)
enricher = SegmentEnricher()
enriched_segments = enricher.enrich_batch(classified_segments)

# Cluster goldmines for logging/prioritization
from src.extraction.segment_enricher import cluster_goldmine_segments, summarize_cluster
clusters = cluster_goldmine_segments(enriched_segments)
for cluster in clusters:
    summary = summarize_cluster(cluster)
    logger.info(f"Goldmine cluster: {summary['segment_count']} segments, "
                f"avg richness {summary['avg_richness']}")
```

## Expected Impact

**Before G9**:
- Individual segments scored, but no way to identify dense regions
- Pipeline cannot prioritize goldmine sections as units

**After G9**:
- Goldmine regions identifiable as clusters
- Summary statistics enable prioritization decisions
- Logging can report "Found 3 goldmine clusters in this filing"

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim. Design your own solution.

<details>
<summary>Expand to see example structure</summary>

```python
# Example showing general approach - NOT meant to be copied directly

def cluster_goldmine_segments(
    segments: List[SourceSegment],
    richness_threshold: float = 6.0,
    max_gap: int = 3
) -> List[List[SourceSegment]]:
    """
    Group adjacent high-richness segments into clusters.

    Pseudocode:
    1. Filter segments to those meeting threshold
    2. Sort by sequence_index
    3. Iterate, starting new cluster when gap exceeds max_gap
    4. Return list of clusters
    """
    # Implementation here
    pass


def summarize_cluster(cluster: List[SourceSegment]) -> dict:
    """
    Generate statistics for a cluster.

    Pseudocode:
    1. Handle empty input
    2. Extract sequence range
    3. Compute averages and aggregates
    4. Return dict with all keys
    """
    # Implementation here
    pass
```
</details>

## Reference

- **Issue source**: GOLDMINE_IMPROVEMENT_PLAN.md Task G9
- **Dependencies**: G8 (richness score formula must be complete)
- **Related**: G11 (pipeline integration will consume these utilities)

## Documentation Updates

After implementation:
1. Update `docs/GOLDMINE_IMPROVEMENT_PLAN.md`:
   - Change G9 STATUS from `🟡 PENDING` to `✅ COMPLETE (YYYY-MM-DD)`
   - Add commit hash if applicable
2. Update `docs/README.md` if segment_enricher documentation exists
3. Verify `CLAUDE.md` does not need updates (enricher is already mentioned)

## Commit Instructions

When complete, commit with message:
```
G9: Add goldmine clustering utilities to SegmentEnricher

- Add cluster_goldmine_segments() for grouping adjacent high-richness segments
- Add summarize_cluster() for generating cluster statistics
- 12+ unit tests with ≥95% coverage

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

---

**Last Updated**: 2025-12-17
**Format Version**: 2.0 (concise requirements-focused format)
