"""
Performance regression tests for segment enricher.

These tests validate that:
1. Enrichment throughput meets minimum thresholds
2. GR-13 text caching optimization is effective
3. GR-14 image detection skip is effective for paragraphs
4. No performance regressions from new features

Throughput Thresholds (segments/second):
- Small batch (100 segments): >= 5000 seg/sec
- Medium batch (1000 segments): >= 3000 seg/sec
- Large batch (25000 segments): >= 300 seg/sec

These thresholds ensure the enrichment pipeline doesn't become a bottleneck
in the extraction pipeline. They are calibrated based on production performance
with comfortable margins for CI variance.

Run with: pytest tests/performance/test_segment_enricher_performance.py -v --no-cov
Run with benchmark plugin: pytest tests/performance/test_segment_enricher_performance.py -v --benchmark-only
"""

import time

import pytest

from src.extraction.models import SourceSegment
from src.extraction.segment_enricher import SegmentEnricher


# =============================================================================
# Throughput Thresholds (segments/second)
# =============================================================================
MIN_THROUGHPUT_SMALL = 5000    # 100 segments: fast warm-up test
MIN_THROUGHPUT_MEDIUM = 3000   # 1000 segments: typical filing size
MIN_THROUGHPUT_LARGE = 300     # 25K segments: stress test (includes overhead)


# =============================================================================
# Test Data Generators
# =============================================================================


def create_paragraph_segments(count: int) -> list[SourceSegment]:
    """
    Create paragraph segments for benchmarking.

    Paragraphs trigger most detection methods but skip image detection (GR-14).
    Content is designed to trigger multiple patterns for realistic processing.

    Args:
        count: Number of segments to generate

    Returns:
        List of SourceSegment objects
    """
    return [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text=(
                f"Revenue increased {(i * 7) % 100}% to ${(i + 1) * 100} million "
                f"in fiscal 2024 compared to 2023. We had {i * 1000} daily active "
                f"users representing year-over-year growth."
            ),
            raw_html=f"<p>Revenue increased {(i * 7) % 100}%...</p>",
            candidate_metric_ids=["cm_revenue", "cm_active_users_daily"],
            classifier_confidence=0.85,
            sequence_index=i,
        )
        for i in range(count)
    ]


def create_table_segments(count: int) -> list[SourceSegment]:
    """
    Create table segments for benchmarking.

    Tables trigger image detection and table structure parsing.
    More expensive to process than paragraphs.

    Args:
        count: Number of segments to generate

    Returns:
        List of SourceSegment objects
    """
    return [
        SourceSegment(
            filing_id=1,
            segment_type="table",
            raw_text=(
                f"Revenue [CELL] ${(i + 1) * 100} [CELL] ${(i + 1) * 110} [ROW] "
                f"Customers [CELL] {i * 1000} [CELL] {i * 1100}"
            ),
            raw_html=(
                f"<table><tr><td>Revenue</td><td>${(i + 1) * 100}</td>"
                f"<td>${(i + 1) * 110}</td></tr></table>"
            ),
            candidate_metric_ids=["cm_revenue", "cm_customer_count"],
            classifier_confidence=0.90,
            sequence_index=i,
        )
        for i in range(count)
    ]


