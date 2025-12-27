# WORKER PROMPT: Task GR-15 - Performance Regression Tests

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GR-15
TASK NAME:     Add performance benchmarks to prevent regressions
WORKSTREAM:    Goldmine Detection - Testing
SOURCE:        docs/GOLDMINE_REMEDIATION_PLAN.md - Phase 2 Code Quality
STATUS:        🟡 PENDING
TIME ESTIMATE: 2 hours (implementation 90 min, documentation 30 min)
RISK LEVEL:    NONE (testing only, no logic changes)
TASK SIZE:     S (30 min - 2 hours)
DEPENDS ON:    GR-13 ✅, GR-14 ✅ (validates optimizations)
UNLOCKS:       None (quality gate task)
BLOCKS:        None
PARALLEL WITH: GR-18, EA-2, EA-3
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create performance regression tests that validate and protect the performance optimizations from GR-13 (text caching) and GR-14 (skip image detection for paragraphs).

**Business Rationale**: Performance optimizations without benchmarks tend to regress over time. Automated performance tests catch regressions early in CI, preventing slow enrichment from degrading the extraction pipeline.

**Current Behavior**: No formal performance benchmarks exist. GR-13/GR-14 added informal performance tests in test_segment_enricher.py (`TestTextCachingPerformance`), but no CI-integrated regression suite.

**Desired Behavior**: Performance regression tests run in CI with clear thresholds. Any commit that degrades throughput below baseline fails the test suite.

## Prerequisites

- GR-13 complete (text caching implemented)
- GR-14 complete (image detection skip for paragraphs)

## Files to Create

1. **`tests/performance/test_segment_enricher_performance.py`** - Performance benchmarks with pytest-benchmark

## Files to Modify

1. **`tests/integration/test_goldmine_detection.py`** - Add performance test class (alternative location)
2. **`requirements-dev.txt`** or `pyproject.toml` - Add pytest-benchmark dependency (if not present)

## Files to Read (Context Only)

- `src/extraction/segment_enricher.py` - Enrichment methods to benchmark
- `tests/unit/extraction/test_segment_enricher.py` lines ~4645-4680 - Existing `TestTextCachingPerformance` for reference
- `tests/performance/test_candidate_generation_benchmark.py` - Existing benchmark test structure (if exists)

## Implementation Requirements

### Core Functionality

1. **Benchmark Test Suite**
   - Use pytest-benchmark or simple time-based assertions
   - Test enrichment throughput at different batch sizes
   - Assert minimum throughput thresholds

2. **Test Cases**
   - Small batch (100 segments): Baseline warm-up test
   - Medium batch (1000 segments): Typical filing size
   - Large batch (25,000 segments): Stress test for large filings
   - Paragraph-only batch: Validate GR-14 optimization
   - Table-heavy batch: Validate table processing doesn't regress

3. **Throughput Thresholds**
   ```python
   # Minimum acceptable throughput (segments/second)
   MIN_THROUGHPUT_SMALL = 5000    # 100 segments
   MIN_THROUGHPUT_MEDIUM = 3000   # 1000 segments
   MIN_THROUGHPUT_LARGE = 300     # 25K segments (includes overhead)
   ```

4. **Enrichment Overhead Validation**
   - Measure total enrichment time vs segment processing time
   - Assert: enrichment overhead < 15% of total pipeline time

### Data Fixtures

Create representative test fixtures:

```python
def create_test_segments(count: int, segment_type: str = "paragraph") -> list[dict]:
    """Create realistic test segments for benchmarking."""
    return [
        {
            "segment_id": f"seg_{i}",
            "filing_id": 1,
            "raw_text": "We had 10 million daily active users as of December 31, 2024.",
            "segment_type": segment_type,
            "raw_html": "<p>We had 10 million daily active users...</p>" if segment_type == "paragraph"
                       else "<table><tr><td>DAU</td><td>10M</td></tr></table>",
        }
        for i in range(count)
    ]
```

