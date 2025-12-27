# WORKER PROMPT: Task GR-9 - Add Performance Instrumentation

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-9
TASK NAME:     Add structured logging for enrichment performance metrics
WORKSTREAM:    Observability
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 1 Critical Accuracy
STATUS:        🟡 PENDING
TIME ESTIMATE: 2 hours (implementation 60 min, testing 45 min, documentation 15 min)
RISK LEVEL:    NONE (logging only, no logic changes)
TASK SIZE:     S (30 min - 2 hours)
DEPENDS ON:    None
UNLOCKS:       GR-15 (performance regression tests)
BLOCKS:        None
PARALLEL WITH: GR-1, GR-2, GR-4, GR-6, GR-7, GR-8
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Add structured performance logging to the segment enrichment process to enable production monitoring, performance debugging, and pattern hit rate analysis.

**Business Rationale**: Without instrumentation, we can't diagnose slow filings, understand pattern effectiveness, or track performance regressions. Structured logging enables dashboarding, alerting, and data-driven optimization decisions.

**Current Behavior**: Minimal logging exists - we don't know how long enrichment takes, which patterns are hitting most often, or the distribution of goldmine scores.

**Desired Behavior**: After processing a batch of segments, emit structured log containing: segment count, processing time, throughput, goldmine counts by tier, average score, and pattern hit rates.

## Prerequisites

- None (standalone task)
- Understanding of Python `logging` module helpful

## Files to Modify

1. **`src/extraction/segment_enricher.py`** - Add metrics collection in `enrich_batch()` method
2. **`tests/unit/extraction/test_segment_enricher.py`** - Verify logs are emitted (optional: use caplog fixture)

## Files to Read (Context Only)

- `src/extraction/segment_enricher.py` - Find `enrich_batch()` method
- `docs/PERFORMANCE_BASELINE.md` - Reference for expected metrics

## Implementation Requirements

### Core Functionality

1. **Metrics to Collect**
   - Total segments processed
   - Processing time (start to finish)
   - Throughput (segments/second)
   - Goldmine counts: ≥6.0, ≥4.0, ≥3.0
   - Average richness score
   - Pattern hit rates (percentage of segments with each flag):
     - `contains_temporal_trend`
     - `contains_cohort_breakdown`
     - `contains_saas_indicator`
     - `contains_retention_keywords`
     - `contains_usage_keywords`
     - `contains_definition_flag`

2. **Logging Format**
   - Use structured logging with key-value pairs
   - Log at INFO level (not DEBUG, so it appears in production)
   - Single summary log at end of batch (not per-segment)

3. **Implementation Pattern**
   ```python
   import time

   def enrich_batch(self, segments: list[SourceSegment]) -> list[SourceSegment]:
       start_time = time.perf_counter()
       # ... existing logic ...
       elapsed = time.perf_counter() - start_time

       # Collect metrics
       # ... calculate counts and rates ...

       logger.info(
           "Enrichment complete: segments=%d time=%.2fs throughput=%.0f/s "
           "goldmines_t1=%d goldmines_t2=%d goldmines_t3=%d avg_score=%.2f "
           "temporal_rate=%.1f%% cohort_rate=%.1f%% ...",
           segment_count, elapsed, throughput, tier1_count, ...
       )
   ```

4. **Threshold Counts**
   - Tier 1 (≥6.0): High-value goldmines
   - Tier 2 (≥4.0, <6.0): Medium-value
   - Tier 3 (≥3.0, <4.0): Low-value

### Error Handling

- If logging fails, don't break enrichment (wrap in try/except)
- Handle empty batch (0 segments) gracefully

### Performance Requirements

- Metrics collection must add <5% overhead
- Use `time.perf_counter()` for accurate timing
- Don't iterate segments twice - collect metrics during main enrichment loop

## Test Requirements

### Coverage Target: Maintain existing coverage for `segment_enricher.py`

### Test Categories (6+ tests)

1. **Log Emission** (2 tests)
   - Enriching a batch emits summary log
   - Log contains expected fields (segments, time, throughput)