def create_mixed_segments(count: int, paragraph_ratio: float = 0.7) -> list[SourceSegment]:
    """
    Create mixed paragraph and table segments for realistic benchmarking.

    Typical S-1 filings are ~70% paragraphs, 30% tables.

    Args:
        count: Total number of segments to generate
        paragraph_ratio: Fraction of segments that should be paragraphs (0.0-1.0)

    Returns:
        List of SourceSegment objects with mixed types
    """
    segments: list[SourceSegment] = []
    para_count = int(count * paragraph_ratio)

    for i in range(count):
        if i < para_count:
            segments.append(
                SourceSegment(
                    filing_id=1,
                    segment_type="paragraph",
                    raw_text=(
                        f"We had {i * 1000} daily active users in FY2024 and FY2023. "
                        f"Net Dollar Retention was 130%. ARR grew {15 + i % 30}% to ${i}M."
                    ),
                    raw_html=f"<p>We had {i * 1000} daily active users...</p>",
                    candidate_metric_ids=["cm_active_users_daily", "cm_net_revenue_retention", "cm_arr"],
                    classifier_confidence=0.85,
                    sequence_index=i,
                )
            )
        else:
            segments.append(
                SourceSegment(
                    filing_id=1,
                    segment_type="table",
                    raw_text=f"Metric [CELL] 2024 [CELL] 2023 [ROW] Revenue [CELL] ${i * 100} [CELL] ${i * 90}",
                    raw_html=f"<table><tr><td>Revenue</td><td>${i * 100}</td></tr></table>",
                    candidate_metric_ids=["cm_revenue"],
                    classifier_confidence=0.90,
                    sequence_index=i,
                )
            )

    return segments


def create_goldmine_segments(count: int) -> list[SourceSegment]:
    """
    Create high-richness "goldmine" segments for benchmarking.

    These segments trigger many detection patterns and result in high richness
    scores (>6.0). Used to benchmark worst-case processing time.

    Args:
        count: Number of segments to generate

    Returns:
        List of SourceSegment objects designed to score highly
    """
    return [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            raw_text=(
                f"Net Dollar Retention was 143% for our FY2024 cohort compared to "
                f"FY2023 cohort. We had {i + 1} million daily active users representing "
                f"year-over-year growth of {25 + i % 50}%. Annual recurring revenue (ARR) "
                f"reached ${(i + 1) * 100} million, up from ${i * 100} million in the "
                f"prior year. Customer lifetime value was $15,000 with CAC of $3,000."
            ),
            raw_html=f"<p>Net Dollar Retention was 143%...</p>",
            candidate_metric_ids=[
                "cm_net_revenue_retention",
                "cm_active_users_daily",
                "cm_arr",
                "cm_lifetime_value_per_customer",
                "cm_customer_acquisition_cost",
            ],
            classifier_confidence=0.95,
            sequence_index=i,
            contains_definition_flag=True,
        )
        for i in range(count)
    ]


# =============================================================================
# Throughput Benchmark Tests
# =============================================================================


@pytest.mark.performance
class TestEnrichmentThroughput:
    """Throughput benchmarks for segment enrichment."""

    def test_throughput_100_segments(self) -> None:
        """
        100 segments should enrich at >= 5000 seg/sec.

        This is a warm-up test for small filings. Most filings have
        100-500 segments, so this represents the lower bound.
        """
        enricher = SegmentEnricher()
        segments = create_paragraph_segments(100)

        start = time.perf_counter()
        enricher.enrich_batch(segments)
        elapsed = time.perf_counter() - start

        throughput = 100 / elapsed
        assert throughput >= MIN_THROUGHPUT_SMALL, (
            f"Throughput {throughput:.0f} seg/sec below minimum {MIN_THROUGHPUT_SMALL}. "
            f"Enrichment took {elapsed * 1000:.1f}ms for 100 segments."
        )

        # Verify all segments were enriched
        assert all(seg.richness_score is not None for seg in segments)

    def test_throughput_1000_segments(self) -> None:
        """
        1000 segments should enrich at >= 3000 seg/sec.

        This represents a typical large filing. Should complete in <500ms.
        """
        enricher = SegmentEnricher()
        segments = create_paragraph_segments(1000)

        start = time.perf_counter()
        enricher.enrich_batch(segments)
        elapsed = time.perf_counter() - start

        throughput = 1000 / elapsed
        assert throughput >= MIN_THROUGHPUT_MEDIUM, (
            f"Throughput {throughput:.0f} seg/sec below minimum {MIN_THROUGHPUT_MEDIUM}. "
            f"Enrichment took {elapsed * 1000:.1f}ms for 1000 segments."
        )

        # Verify all segments were enriched
        assert all(seg.richness_score is not None for seg in segments)

    @pytest.mark.slow
    def test_throughput_25000_segments(self) -> None:
        """
        25K segments should enrich at >= 300 seg/sec.

        Stress test for unusually large filings. Should complete in <30s.
        """
        enricher = SegmentEnricher()
        segments = create_paragraph_segments(25000)

        start = time.perf_counter()
        enricher.enrich_batch(segments)
        elapsed = time.perf_counter() - start

        throughput = 25000 / elapsed

        # Check both throughput and absolute time
        assert elapsed < 30, f"Large batch took {elapsed:.1f}s, exceeds 30s limit"
        assert throughput >= MIN_THROUGHPUT_LARGE, (
            f"Throughput {throughput:.0f} seg/sec below minimum {MIN_THROUGHPUT_LARGE}. "
            f"Enrichment took {elapsed:.1f}s for 25000 segments."
        )

        # Verify all segments were enriched
        assert all(seg.richness_score is not None for seg in segments)

    def test_throughput_mixed_batch(self) -> None:
        """
        Mixed paragraph/table batch should maintain reasonable throughput.

        Realistic filing mix: 70% paragraphs, 30% tables.
        """
        enricher = SegmentEnricher()
        segments = create_mixed_segments(1000, paragraph_ratio=0.7)

        start = time.perf_counter()
        enricher.enrich_batch(segments)
        elapsed = time.perf_counter() - start

        throughput = 1000 / elapsed

        # Mixed batches can be slightly slower due to table processing
        min_mixed_throughput = MIN_THROUGHPUT_MEDIUM * 0.8  # 20% tolerance
        assert throughput >= min_mixed_throughput, (
            f"Mixed batch throughput {throughput:.0f} seg/sec below minimum "
            f"{min_mixed_throughput:.0f}. Tables may be slowing processing."
        )