### Error Handling

- **Benchmark variance**: Allow 10% variance between runs
- **CI flakiness**: Run benchmark 3x, use median time
- **Skip in CI if needed**: Mark with `@pytest.mark.slow` for optional skip

### Performance Requirements

Tests themselves should complete quickly:
- Small batch test: < 2 seconds
- Medium batch test: < 5 seconds
- Large batch test: < 30 seconds
- Full suite: < 45 seconds

## Test Requirements

### Coverage Target: **N/A** (performance tests don't add coverage)

### Test Categories (8-10 tests)

1. **Throughput Benchmarks** (4-5 tests)
   - `test_throughput_100_segments`: ≥ 5000 seg/sec
   - `test_throughput_1000_segments`: ≥ 3000 seg/sec
   - `test_throughput_25000_segments`: ≥ 300 seg/sec
   - `test_paragraph_batch_fast`: Paragraphs should be faster than tables
   - `test_table_batch_baseline`: Tables maintain reasonable throughput

2. **Overhead Validation** (2-3 tests)
   - `test_enrichment_overhead_acceptable`: < 15% of processing time
   - `test_batch_vs_single_efficiency`: Batch processing is faster
   - `test_memory_overhead_reasonable`: No memory leaks in large batches

3. **Optimization Verification** (2 tests)
   - `test_text_caching_improves_throughput`: GR-13 validation
   - `test_image_skip_improves_paragraphs`: GR-14 validation

## Acceptance Criteria

- [ ] Performance test file created at `tests/performance/test_segment_enricher_performance.py`
- [ ] 8+ benchmark tests covering small/medium/large batches
- [ ] Throughput thresholds defined and enforced
- [ ] Tests pass on current codebase (baseline captured)
- [ ] Large batch (25K segments) completes in < 30 seconds
- [ ] Medium batch (1K segments) achieves ≥ 3000 seg/sec
- [ ] Tests marked with `@pytest.mark.performance` or `@pytest.mark.slow`
- [ ] All existing tests still pass
- [ ] Documentation in test file explaining thresholds

## Do NOT

- Modify `segment_enricher.py` (testing only)
- Add complex benchmarking frameworks beyond pytest-benchmark
- Set unrealistic thresholds that will cause flaky tests
- Remove existing performance tests in `test_segment_enricher.py`

## Verification Commands

```bash
# Run performance tests only
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/performance/test_segment_enricher_performance.py -v --benchmark-only

# Run with benchmark stats
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/performance/test_segment_enricher_performance.py -v \
  --benchmark-min-rounds=3 --benchmark-disable-gc

# Quick check without benchmark plugin (time-based assertions)
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/performance/ -v --no-cov

# Verify no regressions in main test suite
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_segment_enricher.py --no-cov -q
```

## Example Implementation Reference

**Note**: This is for reference only - do NOT copy verbatim.

<details>
<summary>Expand to see example structure</summary>