2. **Metrics Accuracy** (3 tests)
   - Segment count is accurate
   - Goldmine tier counts are accurate
   - Pattern hit rates are accurate (within rounding)

3. **Edge Cases** (2 tests)
   - Empty batch → logs with 0 counts, no division by zero
   - Single segment batch → logs correctly

### Using pytest caplog

```python
def test_enrichment_logs_summary(caplog):
    with caplog.at_level(logging.INFO):
        enricher.enrich_batch(segments)
    assert "Enrichment complete" in caplog.text
    assert "segments=" in caplog.text
```

## Acceptance Criteria

- [ ] Performance metrics collected during enrichment
- [ ] Summary log emitted at INFO level after each batch
- [ ] Log includes: segment count, time, throughput, tier counts
- [ ] Log includes: average score, pattern hit rates
- [ ] Empty batch handled gracefully (no errors)
- [ ] 6+ unit tests covering metrics logging
- [ ] All existing tests pass
- [ ] Logging adds <5% overhead (verify with simple benchmark)
- [ ] `pytest tests/unit/extraction/test_segment_enricher.py -v` passes

## Do NOT

- Log per-segment (too verbose for production)
- Log at DEBUG level (needs to be visible in production)
- Change any enrichment logic (this is observability only)
- Add external dependencies (use stdlib logging and time only)
- Store metrics in database (just log them)

## Verification Commands

```bash
# Run unit tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v -k "log or metric or performance" --tb=short

# Run all enricher tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py -v --tb=short

# Manually verify log format
python3 -c "
from src.extraction.segment_enricher import SegmentEnricher
from src.extraction.models import SourceSegment
import logging
logging.basicConfig(level=logging.INFO)
# Create test segments and enrich to see log output
"
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
import time
from typing import Counter

def enrich_batch(self, segments: list[SourceSegment]) -> list[SourceSegment]:
    if not segments:
        logger.info("Enrichment complete: segments=0 (empty batch)")
        return segments

    start_time = time.perf_counter()

    # Initialize counters
    tier_counts = {1: 0, 2: 0, 3: 0}
    flag_counts: Counter[str] = Counter()
    total_score = 0.0

    # Process segments (existing logic)
    enriched = []
    for segment in segments:
        enriched_segment = self._enrich_segment(segment)
        enriched.append(enriched_segment)

        # Collect metrics
        score = enriched_segment.richness_score or 0.0
        total_score += score
        if score >= 6.0:
            tier_counts[1] += 1
        elif score >= 4.0:
            tier_counts[2] += 1
        elif score >= 3.0:
            tier_counts[3] += 1

        # Track flag hits
        meta = enriched_segment.extra_metadata or {}
        for flag in ['contains_temporal_trend', 'contains_cohort_breakdown', ...]:
            if meta.get(flag):
                flag_counts[flag] += 1

    elapsed = time.perf_counter() - start_time
    count = len(segments)
    throughput = count / elapsed if elapsed > 0 else 0

    logger.info(
        "Enrichment complete: segments=%d time=%.2fs throughput=%.0f/s "
        "goldmines_t1=%d goldmines_t2=%d goldmines_t3=%d avg_score=%.2f "
        "temporal_rate=%.1f%% cohort_rate=%.1f%% usage_rate=%.1f%%",
        count, elapsed, throughput,
        tier_counts[1], tier_counts[2], tier_counts[3],
        total_score / count,
        100.0 * flag_counts['contains_temporal_trend'] / count,
        100.0 * flag_counts['contains_cohort_breakdown'] / count,
        100.0 * flag_counts['contains_usage_keywords'] / count,
    )

    return enriched
```
</details>

## Expected Impact

**Before GR-9**:
- No visibility into enrichment performance
- Can't diagnose slow filings
- Pattern effectiveness unknown

**After GR-9**:
- Production performance monitoring enabled
- Can identify slow filings via throughput drops
- Pattern hit rates visible for optimization decisions
- Goldmine tier distribution tracked over time
- Foundation for GR-15 performance regression tests

---

**Last Updated**: 2025-12-25
**Format Version**: 2.4