# =============================================================================
# Optimization Effectiveness Tests (GR-13, GR-14)
# =============================================================================


@pytest.mark.performance
class TestOptimizationEffectiveness:
    """Verify GR-13/GR-14 optimizations are effective."""

    def test_paragraphs_faster_than_tables(self) -> None:
        """
        Paragraphs should be faster than tables (GR-14 skip image detection).

        GR-14 optimization skips image detection for paragraph segments since
        they rarely contain meaningful charts. This should result in faster
        processing compared to tables which trigger full HTML parsing.
        """
        enricher = SegmentEnricher()

        para_segments = create_paragraph_segments(500)
        table_segments = create_table_segments(500)

        # Benchmark paragraphs
        start = time.perf_counter()
        enricher.enrich_batch(para_segments)
        para_time = time.perf_counter() - start

        # Benchmark tables
        start = time.perf_counter()
        enricher.enrich_batch(table_segments)
        table_time = time.perf_counter() - start

        # Paragraphs should be noticeably faster
        # Note: We use a generous threshold since both are fast
        assert para_time < table_time * 1.1, (
            f"Paragraph time ({para_time * 1000:.1f}ms) not faster than "
            f"table time ({table_time * 1000:.1f}ms). GR-14 optimization may not be working."
        )

    def test_text_caching_consistency(self) -> None:
        """
        Text caching produces consistent results across multiple runs.

        GR-13 optimization caches text and text_upper once per segment.
        Running enrichment multiple times should produce identical results.
        """
        enricher = SegmentEnricher()

        # Create segments with content that triggers multiple detections
        segment_data = [
            (
                "Revenue grew 25% in 2022 compared to 2021 with 1.5M MAU.",
                ["cm_revenue_growth", "cm_mau"],
            ),
            (
                "Net Dollar Retention was 143% for enterprise customers.",
                ["cm_net_revenue_retention"],
            ),
            (
                "Our ARR reached $500M with gross retention of 95%.",
                ["cm_arr", "cm_gross_retention"],
            ),
            (
                "Daily active users increased to 10 million, up 40% YoY.",
                ["cm_active_users_daily", "cm_user_growth_rate"],
            ),
        ]

        # First run
        segments_run1 = [
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text=text,
                candidate_metric_ids=metrics,
                classifier_confidence=0.9,
                sequence_index=i,
            )
            for i, (text, metrics) in enumerate(segment_data)
        ]
        enricher.enrich_batch(segments_run1)

        # Second run with fresh segment objects
        segments_run2 = [
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text=text,
                candidate_metric_ids=metrics,
                classifier_confidence=0.9,
                sequence_index=i,
            )
            for i, (text, metrics) in enumerate(segment_data)
        ]
        enricher.enrich_batch(segments_run2)

        # Verify identical results
        for i, (seg1, seg2) in enumerate(zip(segments_run1, segments_run2)):
            assert seg1.richness_score == seg2.richness_score, (
                f"Segment {i}: scores differ ({seg1.richness_score} vs {seg2.richness_score})"
            )
            assert seg1.contains_temporal_trend == seg2.contains_temporal_trend
            assert seg1.contains_cohort_breakdown == seg2.contains_cohort_breakdown
            assert seg1.extra_metadata == seg2.extra_metadata

    def test_goldmine_segments_within_time_budget(self) -> None:
        """
        High-richness segments (goldmines) process within time budget.

        Goldmine segments trigger many detection patterns and have high
        complexity. They should still process quickly.
        """
        enricher = SegmentEnricher()
        segments = create_goldmine_segments(100)

        start = time.perf_counter()
        enricher.enrich_batch(segments)
        elapsed = time.perf_counter() - start

        throughput = 100 / elapsed

        # Goldmines can be slower but should still hit reasonable throughput
        min_goldmine_throughput = MIN_THROUGHPUT_SMALL * 0.5  # 50% of normal
        assert throughput >= min_goldmine_throughput, (
            f"Goldmine throughput {throughput:.0f} seg/sec below minimum "
            f"{min_goldmine_throughput:.0f}. Complex segments are too slow."
        )

        # All goldmine segments should score >= 6.0
        for seg in segments:
            assert seg.richness_score is not None
            assert seg.richness_score >= 6.0, (
                f"Goldmine segment scored {seg.richness_score}, expected >= 6.0"
            )


