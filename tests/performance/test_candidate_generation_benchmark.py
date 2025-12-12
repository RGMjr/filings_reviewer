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
        Measure throughput with 100-segment filing.

        Target: >20 segments/sec
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
        Measure throughput with 500-segment filing (large filing).

        Target: >20 segments/sec
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
        Measure latency percentiles (p50, p95, p99) per segment.

        Target p95: <500ms per segment
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

        Target: <100MB peak usage for 100-segment filing
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

        Runs candidate generation 5 times and checks for linear memory growth.
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
        Measure throughput with learned rules enabled (requires DB).

        This tests the full pipeline including pattern matching.
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
