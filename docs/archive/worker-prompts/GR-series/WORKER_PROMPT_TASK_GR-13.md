# WORKER PROMPT: Task GR-13 - Cache Lowercased Text

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-13
TASK NAME:     Cache text.lower() to avoid repeated string conversions
WORKSTREAM:    Performance
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 2 Performance
STATUS:        🟡 PENDING
TIME ESTIMATE: 2.5 hours (implementation 90 min, testing 45 min, benchmarking 15 min)
RISK LEVEL:    LOW (performance optimization, no logic changes)
TASK SIZE:     M (2-4 hours)
DEPENDS ON:    None
UNLOCKS:       GR-15 (performance regression tests)
BLOCKS:        None
PARALLEL WITH: GR-11, GR-12, GR-14, GR-16, GR-17
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Cache the lowercased text once per segment instead of calling `.lower()` repeatedly in each detection method, improving enrichment performance by 20-30%.

**Business Rationale**: During segment enrichment, `text.lower()` is called multiple times across 7+ detection methods (`_detect_saas_indicators`, `_detect_usage_metrics`, `_detect_temporal_trends`, etc.). For large filings with 25,000+ segments, this creates significant overhead. Caching the lowercase conversion once per segment eliminates redundant string operations.

**Current Behavior**: Each detection method calls `text.lower()` independently, resulting in 7+ lowercase conversions per segment.

**Desired Behavior**: `text_lower = text.lower()` computed once in `_enrich_segment()` and passed to all detection methods.

## Prerequisites

- None (standalone optimization)

## Files to Modify

1. **`src/extraction/segment_enricher.py`**
   - Compute `text_lower` once in `_enrich_segment()`
   - Update all `_detect_*` method signatures to accept `text_lower` parameter
   - Use `text_lower` for case-insensitive pattern matching

2. **`tests/unit/extraction/test_segment_enricher.py`** - Verify behavior unchanged

## Files to Read (Context Only)

- `src/extraction/segment_enricher.py` lines 800-950 - Detection methods calling `.lower()`
- Performance baseline in `docs/PERFORMANCE_BASELINE.md` if exists

## Implementation Requirements

### Core Functionality

1. **Compute text_lower Once**

   In `_enrich_segment()` method:
   ```python
   def _enrich_segment(self, segment: SourceSegment) -> EnrichmentMetadata:
       text = segment.raw_text or ""
       text_lower = text.lower()  # Compute once

       # Pass to all detection methods
       if self._detect_saas_indicators(text, text_lower):
           ...
   ```

2. **Update Detection Method Signatures**

   All 7 detection methods need updated signatures:
   - `_detect_saas_indicators(self, text: str, text_lower: str) -> bool`
   - `_detect_usage_metrics(self, text: str, text_lower: str) -> bool`
   - `_detect_retention_keywords(self, text: str, text_lower: str) -> bool`
   - `_detect_temporal_trends(self, text: str, text_lower: str) -> bool`
   - `_detect_cohort_keywords(self, text: str, text_lower: str) -> bool`
   - `_detect_definition_language(self, text: str, text_lower: str) -> bool`
   - `_detect_images(self, segment: SourceSegment) -> int` (may not need text_lower)

3. **Use text_lower for Pattern Matching**

   Replace patterns like:
   ```python
   # Before
   if "monthly active users" in text.lower():

   # After
   if "monthly active users" in text_lower:
   ```

4. **Keep Original text for Position Finding**
   - When finding positions (for highlighting), use original `text`
   - When checking patterns (case-insensitive), use `text_lower`
   - Both should be passed to methods that need position info

### Error Handling

- Empty text: `text_lower` will be empty string (safe)
- None text: Handle with `text = segment.raw_text or ""`

### Performance Requirements

- Target: 20-30% reduction in enrichment time for large batches
- Measure with timing before/after on 1000+ segment batch
- No increase in memory usage per segment (text_lower is temporary)

### Test Requirements

#### Coverage Target: **Maintain existing coverage** for `segment_enricher.py`

#### Test Categories (8+ tests)

1. **Behavior Unchanged Tests** (5-6 tests)
   - SaaS detection still works correctly
   - Usage metrics still detected
   - Temporal trends still detected
   - All pattern matches unchanged
   - Richness scores identical to before

2. **Performance Tests** (2-3 tests)
   - Enrichment of 1000 segments faster than before
   - Memory usage not increased significantly
   - Large batch processing improved

### Known Edge Cases to Test

- Empty text segments
- Very large text segments (100KB+)
- Unicode text (lowercase conversion correct)
- Mixed case patterns

## Acceptance Criteria

- [ ] `text_lower` computed once in `_enrich_segment()`
- [ ] All 7+ detection methods accept `text_lower` parameter
- [ ] All case-insensitive comparisons use `text_lower`
- [ ] Original `text` preserved for position finding
- [ ] All existing tests pass (behavior unchanged)
- [ ] 8+ tests covering behavior and performance
- [ ] Benchmark shows 20%+ improvement for large batches
- [ ] No increase in per-segment memory usage

## Do NOT

- Change detection logic (only pass cached lowercase)
- Modify pattern definitions
- Add text_lower to method signatures that don't need it
- Store text_lower on segment object (temporary variable only)
- Break position-based matching that needs original case

## Verification Commands

```bash
# Run enricher tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v --tb=short

# Run richness tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher_richness.py -v --tb=short

# Quick benchmark (before/after)
python3 -c "
import time
from src.extraction.segment_enricher import SegmentEnricher
# ... benchmark code
"

# Verify no signature breaks
python3 -c "from src.extraction.segment_enricher import SegmentEnricher; print('Import OK')"
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
# In segment_enricher.py

def _enrich_segment(self, segment: SourceSegment) -> EnrichmentMetadata:
    """Enrich a single segment with metadata."""
    text = segment.raw_text or ""
    text_lower = text.lower()  # Cache once

    metadata: EnrichmentMetadata = {}

    # Pass text_lower to all detection methods
    if self._detect_saas_indicators(text, text_lower):
        metadata["contains_saas_indicator"] = True

    if self._detect_usage_metrics(text, text_lower):
        metadata["contains_usage_keywords"] = True

    if self._detect_temporal_trends(text, text_lower):
        metadata["contains_temporal_trends"] = True

    # ... other detections

    return metadata


def _detect_saas_indicators(self, text: str, text_lower: str) -> bool:
    """Detect SaaS metric indicators."""
    # Use text_lower for case-insensitive matching
    for pattern in self.SAAS_PATTERNS:
        if pattern.search(text_lower):  # Already lowercase
            return True
    return False


def _detect_usage_metrics(self, text: str, text_lower: str) -> bool:
    """Detect usage metric patterns."""
    # For simple string matching
    if "daily active users" in text_lower:
        return True

    # For regex patterns, they may already use IGNORECASE
    # but text_lower ensures consistency
    for pattern in self.USAGE_PATTERNS:
        if pattern.search(text_lower):
            return True

    return False
```
</details>

## Expected Impact

**Before GR-13**:
- 7+ `.lower()` calls per segment
- Large filing (25K segments): ~7 seconds for lowercase conversions alone
- Redundant string allocations

**After GR-13**:
- 1 `.lower()` call per segment
- Large filing: ~1 second for lowercase conversions
- 20-30% overall enrichment speedup
- Reduced memory churn

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4