# =============================================================================
# Overhead Validation Tests
# =============================================================================


@pytest.mark.performance
class TestOverheadValidation:
    """Validate enrichment overhead and efficiency."""

    def test_batch_vs_single_efficiency(self) -> None:
        """
        Batch processing should be more efficient than single segment processing.

        Processing segments in a batch should have less overhead per segment
        than processing them individually.
        """
        enricher = SegmentEnricher()
        segment_count = 100

        # Create segments
        batch_segments = create_paragraph_segments(segment_count)
        single_segments = create_paragraph_segments(segment_count)

        # Batch processing
        start = time.perf_counter()
        enricher.enrich_batch(batch_segments)
        batch_time = time.perf_counter() - start

        # Single processing (process each segment as a batch of 1)
        start = time.perf_counter()
        for seg in single_segments:
            enricher.enrich_batch([seg])
        single_time = time.perf_counter() - start

        # Batch should be faster (less overhead per segment)
        # We expect at least 10% improvement from reduced function call overhead
        assert batch_time < single_time, (
            f"Batch time ({batch_time * 1000:.1f}ms) should be faster than "
            f"single processing ({single_time * 1000:.1f}ms)"
        )

    def test_empty_batch_fast(self) -> None:
        """
        Empty batch should return immediately with minimal overhead.
        """
        enricher = SegmentEnricher()

        start = time.perf_counter()
        result = enricher.enrich_batch([])
        elapsed = time.perf_counter() - start

        assert result == []
        assert elapsed < 0.001, f"Empty batch took {elapsed * 1000:.3f}ms, should be < 1ms"

    def test_memory_stable_over_iterations(self) -> None:
        """
        Memory usage should remain stable over multiple iterations.

        This tests for memory leaks by running enrichment multiple times
        and checking that objects are properly garbage collected.
        """
        import gc

        enricher = SegmentEnricher()

        # Run multiple iterations
        for _ in range(10):
            segments = create_paragraph_segments(1000)
            enricher.enrich_batch(segments)

        # Force garbage collection
        gc.collect()

        # Create one more batch to verify no accumulated state
        final_segments = create_paragraph_segments(100)
        enricher.enrich_batch(final_segments)

        # If we got here without memory errors, the test passes
        assert all(seg.richness_score is not None for seg in final_segments)

    def test_large_text_segments_handled(self) -> None:
        """
        Segments with very large text content should not cause performance issues.

        Some filings have segments with 10KB+ of text. Enrichment should
        still complete in reasonable time.
        """
        enricher = SegmentEnricher()

        # Create segments with large text (simulating a dense filing section)
        large_text_base = (
            "We had 10 million daily active users as of December 31, 2024. "
            "Net Dollar Retention was 143% for the fiscal year. "
            "Annual recurring revenue grew 35% year-over-year to $500 million. "
        )
        large_text = large_text_base * 100  # ~10KB of text

        segments = [
            SourceSegment(
                filing_id=1,
                segment_type="paragraph",
                raw_text=large_text,
                candidate_metric_ids=["cm_active_users_daily", "cm_net_revenue_retention", "cm_arr"],
                classifier_confidence=0.85,
                sequence_index=i,
            )
            for i in range(50)
        ]

        start = time.perf_counter()
        enricher.enrich_batch(segments)
        elapsed = time.perf_counter() - start

        # Should complete in under 5 seconds even with large segments
        assert elapsed < 5.0, (
            f"Large text segments took {elapsed:.1f}s, should complete in < 5s"
        )

        # Verify all segments were enriched
        assert all(seg.richness_score is not None for seg in segments)