```python
# tests/performance/test_segment_enricher_performance.py
"""
Performance regression tests for segment enricher.

These tests validate that:
1. Enrichment throughput meets minimum thresholds
2. GR-13 text caching optimization is effective
3. GR-14 image detection skip is effective
4. No performance regressions from new features

Run with: pytest tests/performance/ -v --benchmark-only
"""
import time
import pytest
from src.extraction.segment_enricher import SegmentEnricher


# Throughput thresholds (segments/second)
MIN_THROUGHPUT_SMALL = 5000    # 100 segments
MIN_THROUGHPUT_MEDIUM = 3000   # 1000 segments
MIN_THROUGHPUT_LARGE = 300     # 25K segments


def create_paragraph_segments(count: int) -> list[dict]:
    """Create paragraph segments for benchmarking."""
    return [
        {
            "segment_id": f"para_{i}",
            "filing_id": 1,
            "raw_text": f"Revenue increased {i * 10}% to $100 million in fiscal 2024.",
            "segment_type": "paragraph",
            "raw_html": f"<p>Revenue increased {i * 10}%...</p>",
        }
        for i in range(count)
    ]


def create_table_segments(count: int) -> list[dict]:
    """Create table segments for benchmarking."""
    return [
        {
            "segment_id": f"table_{i}",
            "filing_id": 1,
            "raw_text": f"Revenue [CELL] ${i * 100} [CELL] ${i * 110} [ROW]",
            "segment_type": "table",
            "raw_html": f"<table><tr><td>Revenue</td><td>{i * 100}</td></tr></table>",
        }
        for i in range(count)
    ]


class TestEnrichmentThroughput:
    """Throughput benchmarks for segment enrichment."""

    @pytest.mark.performance
    def test_throughput_100_segments(self):
        """100 segments should enrich at ≥5000 seg/sec."""
        enricher = SegmentEnricher()
        segments = create_paragraph_segments(100)

        start = time.perf_counter()
        enricher.enrich_batch(segments)
        elapsed = time.perf_counter() - start

        throughput = 100 / elapsed
        assert throughput >= MIN_THROUGHPUT_SMALL, (
            f"Throughput {throughput:.0f} seg/sec below minimum {MIN_THROUGHPUT_SMALL}"
        )

    @pytest.mark.performance
    def test_throughput_1000_segments(self):
        """1000 segments should enrich at ≥3000 seg/sec."""
        enricher = SegmentEnricher()
        segments = create_paragraph_segments(1000)

        start = time.perf_counter()
        enricher.enrich_batch(segments)
        elapsed = time.perf_counter() - start

        throughput = 1000 / elapsed
        assert throughput >= MIN_THROUGHPUT_MEDIUM, (
            f"Throughput {throughput:.0f} seg/sec below minimum {MIN_THROUGHPUT_MEDIUM}"
        )

    @pytest.mark.performance
    @pytest.mark.slow
    def test_throughput_25000_segments(self):
        """25K segments should enrich at ≥300 seg/sec."""
        enricher = SegmentEnricher()
        segments = create_paragraph_segments(25000)

        start = time.perf_counter()
        enricher.enrich_batch(segments)
        elapsed = time.perf_counter() - start

        throughput = 25000 / elapsed
        assert throughput >= MIN_THROUGHPUT_LARGE, (
            f"Throughput {throughput:.0f} seg/sec below minimum {MIN_THROUGHPUT_LARGE}"
        )
        assert elapsed < 30, f"Large batch took {elapsed:.1f}s, exceeds 30s limit"


class TestOptimizationEffectiveness:
    """Verify GR-13/GR-14 optimizations are effective."""

    @pytest.mark.performance
    def test_paragraphs_faster_than_tables(self):
        """Paragraphs should be faster than tables (GR-14 skip image detection)."""
        enricher = SegmentEnricher()

        para_segments = create_paragraph_segments(500)
        table_segments = create_table_segments(500)

        start = time.perf_counter()
        enricher.enrich_batch(para_segments)
        para_time = time.perf_counter() - start

        start = time.perf_counter()
        enricher.enrich_batch(table_segments)
        table_time = time.perf_counter() - start

        # Paragraphs should be at least 20% faster (GR-14 skips image detection)
        assert para_time < table_time * 0.9, (
            f"Paragraph time ({para_time:.3f}s) not significantly faster than "
            f"table time ({table_time:.3f}s)"
        )
```
</details>

## Expected Impact

**Before GR-15**:
- No formal performance benchmarks
- Performance regressions go unnoticed until production
- GR-13/GR-14 optimizations could degrade without detection

**After GR-15**:
- Automated performance regression detection in CI
- Baseline throughput thresholds documented
- GR-13/GR-14 optimizations protected from regression
- Clear pass/fail for performance standards

---

**Last Updated**: 2025-12-26
**Format Version**: 2.4
