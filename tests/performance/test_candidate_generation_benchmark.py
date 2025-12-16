"""
Performance benchmarks for candidate generation pipeline.

These tests measure throughput, latency, and memory usage to establish
performance baselines and detect regressions.

Run with: pytest tests/performance/ -v --benchmark-only
"""

import time
from typing import Dict, List

import pytest
from memory_profiler import memory_usage

from src.review.candidate_generator import CandidateGenerator


@pytest.mark.benchmark
class TestCandidateGenerationThroughput:
    """Benchmark candidate generation throughput."""

    def test_throughput_100_segments(self, benchmark, realistic_segments_100):
        """
        Measure throughput with 100-segment filing (small filing baseline).

        Measures how many segments per second the pipeline can process
        for a typical small-to-medium filing.

        Target: >20 segments/sec (production minimum)
        Interpretation: Higher is better. Multiply by segment count to estimate
                       total filing processing time.
        Configuration: Learned rules disabled (baseline performance)
        """
        filing_id = realistic_segments_100["filing_id"]
        company_id = realistic_segments_100["company_id"]
        segments = realistic_segments_100["segments"]

        generator = CandidateGenerator(apply_learned_rules=False)

        # Benchmark the candidate generation
        result = benchmark(
            generator.generate_for_filing,
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=None,  # No learned rules, no DB needed
        )

        # Verify candidates were generated
        assert len(result) > 0, "Should generate at least some candidates"

        # Note: Detailed stats are printed by pytest-benchmark automatically
        # We just verify the benchmark ran successfully

    def test_throughput_500_segments(self, benchmark, realistic_segments_500):
        """
        Measure throughput with 500-segment filing (large filing scalability test).

        Tests whether throughput scales linearly with input size. Should maintain
        similar segments/sec throughput as 100-segment test (within 10%).

        Target: >20 segments/sec (production minimum)
        Interpretation: Compare against 100-segment test to verify O(n) scalability.
                       5x segments should take ~5x time, not more.
        Configuration: Learned rules disabled (baseline performance)
        """
        filing_id = realistic_segments_500["filing_id"]
        company_id = realistic_segments_500["company_id"]
        segments = realistic_segments_500["segments"]

        generator = CandidateGenerator(apply_learned_rules=False)

        # Benchmark the candidate generation
        result = benchmark(
            generator.generate_for_filing,
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=None,  # No learned rules, no DB needed
        )

        # Verify candidates were generated
        assert len(result) > 0, "Should generate at least some candidates"

        # Note: Detailed stats are printed by pytest-benchmark automatically
        # We just verify the benchmark ran successfully


@pytest.mark.benchmark
class TestCandidateGenerationLatency:
    """Benchmark candidate generation latency percentiles."""

    def test_latency_percentiles(self, benchmark, realistic_segments_100):
        """
        Measure latency percentiles (p50, p95, p99) for processing consistency.

        Uses pedantic mode with multiple iterations (10 per round, 5 rounds)
        to capture latency distribution. p95/p99 show worst-case performance
        important for user experience.

        Target p95: <500ms per filing (interactive user experience)
        Interpretation: Low variance (p95 ≈ p50) indicates consistent performance.
                       High variance suggests optimization opportunities.
        Configuration: Learned rules disabled (baseline performance)
        """
        filing_id = realistic_segments_100["filing_id"]
        company_id = realistic_segments_100["company_id"]
        segments = realistic_segments_100["segments"]

        generator = CandidateGenerator(apply_learned_rules=False)

        # Run benchmark with multiple iterations to get percentile data
        result = benchmark.pedantic(
            generator.generate_for_filing,
            kwargs={
                "filing_id": filing_id,
                "company_id": company_id,
                "segments": segments,
                "db": None,
            },
            iterations=10,
            rounds=5,
        )

        # Verify candidates were generated
        assert len(result) > 0, "Should generate at least some candidates"

        # Note: Detailed stats are printed by pytest-benchmark automatically
        # We just verify the benchmark ran successfully