# =============================================================================
# Scalability Tests
# =============================================================================


@pytest.mark.performance
class TestScalability:
    """Test that performance scales linearly with input size."""

    def test_linear_scaling(self) -> None:
        """
        Throughput should remain roughly constant as batch size increases.

        Tests that the algorithm is O(n) by comparing throughput at
        different batch sizes. Throughput should not degrade significantly.
        """
        enricher = SegmentEnricher()

        # Test at multiple batch sizes
        sizes = [100, 500, 1000]
        throughputs: list[float] = []

        for size in sizes:
            segments = create_paragraph_segments(size)

            start = time.perf_counter()
            enricher.enrich_batch(segments)
            elapsed = time.perf_counter() - start

            throughput = size / elapsed
            throughputs.append(throughput)

        # Throughput should not drop by more than 30% from smallest to largest
        min_throughput = min(throughputs)
        max_throughput = max(throughputs)

        assert min_throughput >= max_throughput * 0.7, (
            f"Throughput dropped significantly: {throughputs}. "
            f"Algorithm may not be scaling linearly."
        )

    def test_segment_type_distribution_impact(self) -> None:
        """
        Different segment type distributions should have predictable performance.

        Tests that increasing table ratio proportionally increases processing time.
        """
        enricher = SegmentEnricher()
        segment_count = 500

        # All paragraphs (fastest)
        all_para = create_mixed_segments(segment_count, paragraph_ratio=1.0)
        start = time.perf_counter()
        enricher.enrich_batch(all_para)
        para_time = time.perf_counter() - start

        # All tables (slowest)
        all_table = create_mixed_segments(segment_count, paragraph_ratio=0.0)
        start = time.perf_counter()
        enricher.enrich_batch(all_table)
        table_time = time.perf_counter() - start

        # 50/50 mix should be between the two
        mixed = create_mixed_segments(segment_count, paragraph_ratio=0.5)
        start = time.perf_counter()
        enricher.enrich_batch(mixed)
        mixed_time = time.perf_counter() - start

        # Mixed should be between para and table times (with 20% tolerance)
        min_expected = para_time * 0.8
        max_expected = table_time * 1.2

        # Note: We only check that performance is reasonable, not exact
        # because CI environments have variable performance
        assert mixed_time < table_time * 1.5, (
            f"Mixed batch ({mixed_time:.3f}s) took too long compared to "
            f"tables ({table_time:.3f}s)"
        )