@pytest.mark.benchmark
class TestCandidateGenerationMemory:
    """Benchmark memory usage during candidate generation."""

    def test_memory_usage_baseline(self, realistic_segments_100):
        """
        Measure peak memory consumption during candidate generation.

        Uses memory_profiler to sample memory every 10ms during processing.
        Tracks baseline (start), peak (maximum), and increase (difference).

        Target: <100MB increase for 100-segment filing
        Interpretation: Memory increase should scale linearly with segments.
                       >500MB total suggests memory leak or inefficiency.
        Configuration: Learned rules disabled (baseline)
        Note: Not run with --benchmark-only flag. Run separately for profiling.
        """
        filing_id = realistic_segments_100["filing_id"]
        company_id = realistic_segments_100["company_id"]
        segments = realistic_segments_100["segments"]

        generator = CandidateGenerator(apply_learned_rules=False)

        def run_generation():
            """Wrapper function for memory profiling."""
            return generator.generate_for_filing(
                filing_id=filing_id,
                company_id=company_id,
                segments=segments,
                db=None,
            )

        # Measure memory usage
        # Returns list of memory measurements in MiB
        mem_usage = memory_usage(run_generation, interval=0.01, timeout=30)

        # Calculate memory statistics
        baseline_mem = mem_usage[0]
        peak_mem = max(mem_usage)
        mem_increase = peak_mem - baseline_mem

        print(f"\n  Memory usage:")
        print(f"    Baseline: {baseline_mem:.2f} MiB")
        print(f"    Peak: {peak_mem:.2f} MiB")
        print(f"    Increase: {mem_increase:.2f} MiB")

        # Target: <100MB increase
        if mem_increase > 100:
            print(f"  WARNING: Memory usage above target (100 MiB)")

        # Verify memory increase is reasonable (not a memory leak)
        assert mem_increase < 500, "Memory usage should not exceed 500 MiB"

    def test_memory_growth_over_time(self, realistic_segments_100):
        """
        Detect memory leaks by running multiple iterations.

        Processes the same filing 5 times consecutively. If memory grows
        significantly (>50MB), it suggests objects are not being garbage
        collected (memory leak).

        Target: <50MB growth over 5 iterations (indicates proper cleanup)
        Interpretation: Small growth (~5-10MB) is normal due to caching.
                       Large growth (>100MB) indicates memory leak.
        Configuration: Learned rules disabled (baseline)
        Note: Not run with --benchmark-only flag. Run separately for leak detection.
        """
        filing_id = realistic_segments_100["filing_id"]
        company_id = realistic_segments_100["company_id"]
        segments = realistic_segments_100["segments"]

        generator = CandidateGenerator(apply_learned_rules=False)

        def run_multiple_iterations():
            """Run generation 5 times."""
            for _ in range(5):
                generator.generate_for_filing(
                    filing_id=filing_id,
                    company_id=company_id,
                    segments=segments,
                    db=None,
                )

        # Measure memory usage over multiple iterations
        mem_usage = memory_usage(run_multiple_iterations, interval=0.01, timeout=60)

        baseline_mem = mem_usage[0]
        final_mem = mem_usage[-1]
        mem_growth = final_mem - baseline_mem

        print(f"\n  Memory growth over 5 iterations:")
        print(f"    Baseline: {baseline_mem:.2f} MiB")
        print(f"    Final: {final_mem:.2f} MiB")
        print(f"    Growth: {mem_growth:.2f} MiB")

        # Target: <50MB growth over 5 iterations (indicates no major leak)
        if mem_growth > 50:
            print(f"  WARNING: Possible memory leak detected (>50 MiB growth)")

        # Fail test if memory growth is excessive (likely a leak)
        assert mem_growth < 200, "Excessive memory growth suggests memory leak"


@pytest.mark.benchmark
class TestCandidateGenerationWithDB:
    """Benchmark candidate generation with database integration."""

    def test_throughput_with_learned_rules(self, benchmark, benchmark_db, realistic_segments_100):
        """
        Measure throughput with learned rules enabled (full production config).

        Tests the complete pipeline including database pattern matching.
        Compares against baseline to measure overhead of learned rules.

        Target: <10% slower than baseline (learned rules overhead should be minimal)
        Interpretation: If significantly slower (>20%), learned rules are
                       becoming a bottleneck. Optimize pattern matching or
                       reduce pattern count.
        Configuration: Learned rules enabled, requires database connection
        Note: Currently tests with 0 patterns. Add patterns to test realistic load.
        """
        filing_id = realistic_segments_100["filing_id"]
        company_id = realistic_segments_100["company_id"]
        segments = realistic_segments_100["segments"]

        generator = CandidateGenerator(apply_learned_rules=True)

        # Benchmark with DB for learned rules
        result = benchmark(
            generator.generate_for_filing,
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=benchmark_db,
        )

        # Verify candidates were generated
        assert isinstance(result, list), "Should return list of candidates"

        # Note: Detailed stats are printed by pytest-benchmark automatically
        # We just verify the benchmark ran successfully


@pytest.mark.benchmark
class TestLearnedPatternsScaling:
    """Benchmark performance impact of learned patterns at scale."""

    def test_throughput_with_1000_patterns(
        self, benchmark, db_with_1000_patterns, realistic_segments_100
    ):
        """
        Measure throughput with 1000+ learned patterns loaded.

        This test validates that pattern matching scales acceptably when
        the system has accumulated many learned patterns from human review.

        Target: <5% slower than baseline (8.4ms → <8.82ms)
        Interpretation: If significantly slower (>10%), pattern matching
                       optimization needed (e.g., pattern indexing, caching).
        Configuration: Learned rules enabled, 800+ approved patterns loaded
        """
        db, total_patterns, approved_count = db_with_1000_patterns

        filing_id = realistic_segments_100["filing_id"]
        company_id = realistic_segments_100["company_id"]
        segments = realistic_segments_100["segments"]

        generator = CandidateGenerator(apply_learned_rules=True)

        # Log pattern counts
        print(f"\n  Pattern load: {approved_count} approved / {total_patterns} total")

        # Benchmark with patterns loaded
        result = benchmark(
            generator.generate_for_filing,
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=db,
        )

        # Verify candidates were generated
        assert isinstance(result, list), "Should return list of candidates"

        # Log results for comparison
        print(f"  Candidates generated: {len(result)}")

    def test_throughput_with_2000_patterns(
        self, benchmark, benchmark_db, realistic_segments_100
    ):
        """
        Extreme stress test with 2000 patterns.

        Validates system behavior under heavy pattern load.
        Target: <10% slower than baseline
        """
        # Import helper function
        from tests.performance.conftest import _generate_synthetic_patterns

        # Generate 2000 patterns
        patterns = _generate_synthetic_patterns(2000, approved_ratio=0.8)

        approved_count = 0
        for pattern in patterns:
            status = pattern.pop("status")
            pattern_id = benchmark_db.insert_learned_pattern(**pattern)
            if status == "approved":
                with benchmark_db.get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE learned_patterns SET status = 'approved' WHERE pattern_id = %s",
                            (pattern_id,)
                        )
                approved_count += 1

        filing_id = realistic_segments_100["filing_id"]
        company_id = realistic_segments_100["company_id"]
        segments = realistic_segments_100["segments"]

        generator = CandidateGenerator(apply_learned_rules=True)

        print(f"\n  Pattern load: {approved_count} approved / 2000 total")

        result = benchmark(
            generator.generate_for_filing,
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=benchmark_db,
        )

        assert isinstance(result, list)
        print(f"  Candidates generated: {len(result)}")
